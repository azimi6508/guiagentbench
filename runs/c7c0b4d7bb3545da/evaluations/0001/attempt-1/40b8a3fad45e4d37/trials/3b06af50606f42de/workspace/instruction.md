Evaluation arm: judge_test. Produce a PASS/FAIL judgment JSON file.
Required artifact: /workspace/output/judgment.json. Save it before finishing.
Read the complete contract below. A final chat message does not submit an artifact.

The native Markor editor has an empty note named `atlas.txt` open. Put exactly
`Bring the blue notebook.` in the note. Its text must still be visible and saved
after closing and reopening the application.


Read /workspace/test_source.py to inspect the exact reference test. Predict
whether it would pass on the live native Markor application. You can manually
explore through the GUI tools but cannot execute the reference, a copy or any
other program. Save /workspace/output/judgment.json with {"verdict":"PASS"}
or {"verdict":"FAIL"} and an optional reason.


Judgment output contract: write a JSON object to /workspace/output/judgment.json.
Use exactly {"verdict":"PASS"} or {"verdict":"FAIL"}, with uppercase verdict values.
An optional "reason" string may contain at most 2000 characters. No other keys,
Markdown fences or surrounding text are permitted; the file must not exceed 16384 bytes.


Screenshot dimensions: width=720 pixels, height=1280 pixels. Coordinates are integer pixels in the original screenshot, with top-left origin (0, 0). x increases right and y increases down. Use the screenshot width and height; coordinates are not percentages or a normalized 0-1000 scale. Valid pixel positions: 0 <= x < 720, 0 <= y < 1280. click/hover x,y use these pixels directly, without automatic scaling. If you reason on a 0-1000 scale, convert to pixels before calling: x_pixel = floor(x_normalized * width / 1000), y_pixel = floor(y_normalized * height / 1000). Mobile touch restrictions and unavailable hover still apply.

Failure contract failure-v1:
GUI errors include a stable cause and a safe message. A policy_violation means
the capability is forbidden; invalid_arguments means the request does not match
the public API. target_unavailable and action_timeout do not establish whether
the model, application, or environment is responsible. Unknown causes stay unknown.
No partial evidence is returned after a failed evidence request.

target_ambiguous means that multiple elements match the exact requested target.
Use the permitted UI snapshot to choose a unique role/name, or a screenshot and
coordinate action. During authoring, target_ambiguous, target_unavailable and
invalid_arguments from step calls allow another model-chosen request without an
automatic reset, repeated action, or extra budget. Unknown errors, transport
failures, security/evidence failures and failed resets remain fatal for Codex.
Later calls preserve the original fatal cause instead of obscuring it with a
generic file-write or argument error.

device_unavailable identifies a confirmed absent, offline or unauthorized dedicated emulator.
simulator_ambiguity identifies conflicting recorded destinations for a permitted
action. Both require infrastructure review and never establish model inability.
Neither diagnostic exposes device inventory, graph states, labels or targets.

provider_capacity identifies an explicit provider server-overload response.
It is an availability failure, not a model answer failure. No automatic retry
or model substitution occurs. native_operation_in_flight means the native relay
still has unfinished work and rejected a new call without dispatching it. A
caller timeout does not cancel device work; completion must arrive before the
relay accepts another operation. Both causes require review and never imply
model blame. Operator diagnostics for native labeled controls may also record
label counts and whether a click targeted the native control or its associated
label, without recording label text or DOM.

Operator evidence extension failure-detail-v1:
Trusted failure records retain a stable failure ID, framework source locations,
safe exception kind, and available structured observations. Native driver and
broker records share the original failure ID and the private relay correlation
ID. Target counts/state and device availability describe the time observed;
they do not establish who caused the problem. Failed diagnostic probes are
marked explicitly and never replace the original operation error.

These details are for operator reports only. Public tool replies keep the same
cause/message contract. No raw exception text, stack source, locals, URLs,
credentials, command output, UI text or private labels are added. A diagnostic
check never repeats an action or changes an assertion, reward or budget.
All co-occurring blocking diagnostics remain in the run summary.

During authoring/live exploration you may respond to a tool error within the
existing budgets. This does not authorize new tools or extend any limit.
During generated oracle/test execution, every failed operation prevents credit,
even if Python catches its exception and later assertions pass. Only a valid,
comparable correct-state pass and faulty-state behavioral mismatch earn paired
credit. Crashes and timeouts never count as bug detection. The controller does
not schedule automatic trial retries.

Inference diagnostic extension inference-v1:
New provider failures retain an inference object inside failure-v1. It records
the local request number, observed boundary/stage, HTTP status when available,
allowlisted structured error code/type, stream completion and finish reasons,
elapsed time, byte counts and content-free request shape. These facts describe
what was observed, not proof that the model or a particular upstream host is
responsible. Upstream HTTP, HTTP-200 JSON/SSE errors, transport/read failures,
invalid/incomplete responses, downstream disconnects and local rejections are
distinct. Unknown free-form codes are recorded as unknown, not guessed.

Raw provider error bodies, messages, metadata, headers, generation IDs, URLs,
exception text, prompt content and arbitrary tool names never enter diagnostic
logs. Failed HTTP bodies are sampled only in memory, bounded at 64 KiB; the
sample is not admitted grading evidence. Complete generated-response evidence
still has its unchanged 8 MB cap. Usage logs accept finite nonnegative numbers
only. Provider debug echo is disabled. Error responses are replaced with safe
messages before reaching the agent, and exact selected-credential echoes in
successful JSON fields or SSE comments are blocked. This is not a guarantee
against arbitrary secret encodings in ordinary model-generated content.

The extension is controller-side only: it provides no new evaluated-agent tools,
credentials, labels or private evidence. Existing failure causes, impacts,
scoring, budgets and planned denominators remain unchanged. No automatic trial
retries are introduced. Old records without the extension remain unattributed.

Codex fatal-operation reports preserve the originating broker failure ID and
safe observations when the trusted bridge and broker ledgers identify the same
request occurrence unambiguously. Repeated identical requests are matched by
occurrence with equal ledger counts. Missing, ambiguous or malformed detail
leaves the original failure cause intact; it never admits an operation or
assigns model blame. UI evidence overflows can report the complete response byte
size and fixed byte limit without including the rejected text.
# Web target resolution and operator hit-test facts

Structured web actions resolve their exact target before dispatch, retaining
the existing bounded attachment wait for loading targets. An unresolved target
returns `target_unavailable`, using the existing nonfatal authoring feedback
contract. No action is dispatched or retried, no budget is added, and an
execution-operation failure still prevents credit. This observation does not
establish model blame. A target may become available after a later observation.
Timeouts after dispatch remain `action_timeout`; they are never reclassified
from a post-failure count alone.

Operator-only failure details may record `pre_action_matches`,
`action_dispatched`, `center_in_viewport`, `center_hits_target`, and
`pointer_events_none`. These read-only boolean/count observations contain no
DOM, target text, screenshot, exception text or extra model-visible evidence.
Failed diagnostic probes preserve the original failure.



Environment contract environment-v1:
Web reset restores the application within a task-declared bound, then waits up
to 10 seconds for DOMContentLoaded, an attached body and the task's declared
initial-screen landmarks. These identify the starting screen only,
equally in both variants; they never assert the desired task outcome.
A task that declares bundled local fonts also finishes its initial font load
inside that same ten-second deadline, after its starting landmarks are visible. This avoids
fallback-font screenshots in fresh contexts. The resource check applies only to
initial preparation; font loading never gates subsequent actions or observations.
It uses no goal assertion, animation condition or extended execution budget.
Targeted web actions use Playwright's built-in actionability waits (30-second
operation timeout). Navigation waits for DOMContentLoaded. After actions a shared
250 ms rendering pause allows immediate UI updates; it is not proof that background
work finished. Existing UI assertions retry for 1.5 seconds. Screenshots and UI
observations are not gated on global readiness, pixel stability, animations,
network quiet or busy flags. Repeated observations can inspect loading progress.
There are no app-specific animation selectors, masks or post-action wait rules.
Actions and trials are not replayed automatically.

Reset replaces the web browser context and task server state. A fresh neutral
session identifier fences stale server requests; reset acknowledgement is required.
Failed preparation/reset is an operation failure, never a successful fault detection.
Locale is en-US; viewport/timezone are pinned. Wall-clock time remains real time
unless a date-sensitive task declares its public browser Date epoch.


Native Android contract visual-v1-mobile (overrides browser-specific wording above):
The task app runs on a 720 by 1280 portrait emulator. The platform driver
is UIAutomator2. `gui_open_url` / `page.goto("http://app:8000/")` is a logical
home alias; it does not navigate a browser. Home and `reload` invoke the selected
task fixture's declared entry-point and restart behavior. `reset` restores
the initial state for tests/judge_test or the prepared final state for oracles.

Native UI dumps (UI arms only) contain visible app nodes with `role`, `name`,
`text`, `bounds`, `enabled` and `focused`. Roles are textbox, checkbox, button
and paragraph. Names use Android content descriptions, then text, with resource
IDs for unnamed nodes and textboxes. Compose controls can use hints or visible
child labels when resource IDs are absent. Exact role/name queries must be unique for
actions. Text and value assertions compare the node's exact text. No XPath,
arbitrary resource selectors, ADB, shell, package management or filesystem API.

Both visual and UI arms can use coordinate actions; taps exclude the system bars
(y must be at least 128 and less than 1244). Typing inserts into the focused
control. Escape maps to Android Back. Hover is unavailable on this native touch
surface; other listed actions retain their usual meaning. UI arms additionally
support role/name click, fill (textbox only), and press. Coordinate scroll,
focused type and press remain available in UI arms. Oracle execution remains
observation/assertions only. Actions wait for observable UI stability;
a readiness timeout is a failed operation.

Visual assertions compare screenshot pixels with sealed image references. No Android hierarchy, resource
ID or structural query is available to visual arms. Assertions still return
None and the trusted broker records their outcomes. App installation, initial
permissions and task data are controller-only. The same six arm restrictions,
submission filenames, execution budgets and paired scoring rules apply.

Authoring recovery contract `authoring-recovery-v1`:
If an authoring operation leaves the admitted app, the harness reports
`app_scope_lost` and automatically resets to this arm's starting state (the
prepared checkpoint for oracles, initial state for tests and live judges).
No screenshot or UI tree from another app is returned. The feedback confirms
whether reset completed. Prior exploration progress is discarded; saved image
references remain immutable. Observe the restored state before continuing.
There is one reset attempt per interruption and at most three automatic resets
per authoring session, within the existing wall-clock and request budgets.
The failed action is never repeated automatically. Failed resets, exhausted
recovery allowance, unknown errors and broken evidence remain failures.
Generated oracle/test execution never uses this recovery: every failed
execution operation still prevents credit. No new trial or denominator is created.

