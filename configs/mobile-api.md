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

