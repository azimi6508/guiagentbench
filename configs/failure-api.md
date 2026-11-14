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

