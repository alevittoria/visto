# Local evidence and run storage

## Visto home

Visto keeps everything it stores in one folder per user, the Visto home:
`~/.visto/` (on Windows `%USERPROFILE%\.visto\`). Every command takes
`--home <folder>` to use another one; nothing is read from environment variables.

```text
~/.visto/
  settings.json                  preferences and iOS signing values (versioned format)
  secrets.json                   the provider key, in plain text
  data/
    runs.sqlite3                 run history
    runs.sqlite3.v<N>-<UTC timestamp>.bak   backup taken before a data upgrade
    artifacts/                   screenshots and their metadata
    prices.sqlite3               daily model price lists
    device-leases/<sha256(serial)>.lease    device ownership markers
  toolchain/                     Node, JDK, Android SDK tools, Appium (state.json lists the active versions)
  logs/appium.log                Appium server output
  instances/<pid>.json           running Visto processes using this home
```

`settings.json` and `secrets.json` are replaced atomically. On macOS and Linux both
are created readable and writable by your user only (mode 0600), as are
`logs/appium.log`, a newly created `runs.sqlite3` and every upgrade backup. The
folders Visto creates (the home itself, `data/` or a missing `--data-dir`,
`artifacts/`, `logs/` and `instances/`) are accessible by your user only (mode
0700), so screenshots, leases and price lists inside them are private too. Visto
never changes the mode of a folder or database that already exists, including a
`--data-dir` you created yourself; check those permissions yourself. On Windows
these files get no extra protection: they inherit the access rules of your user
profile folder, which normally admit your account, administrators and the system.
**The provider key is stored in plain text**, not in an operating-system credential store and not encrypted; anyone who can read your
profile folder can read it. The key never appears in API responses, logs, reports
or command output.

`logs/appium.log` is private: Appium can log request bodies, entered text and
device details. The `instances` folder lets setup and data upgrades refuse while
another Visto process uses the home; it holds no run data.

`visto run --data-dir <folder>` and `visto inspect --data-dir <folder>` read and
write run history elsewhere; device leases always stay in the home's
`data/device-leases`, so every process sharing a home shares them.

### Data upgrades and backups

The run database carries a schema version and is upgraded by numbered forward
migrations when a Visto command (`start`, `run` or `inspect`) opens it, normally the
first `visto start` after an upgrade. Each command refuses to upgrade an existing
database while another Visto process uses the home.
Before changing an existing database it is copied to
`runs.sqlite3.v<N>-<UTC timestamp>.bak` beside it, where `<N>` is the version
before the upgrade. A database written by a newer Visto is refused with a message
rather than opened; install that newer Visto again or, with Visto stopped, copy
the matching backup over `runs.sqlite3`. A backup holds the database only: the `artifacts`
folder is never upgraded or copied, and a restored database keeps referencing it.
`settings.json`, `secrets.json` and `toolchain/state.json` follow the same rule:
a format newer than this Visto knows is refused.

## Stores

`LocalArtifactStore(root: Path)` and
`SQLiteRunStore(database: Path, artifacts: ArtifactStore)` implement the async
application ports. They perform blocking local I/O in bounded SQLite operations
on worker threads; there is no retained connection and no `close()` requirement.
SQLite lock acquisition has a five-second timeout. Ordinary local disk failures
are reported as sanitized `PortError` values.

## Stored information

The database contains immutable request text, expected result, constraints,
model/provider/instruction identity, adapter version, technical limits, run
lifecycle revisions, observations, decisions, action intents, receipts, pending
questions, attributed answers and terminal records. Decisions preserve the exact
IDs of evidence presented to the model, its working plan and reported token
usage. Unknown usage stays unknown. AI assessments are recorded opinions, never
ground-truth labels. Technical command completion is not an application pass.

The adapter uses a versioned schema (see
[data upgrades](#data-upgrades-and-backups)) and a closed tagged JSON format with
explicit allowlisted domain types. Unknown versions, tags, duplicate JSON keys and extra
fields are rejected. No pickle or runtime imports from stored values are used.
SQL values use placeholders, including arbitrary run IDs. A connection is opened
per operation with Python 3.12 `autocommit=True`, foreign keys and full synchronous
writes. Explicit `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` transactions serialize
writers. Ordinary reads also use this transaction helper; high read concurrency
is outside the initial local CLI's scope.

History appends are run-scoped, ordered and immutable. An identical repeated
record is idempotent; the same identity with changed content is rejected. An
observation requires readable hash-checked image bytes before insertion. Source
observations and decisions precede action intent; action intent precedes receipt.
Latest-frame/decision bindings, capabilities, timeouts and coordinates are checked
without interpreting screenshot contents. Pause prevents new action intents.
Question and answer records must exist before their lifecycle snapshot is saved.

Lifecycle writes use revision compare-and-swap and reject changes to the original
goal, configuration, device or creation time. Terminal writes must use
`finalize()`: one transaction validates evidence, inserts the terminal and updates
the run. The first accepted terminal wins; competing or repeated calls return the
actual stored winner. Opening a database never changes an existing run.

## Image files and privacy

Each `put()` creates a new random artifact ID under a SHA256-derived run
directory. Input run IDs are never interpreted as paths. Exclusive file creation
prevents overwrites, and file contents and metadata sidecars are flushed and
fsynced. References bind artifact ID, owning run, media type, byte length and
SHA256 digest. Reads verify the sidecar and bytes, reject path traversal or
symlinks, and report missing or corrupt evidence explicitly.

Image filenames are opaque artifact IDs without an extension; their media type
is stored in the reference/metadata. Use an image viewer that detects PNG/JPEG
contents, or copy the file outside the evidence tree with the corresponding
extension for viewing. Do not rename or edit the original artifact/sidecar.

File storage and SQLite are not a shared transaction. Files are written first;
a crash or a later database failure can leave unreferenced files. A partial
artifact is never accepted as valid evidence. Automatic orphan cleanup is not
implemented. Directory-entry durability after sudden power loss is dependent on
the operating system/filesystem; fsync of file contents does not promise that a
directory entry survives every power-loss scenario. This is local persistence,
not an archival or encrypted evidence vault.

Screenshots, goals, entered text, decisions and answers may contain private data.
Keep the Visto home (and any `--data-dir`) outside source control and
shared/public folders. Apart from the owner-only modes described
[above](#visto-home), run data files inherit the folder's operating-system
permissions; the tool does not encrypt them or install account ACLs. Credentials
must be injected into provider adapters and are not part of these configuration
snapshots. Input text and screenshots are deliberately preserved as evidence; this
is not a general secret scrubber.

Retention is manual and indefinite by default. There is no background deletion,
upload or public artifact URL. Stop all users of the state directory before
backing up its database and artifact tree together (stop `visto start` and
any `visto run` first). Restore both together; a
database-only restore can reference absent screenshots. Remove a complete chosen
state directory only after keeping any required evidence and confirming it is
the intended directory. Provider adapters transmit selected screenshots and
context for inference; local storage does not imply local inference or provider
zero retention. See [provider setup](provider-setup.md) when available.

## Interrupted runs

A run whose owning process died stays non-terminal in the database. There is no
automatic or administrative recovery: opening the database never declares an
owner dead, no command is replayed and no AI verdict is inferred. Device
lease/session reconciliation is a separate operator task (see
[Android setup](android-setup.md)).

## Local verification

From the repository root:

```sh
uv run --project backend --locked --no-sync pytest -p no:cacheprovider backend/tests/test_storage.py -q
uv run --project backend --locked --no-sync ruff check backend/src/visto/adapters/storage backend/tests/test_storage.py
```

These tests use temporary local SQLite databases and fake image bytes. They
exercise durable reload/history, idempotency and conflicts, artifact ownership
and corruption, evidence dependencies, lifecycle CAS, immutable goals, concurrent
terminal calls and question/answer persistence.
They neither contact an Android device/provider nor measure model judgement.
