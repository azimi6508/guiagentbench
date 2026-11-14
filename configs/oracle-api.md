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
