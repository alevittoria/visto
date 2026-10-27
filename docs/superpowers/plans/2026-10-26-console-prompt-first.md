# Prompt-First Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the console say "write the goal and start" at a glance, and turn the run view into a live-progress page (now / question / outcome / previous steps) with one-click rerun and automatic device discovery.

**Architecture:** Frontend only. New pure modules hold the decisions (`steps.ts` for step grouping, `start.ts` for start-screen state, rerun and device-polling rules) with node tests; React components become thin renderers. The flat evidence timeline, the large current-screen panel, the readiness panel and the full-page form are replaced. No backend or API change.

**Tech Stack:** React 19 + TypeScript 5.9, Vite, node `--test` on `.mjs` tests importing `.ts` sources, plain CSS in `frontend/src/style.css`.

**Spec:** `docs/superpowers/specs/2026-10-26-console-prompt-first-design.md`

## Global Constraints

- Follow `AGENTS.md`: frontend-only, device and app anonymity in every fixture, docs and commit (fictional app names only, e.g. "Pantry Notes"), no device contact or billable inference to verify the work, docs describe current state only.
- No backend/API change. Mutations are never retried automatically; an uncertain response goes to the existing Reconnect/Refresh path.
- Keep existing safety copy: cancel confirmation, delete confirmations, "answer clarifies but does not change the goal", receipts are technical only, outcomes that are not a verdict say so.
- UI copy stays in English. Reuse the color tokens in `style.css`; no new dependency.
- Accessibility: every control labelled; status, question and outcome regions `aria-live`; keyboard-operable menus/disclosures (Escape closes, focus returns to the trigger); goal focused on the start screen; answer field focused when a question appears.
- Implementer brief: frontend engineer with strong UI/UX design skill (`agents/roles/frontend.md`), aiming for a calm, uncluttered, modern layout (clear hierarchy, generous whitespace, one primary action per screen).
- Checks: `cd frontend && pnpm test && pnpm lint && pnpm build`. Final: `python scripts/verify.py` and `python scripts/check_project.py`.
- Work on branch `feature/console-prompt-first`. Commit steps run only if the user has asked for commits; otherwise leave changes uncommitted.

## Review Focus

1. **Run with zero decisions yet / only an observation** → step list shows "Waiting for the first AI step", Now block shows the same; no crash (Task 1 `groupSteps handles observations before any decision`).
2. **Device list fails or returns `available: false` while polling** → error shown in the device menu/notice, polling continues at the same bounded interval, never tight-loops (Task 2 `nextDevicePoll keeps interval after failure`).
3. **Rerun clicked twice quickly / while a create is in flight** → one request only (Task 5 guard reuses `submitting`; Task 2 `rerunPlan` is pure, caller guards).
4. **Question answered from another tab, or cancelled** → question block disappears based on stored `pending_question.answer` / `cancelled_at`, no resume sent (Task 4 shows the block only from `controlAvailability().answer` or a stored answer awaiting resume, and sends resume only after a confirmed answer).
5. **Very long goal (16 000 chars) or long AI rationale** → header goal clamped with expand, Now block scrolls inside, layout never scrolls horizontally at 360 px wide (Task 3/4 CSS; checked in Task 6 visual pass).

---

### Task 1: Step grouping module

**Files:**
- Create: `frontend/src/steps.ts`
- Test: `frontend/tests/steps.test.mjs`

**Interfaces:**
- Consumes: `HistoryEntry`, `DecisionEntry`, `ObservationEntry`, `ActionEntry`, `ReceiptEntry` from `history.ts`.
- Produces:
  ```ts
  export type StepEffect = 'achieved' | 'not_achieved' | 'unclear' | 'pending' | 'none';
  export interface Step {
    number: number;                 // 1-based, counts decisions
    decision: DecisionEntry | null; // null only for records before the first decision when no decision exists yet
    action: ActionEntry | null;
    receipt: ReceiptEntry | null;
    summary: string;                // action description, or "Wait and look again", "Asked a question", "Concluded"
    effect: StepEffect;             // judged by the NEXT decision's previous_effect for this step's action
    effectExplanation: string | null;
    thumbnail: ObservationEntry | null; // decision's source observation
    records: HistoryEntry[];        // every entry belonging to this step, in sequence order
  }
  export function groupSteps(entries: HistoryEntry[], observations: Map<string, ObservationEntry>): Step[]; // oldest first
  export function currentStepNumber(steps: Step[]): number; // 0 when none
  ```

- [ ] **Step 1: Write the failing tests** (reuse the fixture style of `tests/history.test.mjs`)
  - `groupSteps assigns each record to the decision that precedes it`: with the history fixture (obs1, d2+action x1+receipt, obs5, d6 ask, q, answer, d9 conclude) → 3 steps; step 1 `records` types `['observation','decision','action','receipt','observation']`; step 2 records include question and answer; `currentStepNumber` = 3.
  - `effect comes from the next decision`: step 1 `effect === 'achieved'`, `effectExplanation === 'App opened'`; step 3 (conclude) `effect === 'none'`.
  - `latest action awaits judgement`: a run ending after an action+receipt → last step `effect === 'pending'`.
  - `non-action decisions get a row`: `observe_after` → summary `'Wait and look again'`, `ask_user` → `'Asked a question'`, `conclude` → `'Concluded'`, all `effect === 'none'`.
  - `rejected or uncertain receipt replaces the effect`: receipt status `rejected` → `effect === 'none'`, `receipt.status === 'rejected'`.
  - `groupSteps handles observations before any decision`: only obs1 → one step, `number: 1`, `decision: null`, `summary: 'Waiting for the first AI step'`, `records.length === 1`; `currentStepNumber` = 0.
  - `no record is dropped`: sum of `records.length` over steps equals `entries.length`, including an `unknown` entry.
  - `effect matches by action id`: if the next decision's `previous_effect.action_id` differs from this step's action id, this step's effect stays `'pending'` (a mismatched judgement is never attached).

- [ ] **Step 2: Run** `cd frontend && node --test --test-isolation=none tests/steps.test.mjs` → FAIL (module missing).
- [ ] **Step 3: Implement `groupSteps` / `currentStepNumber` in `frontend/src/steps.ts`.** Records before the first decision go into step 1 (the first decision's step). Header comment: pure projection, never infers a test verdict.
- [ ] **Step 4: Run** the test file → PASS; `pnpm lint` → no errors.
- [ ] **Step 5: Commit** (if authorized): `feat(console): group run history into AI steps`

---

### Task 2: Start, rerun and polling rules

**Files:**
- Create: `frontend/src/start.ts`
- Test: `frontend/tests/start.test.mjs`

**Interfaces:**
- Consumes: `Readiness`, `AttachedDevice`, `Run`, `Limits`, `createBlockReason`, `canCreateRun` (console.ts); `RunForm`, `CreateRunRequest`, `emptyForm`, `formFromRun`, `pickDevice`, `buildRunRequest`, `LIMIT_FIELDS`, `displayLimit` (form.ts).
- Produces:
  ```ts
  export type NoticeTone = 'blocked' | 'warning';
  export interface StartNotice { tone: NoticeTone; text: string; action: { label: string; target: 'settings' | 'run'; runId?: string } | null }
  export function startNotices(readiness: Readiness | null, connected: boolean): StartNotice[]; // [] when ready
  export function changedOptionCount(form: RunForm, defaults: Limits): number;
  export type RerunPlan = { kind: 'create'; request: CreateRunRequest } | { kind: 'blocked'; reason: string };
  export function rerunPlan(run: Run, devices: AttachedDevice[], readiness: Readiness | null, connected: boolean, defaults: Limits): RerunPlan;
  export interface PollInput { selectableCount: number; runOpen: boolean; pageVisible: boolean }
  export const DEVICE_POLL_MS = 5000;
  export function nextDevicePoll(input: PollInput): number | null; // ms, or null = stop
  ```

- [ ] **Step 1: Write the failing tests**
  - `startNotices is empty when ready`; `unreachable service` → one `blocked` notice with the `createBlockReason` text; `missing key` → `blocked`, action `{label:'Open settings', target:'settings'}`; `open run` → `blocked`, action `{label:'View open run', target:'run', runId}`; `cleanup attention` with ready service → one `warning` notice, action `target:'run'` for the first id, and `canCreateRun` still true (non-blocking).
  - `changedOptionCount`: empty form → 0; expected result set → 1; plus one constraint and observe-only → 3; a model set (non-blank) counts 1; a limit edited away from default → +1; limit equal to default text → 0.
  - `rerunPlan creates with the same settings`: device listed and selectable → `kind:'create'`, request equals `buildRunRequest(pickDevice(formFromRun(...)))` with goal, constraints, observe-only, limits and model of the stored run, `platform` from the device.
  - `rerunPlan blocks a missing device`: device absent or `selectable:false` → `blocked`, reason `'The device used by this run is not ready. Use Edit and rerun to pick another one.'`
  - `rerunPlan blocks a model no longer offered`: run model not in `readiness.models` → `blocked`, reason `'The AI model used by this run is no longer offered. Use Edit and rerun to choose one.'`
  - `rerunPlan blocks when the service cannot start runs`: returns the `createBlockReason` text.
  - `nextDevicePoll`: selectable 0, no run, visible → `5000`; selectable ≥1 → `null`; run open → `null`; hidden → `null`.
  - `nextDevicePoll keeps interval after failure`: callers treat a failed list as `selectableCount: 0` → still `5000` (document in JSDoc).

- [ ] **Step 2: Run** `node --test --test-isolation=none tests/start.test.mjs` → FAIL.
- [ ] **Step 3: Implement in `frontend/src/start.ts`.** `rerunPlan` checks, in order: service block reason → model offered (blank stored model = server default, allowed) → device selectable → `buildRunRequest` errors (return first error text as reason).
- [ ] **Step 4: Run** → PASS; `pnpm lint` clean.
- [ ] **Step 5: Commit** (if authorized): `feat(console): add start notices, rerun and device polling rules`

---

### Task 3: Prompt-first start screen

**Files:**
- Create: `frontend/src/components/StartScreen.tsx` (replaces `NewRunForm.tsx`), `frontend/src/components/DeviceChip.tsx` (replaces `DeviceSelect.tsx`), `frontend/src/components/OptionsPanel.tsx`
- Delete: `frontend/src/components/NewRunForm.tsx`, `frontend/src/components/DeviceSelect.tsx`, `frontend/src/components/ReadinessPanel.tsx`
- Modify: `frontend/src/App.tsx` (render `StartScreen`, drop `ReadinessPanel`), `frontend/src/components/SettingsView.tsx` (add a small "Service" section: version, device automation URL, provider-key/configuration status previously in readiness), `frontend/src/style.css`

**Interfaces:**
- Consumes: Task 2 `startNotices`, `changedOptionCount`, `nextDevicePoll`, `DEVICE_POLL_MS`; existing `parseDevices`, `deviceLabel`, `emptyDeviceHint`, `reconcileDevice`, `pickDevice`, `buildRunRequest`, `appendTranscript`, `DictateButton`.
- Produces: `StartScreen` with the same props as today's `NewRunForm` plus `onOpenSettings: () => void`, `onOpenRun: (id: string) => void`, `health: HealthState`; `DeviceChip({ value, onSelect, onLoaded, invalid, platforms, pollingAllowed: boolean })`.

Behavior (from spec):
- Centered heading **"What do you want to test?"**, goal textarea autofocused, `Enter` submits, `Shift+Enter` newline (ignore Enter during IME composition). Dictate button inside the input frame. Placeholder uses a fictional example ("In Pantry Notes, add “milk” to the list and check it appears").
- Chip row inside the input frame: Device chip, Options chip (`Options` or `Options · N changed`), primary **Start** button (`Starting…` while submitting).
- Device chip menu: device list (non-selectable entries disabled with reason), status line, manual Refresh, notes. Lists on mount, on menu open, on `visibilitychange`/`focus` when visible, and on `nextDevicePoll` timer; abort the previous request before a new one; auto-select via `reconcileDevice` only when the user has not explicitly chosen another device.
- Options panel (disclosure/popover): model, expected result (+dictation), constraints, observe-only, limits — same validation, help text and error display as today's form; field errors open the panel and focus the first invalid field.
- Notice line above the input from `startNotices` (render each; `blocked` styled as today's `.blocked`, `warning` lighter) with its action link.
- Privacy line under the input, always visible, short form: "Starting sends screenshots and your test text to the AI provider{observeOnly ? '' : ' and lets the AI operate the device'}. Use a test device and synthetic data." plus a `details` disclosure with today's full text (including dictation).
- Create error / uncertain + Refresh button next to Start, as today.

- [ ] **Step 1:** Build the components and wire `App.tsx`; delete replaced files.
- [ ] **Step 2: Run** `cd frontend && pnpm test && pnpm lint && pnpm build` → all pass (update or remove tests that imported deleted modules only if they tested UI; `tests/devices.test.mjs` tests console.ts helpers and must still pass unchanged).
- [ ] **Step 3: Commit** (if authorized): `feat(console): prompt-first start screen with device and options chips`

---

### Task 4: Live-progress run view

**Files:**
- Create: `frontend/src/components/RunHeader.tsx`, `QuestionBlock.tsx`, `NowBlock.tsx`, `OutcomeBlock.tsx`, `StepList.tsx`, `RunDetails.tsx`
- Delete: `frontend/src/components/CurrentScreen.tsx`, `frontend/src/components/RunControls.tsx`
- Modify: `frontend/src/components/RunView.tsx`, `frontend/src/components/EvidenceHistory.tsx` (keep only `ObservationThumb`, `ActionShot` and the per-record renderer `Entry`, exported for the expanded step view; remove the flat `EvidenceHistory` list), `frontend/src/style.css`

**Interfaces:**
- Consumes: Task 1 `groupSteps`, `currentStepNumber`, `Step`; Task 2 `rerunPlan`; existing `controlAvailability`, `outcome`, `outcomeExplanation`, `cleanupWarning`, `latestDecision`, `EFFECT_LABELS`.
- Produces: `RunView` props add `onRerun: (run: Run) => Promise<void>` (one-click) and rename the old prefill callback to `onEditRerun: (run: Run) => void`; `rerunBlockedReason: string | null` displayed after a blocked click.

Behavior (from spec + clarifications):
- **Header:** goal clamped to 2 lines with "Show more"; state badge `Running · step N` (`N = currentStepNumber`), `Paused`, `Waiting for your answer`, pending control badge; Pause/Resume/Cancel buttons (cancel keeps `window.confirm`); compact connection line, prominent only when lost.
- **Question block** (when `controlAvailability().answer` or a stored answer awaits resume): above everything, strong active color, question, answer textarea autofocused, **Send answer**. Flow: POST `answers`; on confirmed success, if `run.can_resume` after refresh (or the returned run is resumable) POST `resume`; uncertain on either → existing UNCERTAIN message + Reconnect, no further request; resume rejected (non-uncertain) → block shows recorded answer, error text, visible **Resume** button. Document title prefixed `"Input needed · "` while the question is open, restored after.
- **Now block** (running/paused, not terminal, not interrupted): latest decision's previous-effect line, rationale, next action (`entry.next`), working plan in a disclosure when changed. No large screenshot; one small thumbnail of the source observation linking to the full image.
- **Outcome block** (terminal): replaces Now; colored by `outcome(run).tone`; title by kind (AI verdict passed/failed/inconclusive, Technical failure, Cancelled, Limit reached); explanation, referenced thumbnails, recorded time. Actions: primary **Rerun** (disabled with spinner while running the plan; on `blocked` shows reason inline next to the buttons), secondary **Edit and rerun**, then links: readable report, JSON report, delete (when `canDeleteRun`).
- **Interrupted run:** neutral block with `outcomeExplanation(run)`, only **Edit and rerun**.
- **Step list:** newest first, row = step number, thumbnail, summary, effect icon with text label for screen readers (`EFFECT_LABELS`, or "Waiting for the AI to judge", rejected/uncertain receipt label). Row is a disclosure; expanded shows `records` rendered with the existing `Entry` renderer (action overlay included). Empty → "Waiting for the first AI step".
- **Details** disclosure: device, mode, model, started, tokens, cost, limits, expected result, constraints, unknown-usage note, cleanup warning (cleanup warning also shown visibly near the top when present).

- [ ] **Step 1:** Build components, rewrite `RunView`, delete replaced files.
- [ ] **Step 2: Run** `pnpm test && pnpm lint && pnpm build` → pass.
- [ ] **Step 3: Commit** (if authorized): `feat(console): live-progress run view with steps, question and outcome blocks`

---

### Task 5: Shell — collapsible history sidebar and rerun wiring

**Files:**
- Modify: `frontend/src/App.tsx`, `frontend/src/components/RunList.tsx`, `frontend/src/style.css`

**Interfaces:**
- Consumes: Task 2 `rerunPlan`; Task 4 `RunView` props; `parseDevices`, `apiRequest`.
- Produces: `App` handlers `rerun(run)` and `editRerun(run)`.

Behavior:
- Sidebar ~260 px with **New run** on top and the run list (goal, badge, time, cleanup badge, per-row delete, delete all). Token summary removed (Stats already shows totals). Collapse toggle in the top bar; collapsed state stored in `localStorage` key `visto.sidebar` inside try/catch. Below 960 px the sidebar is an overlay drawer (closed by default, Escape/backdrop closes, focus trapped while open, closes after selecting a run).
- Top bar: menu/collapse toggle, brand, Stats, Settings. Replace the brand mark letter "A" with "V".
- `rerun(run)`: if `submitting` return; set `submitting`; GET `/devices` once; `rerunPlan(...)`; `create` → existing `create(request)` path (uncertain handling included); `blocked` → pass reason to `RunView`. `editRerun(run)` = today's prefill behavior.

- [ ] **Step 1:** Implement.
- [ ] **Step 2: Run** `pnpm test && pnpm lint && pnpm build` → pass.
- [ ] **Step 3: Commit** (if authorized): `feat(console): collapsible run history and one-click rerun`

---

### Task 6: Docs, status and full verification

**Files:**
- Modify: `docs/web-console.md` (start screen, device chip and automatic discovery, options, run view blocks, rerun, history sidebar), `README.md` (feature rows mentioning console layout; GIF untouched), `docs/ai-context/STATUS.md` (coordinator only: console description; known issue "README demo GIF shows the previous console layout; re-record after the user's test round")

- [ ] **Step 1:** Update docs to describe the current state only.
- [ ] **Step 2: Run** `python scripts/check_project.py` → passes.
- [ ] **Step 3: Run** `python scripts/verify.py` → all checks pass; record actual output.
- [ ] **Step 4: Visual pass (no device, no provider):** run `cd frontend && pnpm dev`, open the console in a browser with the backend not running and check: start screen layout at 1280 px and 360 px, notice line for unreachable service, options panel, sidebar collapse/drawer, keyboard navigation. Run-view states are checked in the user's test round.
- [ ] **Step 5: Commit** (if authorized): `docs: describe the prompt-first console`
