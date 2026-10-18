"""Explicit live run, configuration doctor and private local run inspection."""

import argparse
import asyncio
import json
import signal
import sys
from dataclasses import asdict, replace
from pathlib import Path

from visto.adapters.ai.openai import history_data
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.ports import PortError
from visto.application.runtime import MutableRunControl
from visto.configuration import resolve_api_key
from visto.domain.models import AgentDecision, Goal, RunLimits
from visto.domain.run import (
    AIConclusion,
    BudgetExhausted,
    Cancelled,
    InfrastructureFailure,
    Run,
    RunState,
    UserAnswer,
)
from visto.runner import RunnerSettings, build_runtime, new_run


def positive(value):
    number = int(value)
    if not 1 <= number <= 10000000:
        raise argparse.ArgumentTypeError("Expected integer between 1 and 10000000")
    return number


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run", "inspect"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", type=Path, default=Path(".work/runs"))
        if name == "inspect":
            p.add_argument("--run-id", required=True)
            continue
        p.add_argument("--device", required=name == "run", default="")
        p.add_argument("--appium-url", default="http://127.0.0.1:4723")
        p.add_argument("--model", default="gpt-6-luna")
        p.add_argument(
            "--env-file",
            type=Path,
            default=Path(".env"),
            help="Local provider-key file; process environment takes precedence",
        )
        if name == "run":
            goals = p.add_mutually_exclusive_group(required=True)
            goals.add_argument("--goal")
            goals.add_argument("--goal-file", type=Path)
            goals.add_argument(
                "--request-file",
                type=Path,
                help="UTF-8 JSON with goal, constraints, expected_result",
            )
            p.add_argument("--expected-result")
            p.add_argument("--constraint", action="append", default=[])
            p.add_argument("--wall-time-ms", type=positive, default=1200000)
            p.add_argument("--max-actions", type=positive, default=60)
            p.add_argument("--max-inferences", type=positive, default=90)
            p.add_argument("--command-timeout-ms", type=positive, default=60000)
            p.add_argument("--max-wait-ms", type=positive, default=10000)
            p.add_argument(
                "--observe-only",
                action="store_true",
                help="Disable every device mutation capability",
            )
    return root


def emit(value, output):
    output(json.dumps(value, default=str, ensure_ascii=False))


def outcome(run: Run) -> tuple[str, int]:
    match run.terminal:
        case AIConclusion(assessment=assessment):
            return assessment.verdict.value, {"passed": 0, "failed": 1, "inconclusive": 2}[
                assessment.verdict.value
            ]
        case InfrastructureFailure():
            return "infrastructure_failure", 3
        case Cancelled():
            return "cancelled", 130
        case BudgetExhausted():
            return "budget_exhausted", 4
        case _:
            return run.state.value, 5


async def summary(loop, run):
    history = await loop.store.history(run.run_id)
    decisions = [r for r in history if isinstance(r, AgentDecision)]
    usage = {}
    usage["scope"] = (
        "persisted_decisions_only; unrecorded or failed requests may incur unknown usage"
    )
    for name in ("input_tokens", "output_tokens"):
        values = [getattr(d.usage, name) for d in decisions]
        usage[name] = sum(values) if values and all(v is not None for v in values) else None
        usage[f"known_{name}"] = sum(v for v in values if v is not None)
    label, code = outcome(run)
    return {
        "run_id": run.run_id,
        "state": run.state.value,
        "outcome": label,
        "terminal": history_data(run.terminal),
        "recorded_decisions": len(decisions),
        "reported_usage": usage,
        "exit_code": code,
    }


async def execute(settings, goal, api_key, *, factory=build_runtime, prompt=input, output=print):
    control = MutableRunControl()
    loop = factory(settings, api_key, control)
    run = new_run(settings, goal, loop.clock)
    emit(
        {
            "run_id": run.run_id,
            "event": "starting_live_run",
            "device": settings.device_id,
            "model": settings.model,
            "limits": asdict(settings.limits),
            "data_directory": str(settings.data_directory.resolve()),
        },
        output,
    )
    previous_handler = None
    installed_handler = False
    waiting_for_input = False

    def interrupt(signum, frame):
        control.cancel()
        if waiting_for_input:
            raise KeyboardInterrupt

    try:
        try:
            previous_handler = signal.signal(signal.SIGINT, interrupt)
            installed_handler = True
        except ValueError:  # Embedded/testing invocation outside the main thread.
            pass
        run = await loop.start(run)
        while run.state in (RunState.WAITING_FOR_USER, RunState.PAUSED):
            # Device ownership has already been released. No background inference
            # runs while input is pending. Wall-time is checked before reacquisition.
            if run.state is RunState.WAITING_FOR_USER:
                question = run.pending_question
                emit(
                    {
                        "event": "question",
                        "run_id": run.run_id,
                        "question_id": question.question_id,
                        "question": question.question,
                    },
                    output,
                )
                try:
                    waiting_for_input = True
                    answer = prompt("Answer (or /cancel): ")
                except (EOFError, KeyboardInterrupt):
                    answer = "/cancel"
                finally:
                    waiting_for_input = False
                if not answer.strip() or answer == "/cancel" or control.cancel_requested():
                    control.cancel()
                else:
                    await loop.answer(
                        UserAnswer(
                            question.question_id,
                            run.run_id,
                            answer,
                            "terminal_user",
                            loop.clock.now(),
                        )
                    )
            else:
                control.resume()
            run = await loop.resume(run.run_id)
        result = await summary(loop, run)
        emit(result, output)
        return result["exit_code"]
    except asyncio.CancelledError:
        control.cancel()
        run = await loop.store.finalize(run.run_id, Cancelled(run.run_id, loop.clock.now(), "task"))
        result = await summary(loop, run)
        emit(result, output)
        return result["exit_code"]
    except PortError:
        # A cleanup failure cannot erase a durable AI or technical terminal.
        run = await loop.store.get(run.run_id)
        if run.terminal is None:
            raise
        result = await summary(loop, run)
        result.update(cleanup_failed=True, exit_code=3)
        emit(result, output)
        return 3
    finally:
        if installed_handler:
            signal.signal(signal.SIGINT, previous_handler)


def main(argv=None, *, output=print, prompt=input, factory=build_runtime):
    args = parser().parse_args(argv)
    try:
        if args.command == "inspect":
            # Inspect does not create a nonexistent data store or require a key/device.
            database = args.data_dir / "runs.sqlite3"
            if not database.is_file():
                raise ValueError("Run database does not exist")
            artifacts = LocalArtifactStore(args.data_dir / "artifacts")
            store = SQLiteRunStore(database, artifacts)

            async def inspect():
                run = await store.get(args.run_id)
                records = await store.history(args.run_id)
                emit(
                    {"run": history_data(run), "history": [history_data(r) for r in records]},
                    output,
                )

            asyncio.run(inspect())
            return 0
        settings = RunnerSettings(
            args.device or "configuration-check", args.data_dir, args.appium_url, args.model
        )
        key = resolve_api_key(args.env_file)
        if args.command == "doctor":
            emit(
                {
                    "configuration_only": True,
                    "api_key_present": bool(key.strip()),
                    "device_serial_supplied": bool(args.device),
                    "model": args.model,
                    "appium_url": args.appium_url,
                    "data_directory": str(args.data_dir.resolve()),
                    "lease_directory": str(settings.lease_directory.resolve()),
                    "device_contacted": False,
                    "provider_contacted": False,
                    "next": "Follow docs/first-device-test.md; live readiness is unverified",
                },
                output,
            )
            return 0 if key.strip() and args.device else 2
        if not key.strip():
            raise ValueError("OPENAI_API_KEY is missing; set it in .env or the process environment")
        limits = RunLimits(
            args.wall_time_ms,
            args.max_actions,
            args.max_inferences,
            args.command_timeout_ms,
            args.max_wait_ms,
        )
        settings = RunnerSettings(args.device, args.data_dir, args.appium_url, args.model, limits)
        if args.observe_only:
            settings = replace(settings, capabilities=())
        if args.request_file is not None:
            if args.constraint or args.expected_result is not None:
                raise ValueError("Request file cannot be combined with goal modifiers")
            request = json.loads(args.request_file.read_text(encoding="utf-8-sig"))
            if (
                type(request) is not dict
                or set(request) != {"goal", "constraints", "expected_result"}
                or type(request["constraints"]) is not list
            ):
                raise ValueError("Request file requires goal, constraints and expected_result")
            goal = Goal(request["goal"], tuple(request["constraints"]), request["expected_result"])
        else:
            goal_text = (
                args.goal if args.goal is not None else args.goal_file.read_text(encoding="utf-8")
            )
            goal = Goal(goal_text, tuple(args.constraint), args.expected_result)
        return asyncio.run(
            execute(settings, goal, key, factory=factory, output=output, prompt=prompt)
        )
    except ValueError as error:
        # Only local validation error messages are exposed; provider bodies never get here.
        emit({"error": "configuration_or_input", "detail": str(error)}, output)
        return 3
    except (PortError, OSError):
        emit(
            {
                "error": "technical_failure",
                "detail": (
                    "Operation failed. Inspect durable run history; check provider/Appium setup. "
                    "A retained device lease requires explicit recovery in docs/android-setup.md."
                ),
            },
            output,
        )
        return 3
    except (KeyboardInterrupt, asyncio.CancelledError):
        emit({"error": "cancelled"}, output)
        return 130


if __name__ == "__main__":
    sys.exit(main())
