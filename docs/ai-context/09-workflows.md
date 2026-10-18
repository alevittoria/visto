# Workflows

## Start a task

1. Read `AGENTS.md`, the [router](00-index.md) and [STATUS](STATUS.md).
2. Pick the task from the user's request or the STATUS "Next work" list; load
   only the relevant context files.
3. For substantial independent work, delegate following
   [agents/README.md](../../agents/README.md); do not confuse development
   agents with the runtime AI.
4. Implement, then run the smallest relevant checks and finally
   `python scripts/verify.py`.
5. Independent review checks the delivered change before it is called done.
6. Update STATUS if the current state, known issues or next work changed.

## Running the application

Development and runs use the VS Code dev container or the Docker stack; see
[Docker](../docker.md). Locked backend/frontend setup is in
[local development](../local-development.md). The headless CLI runs in the
backend or dev container against the containerized Appium: see
[first device test](../first-device-test.md). Live results are reported
separately from local software tests.

## Parallel editing

Agree dependent contracts before parallel implementation. Never edit another
active worker's write set; keep STATUS single-writer.

## Finishing

Collect worker results, report evidence and unfinished work, update STATUS and
do not leave workers or services running after reporting completion.
