"""Visto command line: setup, start, doctor, settings, live runs and run inspection."""

import argparse
import asyncio
import json
import os
import signal
import sys
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path
from urllib.parse import urlsplit

from visto.adapters.ai.openai import history_data
from visto.adapters.devices import Platform
from visto.adapters.ios.inventory import find_xcrun
from visto.adapters.settings.store import SettingsStore
from visto.adapters.storage import LocalArtifactStore, SQLiteRunStore
from visto.application.ports import PortError
from visto.application.runtime import MutableRunControl
from visto.commands.appium_process import AppiumFailed, AppiumProcess, PortBusy, appium_running
from visto.commands.data import prepare_data
from visto.commands.doctor import run_doctor
from visto.commands.doctor import xcrun_finds as xcrun_tool
from visto.commands.settings import ACTIONS, run_settings
from visto.commands.setup import run_setup
from visto.commands.start import _termination_interrupts, run_start
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
from visto.home import VistoHome, default_home
from visto.instances import registered
from visto.runner import RunnerSettings, build_runtime, new_run
from visto.toolchain import (
    Toolchain,
    ToolchainMissing,
    UnsupportedHost,
    child_env,
    host_key,
    stored_ca_bundle,
    trusted_ca_bundle,
)


def positive(value):
    number = int(value)
    if not 1 <= number <= 10000000:
        raise argparse.ArgumentTypeError("Expected integer between 1 and 10000000")
    return number


def resolved_home(args) -> VistoHome:
    return default_home() if args.home is None else VistoHome(args.home)


def resolved_data_dir(args) -> Path:
    return args.data_dir if args.data_dir is not None else resolved_home(args).data


def ios_host() -> bool:
    """Only macOS hosts offer iOS; Windows and Linux never show its options."""
    try:
        return host_key().startswith("macos-")
    except UnsupportedHost:
        return False


def platform_choices() -> list[str]:
    return [p.value for p in Platform if p is not Platform.IOS or ios_host()]


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("setup", help="Install the pinned toolchain into the Visto home")
    setup.add_argument("--home", type=Path, default=None, help="Visto home (default ~/.visto)")
    setup.add_argument(
        "--accept-android-license",
        "--accept-license",
        dest="accept_license",
        action="store_true",
        default=None,
        help="Accept the Android SDK license without prompting",
    )
    setup.add_argument("--ca-bundle", type=Path, default=None, help="PEM file of trusted CAs")
    start = sub.add_parser("start", help="Start Appium and the local console")
    start.add_argument("--home", type=Path, default=None, help="Visto home (default ~/.visto)")
    start.add_argument("--port", type=int, default=8000)
    start.add_argument("--appium-port", type=int, default=4723)
    start.add_argument("--no-browser", action="store_true")
    start.add_argument(
        "--no-ios-tunnel",
        action="store_true",
        help="macOS: do not start the iOS tunnel, so Visto never asks for the password",
    )
    settings = sub.add_parser("settings", help="Manage the provider key and show settings")
    settings.add_argument(
        "action",
        choices=ACTIONS,
        help="set-key reads one line from stdin; the key is never an argument",
    )
    settings.add_argument("--home", type=Path, default=None, help="Visto home (default ~/.visto)")
    for name in ("doctor", "run", "inspect"):
        p = sub.add_parser(name)
        p.add_argument("--home", type=Path, default=None, help="Visto home (default ~/.visto)")
        p.add_argument(
            "--data-dir", type=Path, default=None, help="Run data directory (default <home>/data)"
        )
        if name == "inspect":
            p.add_argument("--run-id", required=True)
            continue
        p.add_argument("--device", required=name == "run", default="")
        p.add_argument(
            "--platform",
            choices=platform_choices(),
            default=Platform.ANDROID.value,
            help="Target platform; the device must match it",
        )
        p.add_argument("--appium-url", default="http://127.0.0.1:4723")
        p.add_argument("--model", default="gpt-6-luna")
        if name == "doctor":
            p.add_argument("--json", action="store_true", help="Machine-readable output")
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


def ios_prerequisites(signing):
    xcrun = find_xcrun()
    return {
        "xcrun_present": xcrun is not None,
        "simulator_tooling_present": xcrun is not None and xcrun_tool(xcrun, "simctl"),
        "device_tooling_present": xcrun is not None and xcrun_tool(xcrun, "devicectl"),
        # Presence only: signing identifiers are configuration and never echoed.
        "wda_signing_configured": all(
            value.strip() for value in (signing.team_id, signing.signing_id, signing.wda_bundle_id)
        ),
    }


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


@contextmanager
def appium_for_run(home: VistoHome, appium_url: str):
    """Reuse an Appium already answering on the run's port, else run the managed one."""
    port = urlsplit(appium_url).port or 4723
    if appium_running(port):
        yield
        return
    toolchain = Toolchain(home)
    try:
        paths = toolchain.paths()
        state = toolchain.state()
    except (ToolchainMissing, ValueError):
        paths = None
    if paths is None or paths.appium_dir is None:
        raise ValueError(
            f"Appium is not running on port {port} and the managed toolchain is not"
            " installed; run 'visto setup'"
        )
    env = child_env(paths, os.environ, state.ca_bundle)
    try:
        appium = AppiumProcess.start(paths, env, port, home.logs / "appium.log")
    except PortBusy:
        raise ValueError(f"Port {port} is in use by something other than Appium") from None
    except AppiumFailed as error:
        raise ValueError(f"Appium could not start: {error}") from None
    try:
        yield
    finally:
        appium.stop()


def doctor(args, home: VistoHome, data_dir: Path, output) -> int:
    """Human checks by default; `--json` keeps the earlier configuration fields."""
    appium_port = urlsplit(args.appium_url).port or 4723
    if not args.json:
        return run_doctor(
            home, json_output=False, output=output, fields=None, appium_port=appium_port
        )
    store = SettingsStore(home)
    platform = Platform(args.platform)
    ios = ios_prerequisites(store.load().ios) if platform is Platform.IOS and ios_host() else {}
    fields = {
        "platform": platform.value,
        "configuration_only": False,
        "api_key_present": bool(store.api_key().strip()),
        "device_serial_supplied": bool(args.device),
        "model": args.model,
        "appium_url": args.appium_url,
        "data_directory": str(data_dir.resolve()),
        "lease_directory": str(home.leases.resolve()),
        **ios,
        "provider_contacted": False,
        "next": "Follow docs/first-device-test.md; live readiness is unverified",
    }
    code = run_doctor(home, json_output=True, output=output, fields=fields, appium_port=appium_port)
    # Simulator tooling is the floor. Device tooling and signing are reported
    # for physical phones but do not gate a simulator-only setup.
    toolchain = not ios or (ios["xcrun_present"] and ios["simulator_tooling_present"])
    return code if toolchain else 2


def main(argv=None, *, output=print, prompt=input, factory=build_runtime):
    args = parser().parse_args(argv)
    try:
        if args.command == "setup":
            return run_setup(
                resolved_home(args), accept_license=args.accept_license, ca_bundle=args.ca_bundle
            )
        if args.command == "start":
            return run_start(
                resolved_home(args),
                port=args.port,
                appium_port=args.appium_port,
                open_browser=not args.no_browser,
                ios_tunnel=ios_host() and not args.no_ios_tunnel,
            )
        if args.command == "settings":
            return run_settings(resolved_home(args), args.action)
    except KeyboardInterrupt:
        return 130
    try:
        home = resolved_home(args)
        data_dir = resolved_data_dir(args)
        leases = home.leases
        if args.command == "doctor":
            return doctor(args, home, data_dir, output)
        if args.command == "inspect":
            # Inspect does not create a nonexistent data store or require a key/device.
            database = data_dir / "runs.sqlite3"
            if not database.is_file():
                raise ValueError("Run database does not exist")

            async def inspect(store):
                run = await store.get(args.run_id)
                records = await store.history(args.run_id)
                emit(
                    {"run": history_data(run), "history": [history_data(r) for r in records]},
                    output,
                )

            with registered(home, "inspect"):
                prepare_data(home, data_dir)
                artifacts = LocalArtifactStore(data_dir / "artifacts")
                asyncio.run(inspect(SQLiteRunStore(database, artifacts)))
            return 0
        store = SettingsStore(home)
        stored = store.load()
        settings = RunnerSettings(
            args.device or "configuration-check",
            data_dir,
            args.appium_url,
            args.model,
            lease_directory=leases,
            platform=Platform(args.platform),
            ios_signing=stored.ios,
        )
        key = store.api_key()
        if not key.strip():
            raise ValueError(
                "Provider key is not configured; set it in the console Settings page"
                " or with 'visto settings set-key'"
            )
        limits = RunLimits(
            args.wall_time_ms,
            args.max_actions,
            args.max_inferences,
            args.command_timeout_ms,
            args.max_wait_ms,
        )
        settings = RunnerSettings(
            args.device,
            data_dir,
            args.appium_url,
            args.model,
            limits,
            lease_directory=leases,
            platform=Platform(args.platform),
            ios_signing=stored.ios,
        )
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
        with registered(home, "run"):
            prepare_data(home, data_dir)
            with (
                _termination_interrupts(),
                appium_for_run(home, args.appium_url),
                # The provider worker inherits this process's environment.
                trusted_ca_bundle(stored_ca_bundle(Toolchain(home))),
            ):
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


def entry() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entry()
