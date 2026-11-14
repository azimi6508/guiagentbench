Evaluation arm: test_visual. Produce a complete Python test with def test(page).
Required artifact: /workspace/output/test.py. Save it before finishing.
Read the complete contract below. A final chat message does not submit an artifact.

# A saved biography appears on the reopened profile

Change the forum biography of the signed-in user to exactly `I am a robot` and
save it. When the profile is opened again after saving, its biography must be
exactly `I am a robot`.

The local Postmill forum opens on the profile of `MarvelsGrantMan136`, who is
already signed in. The profile page and its biography editor are available;
other forum pages are outside this task.


Write a complete Python GUI test from this goal. There is no supplied recording,
journey, step list or reference test. The live app starts at its initial home
page. Choose how to explore it using the available tools, and save
`/workspace/output/test.py` with synchronous `def test(page):`.

The same sealed file and any named image references run against two fresh app states. It must perform the
journey itself, check that the intended screen/setup was reached, and assert
the requested behavior. Authoring and execution are separate: there is no
authoring-time Python execution tool or grading feedback.

Execution ABI visual-v1 uses a scoped Python client. Actions and UI assertions are
performed by Playwright in the browser broker. Ordinary Python runs in a separate
container. This is not an unrestricted Playwright Page; no JavaScript evaluation,
arbitrary selectors, browser debugging, backend requests or filesystem fixtures
are available through the browser API.

Both arms:
- `page.screenshot()` returns viewport PNG bytes.
- `page.goto("http://app:8000/")`, `page.reload()`, `page.reset()` navigate to the
  allowlisted home, reload, or restore a fresh initial app respectively.
- `page.expect_image(...)` compares screenshot pixels with a named reference
  captured during your authoring exploration; see the visual assertion contract
  below. You choose the checkpoints, reference images, regions and tolerances.

Both test_visual and test_ui support these coordinate and keyboard actions
(action contract ui-superset-v1):
- `page.click(x, y)`, `page.hover(x, y)`, `page.scroll(dx, dy)`.
- `page.type_text(text)` inserts text into the focused control.
- `page.press(key)` accepts Enter, Tab, Escape, the four Arrow keys, or Backspace.
  test_visual must obtain coordinates from screenshots and has no UI tree,
  locator or hidden text query. test_ui may choose either evidence source.

test_ui additionally supports:
- `page.dump_ui()` returns the current accessibility tree.
- `page.get_by_role(role, name="exact accessible name")` locators provide
  `.click()`, `.hover()`, `.fill(text)` and `.press(key)`.
- Role/name locators and `page.get_by_text("exact text")` support assertions
  `.to_be_visible()`, `.to_be_hidden()`, `.to_have_text(text)`,
  `.to_have_value(value)` and `.to_have_count(count)`. Text locators are for
  assertions only. Each assertion accepts `precondition=True`.

During authoring, gui_step uses the same action forms: click/hover with x,y;
scroll with dx,dy; type with text; press with key; reload with no other fields.
UI arms may alternatively use role,name with click/hover/press, or
role,name,text with fill. Never mix coordinates with role/name in one action.
All capabilities are optional; choose those useful for the task.

Coordinate clicks and hovers use integer pixels in the original screenshot:
origin (0, 0) is top-left, x increases right, and y increases down. gui_observe
reports the width and height. Use 0 <= x < width and 0 <= y < height; values
are not percentages or normalized 0-1000 coordinates. The same pixel units
apply to page.click(x, y) and page.hover(x, y) during test execution.

Include a positive precondition for shared app chrome or another landmark
independent of the requested behavior before behavioral assertions. A requested
navigation destination, saved content or setting belongs in behavioral checks.
An authored precondition failure invalidates the submission; it does not prove
an environment fault and never counts as bug detection. Include at
least one user action. Perform the same actions and assertion definitions in
the same order on both states; observation calls need not be identical.
Assertions return None; their results are recorded in the trusted browser ledger.
Catching exceptions, changing Python objects, printing verdicts or returning
early cannot erase broker failures. Crashes, timeouts, denied requests, missing
assertions or setup errors earn zero. The sealed test runs five times on each
state. Only five valid correct-state passes and five faulty-state behavioral
mismatches, all with the same actions and assertion definitions, earn 1 for
the pair; a flaky run earns zero.

Budgets: source at most 64 KiB, 360 seconds per execution, 80 broker
requests, 1 MiB execution output. No external dependencies are installed for
submitted Python. Keep the test deterministic and use positive screen checks.


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


Screenshot dimensions: width=1280 pixels, height=720 pixels. Coordinates are integer pixels in the original screenshot, with top-left origin (0, 0). x increases right and y increases down. Use the screenshot width and height; coordinates are not percentages or a normalized 0-1000 scale. Valid pixel positions: 0 <= x < 1280, 0 <= y < 720. click/hover x,y use these pixels directly, without automatic scaling. If you reason on a 0-1000 scale, convert to pixels before calling: x_pixel = floor(x_normalized * width / 1000), y_pixel = floor(y_normalized * height / 1000).

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
