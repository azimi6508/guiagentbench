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
