Evaluation arm: oracle_visual. Produce a Python oracle with def check(page).
Required artifact: /workspace/output/oracle.py. Save it before finishing.
Read the complete contract below. A final chat message does not submit an artifact.

The native Markor editor has an empty note named `atlas.txt` open. Put exactly
`Bring the blue notebook.` in the note. Its text must still be visible and saved
after closing and reopening the application.


Save `/workspace/output/oracle.py` with a synchronous `def check(page):` function.
The same sealed Python file and named image references run on two fresh app states. This is oracle
generation: the controller already performs the supplied steps and presents the
third/final checkpoint. Write assertions for that state, not a new journey.

You may explore the prepared live state using the available GUI tools. `gui_reset`
restores the final checkpoint; `gui_open_url` opens the home page. Select evidence
and actions yourself. There is no authoring-time code execution tool. Execution
uses a separate container and a read-only browser API. No private test source,
labels, app code, or result files are available.

Authoring action contract ui-superset-v1: both oracle arms can use gui_step
with click/hover (x,y), scroll (dx,dy), type (text), press (key), or reload
(no other fields). oracle_ui additionally permits exact role,name targeting
for click/hover/press, and role,name,text for fill, plus gui_dump_ui.
Never mix coordinates with role/name in one action. Capabilities are optional.
These are authoring tools only: neither oracle may act during execution.

Authoring click/hover coordinates are integer pixels in the original screenshot:
origin (0, 0) is top-left, x increases right, and y increases down. gui_observe
reports the width and height. Use 0 <= x < width and 0 <= y < height; values
are not percentages or normalized 0-1000 coordinates.

Execution ABI visual-v1:
- `page.screenshot()` returns PNG bytes from the viewport.
- `page.expect_image(...)` compares screenshot pixels with a named reference
  captured during your authoring exploration. You choose the references,
  regions, masks and tolerances; see the visual assertion contract below.
- `precondition=True` marks an authored setup/health assertion; its failure
  never counts as bug detection or proves an environment fault. Choose shared
  app chrome or another positive landmark independent of the requested outcome.
  Navigation destination, saved content and requested settings are behavior;
  asserting them as setup can invalidate detection of that behavior's failure.
- Assertions return None. The browser records every result independently;
  catching exceptions or returning early cannot erase failed checks.
- Only oracle_ui also has `page.dump_ui()`,
  `page.get_by_role(role, name="exact accessible name")`, and
  `page.get_by_text("exact visible text")`. These locators support
  `.to_be_visible()`, `.to_be_hidden()`, `.to_have_text("text")`,
  `.to_have_value("value")`, `.to_have_count(integer)`, each accepting the
  optional `precondition=True` keyword. They use Playwright assertions in the
  trusted browser. No arbitrary selectors, attributes, JavaScript, CDP or HTTP.

Visual oracles cannot use any UI query, UI assertion or UI dump, even through a
direct network call. Execution cannot change the page, reset it or navigate.
The page is a scoped remote facade, not an unrestricted Playwright Page object.
You can use ordinary Python in the sandbox, but process and file access are
confined there. Only broker-recorded assertions determine the result. At least
one positive precondition followed by a behavioral assertion are required on each state,
with the same ordered assertion definitions on both. Exceptions, denied requests,
timeouts, missing assertions and malformed artifacts earn zero.

The sealed oracle runs five times on each state. It earns credit only if all
five correct-state runs pass, all five faulty-state runs fail behaviorally and
every run makes the same assertion definitions; a flaky run earns zero.

Budgets: oracle.py at most 64 KiB, 60 seconds per execution, 80 broker
requests, 1 MiB execution output. Submit only the Python source at the path above.


Visual assertion contract `visual-v1` (web and native Android)

You choose what to check, when to check it, and which screenshots demonstrate
the expected appearance. No reference images or assertion regions are supplied
in advance. During authoring, call `gui_observe` with an optional `reference`
argument, for example `{"reference":"saved-note"}`. It returns the current
screenshot and saves those exact pixels under that name. Inspect it before
choosing it as a reference. You can capture several states during exploration.
An ordinary `gui_observe` without a reference only observes; it saves no baseline.

Each gui_observe includes the screenshot width and height, pixel units, top-left
origin (0, 0), and axes (x right, y down). Image regions and masks use these same
original-screenshot pixels. Coordinate actions also use these pixels wherever
the platform permits pointer interaction. Images are not resized by this contract.

Reference names use lowercase letters, numbers, hyphens and underscores, start
with a letter, and have at most 48 characters. Names are immutable: use a new
name for another capture. The framework preserves the named images; do not
encode images in Python, write image files, or supply paths/URLs to the API.

The executable assertion is:
`page.expect_image(reference, region=None, masks=None, threshold=0.1,
                   max_diff_pixels=0, include_aa=False, precondition=False,
                   observation_window_ms=1600)`

- `reference` is a name you captured with `gui_observe` during authoring.
- `region` is `[left, top, right, bottom]` in screenshot pixels, with right and
  bottom exclusive. None compares the whole viewport. Choose a region that
  covers the behavior you intend to verify.
- `masks` is a list of rectangles in the same viewport coordinates, entirely
  inside the comparison region. Mask only irrelevant dynamic content. Masked
  pixels are excluded; the assertion must retain some checked pixels.
- `threshold` is a per-pixel perceptual color tolerance in `[0, 1)`, not the
  fraction of the screen allowed to differ. Smaller values are more sensitive.
- `max_diff_pixels` is the maximum mismatching unmasked pixel count allowed.
  It must be smaller than the number of unmasked pixels. Select tolerances for
  harmless rendering variation without obscuring meaningful differences.
- `include_aa=False` ignores detected anti-aliasing differences; True counts them.
- `observation_window_ms` is an integer in 0..2000, default 1600. The broker
  takes five screenshot observations over that bounded window, at fractions
  0, .23, .51, .77 and 1, and compares every frame with the same sealed reference
  and your exact region, masks and tolerance. The assertion matches if any
  observed frame matches. A zero window takes one frame. Legacy direct wire
  requests without this field retain single-frame behavior. This is the
  `visual-observation-window-v1` measurement contract, not an action or trial
  retry. No action is repeated, reference learned, mask added or tolerance
  increased. Every observed PNG, timing, difference count and selected frame
  is retained. Observation errors remain fatal. Wall-clock/evidence budgets
  remain unchanged; use windows selectively for long tests. Do not use an
  earlier transient match to claim persistence: perform the relevant reopen
  or navigation before asserting the durable visible outcome.
- `precondition=True` identifies a positive screen/setup check. A mismatch there
  invalidates the submitted checks, not proof that the environment is broken.
  Use shared chrome independent of the goal, and reserve the destination,
  selected setting and saved content for behavioral assertions.

Example: after capturing an appropriate `saved-note` screenshot in authoring,
`page.expect_image("saved-note", region=[40, 200, 650, 400])` compares that region.
Choose coordinates from your own screenshots; these example coordinates are
not a task-specific solution. UI-capable arms may freely combine image and UI
assertions. Visual arms have only screenshot-based assertions.

Comparison uses pinned Pixelmatch Python and Pillow on screenshot pixels only.
It does not recognize text or interpret semantic correctness. Reference images
must themselves demonstrate the intended appearance. A visual match alone
cannot prove invisible backend state; establish relevant visible checkpoints
through the journey allowed by your arm.

Mobile screenshots can contain a blinking editor caret, selection handles,
fading scrollbars, focus indicators and system-bar time. These are visible
rendering details, not task outcome labels. The observation window accommodates
short-lived variation; it does not guarantee that arbitrary broad crops are
stable. Choose relevant regions and mask irrelevant dynamic areas using your
own permitted screenshots. A zero-tolerance comparison including changing
decoration can fail even when text/settings are correct. UI-capable arms may
use semantic checks when useful; no capability is mandatory.

References are frozen with the program before paired grading. The execution
API cannot create/update references, access another variant or return assertion
results. No reference is auto-created when missing. The broker records every
result and saves expected, actual, difference and original capture images for
review. Missing references, malformed images and invalid parameters invalidate
execution, even if the submitted program catches the exception.

At most 64 references, 4 MB per PNG and 32 MB total are retained. Exceeding these
limits fails explicitly; images are never silently pruned. Both paired runs use
the same reference bytes, names, regions, masks and comparison settings.


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

