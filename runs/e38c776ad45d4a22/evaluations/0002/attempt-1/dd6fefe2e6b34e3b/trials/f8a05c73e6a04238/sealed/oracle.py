def check(page):
    # Positive setup landmark: Markor editor title bar with note name "atlas"
    # (shared chrome, independent of note content/save state).
    page.expect_image(
        "atlas-final",
        region=[0, 128, 360, 212],
        threshold=0.1,
        max_diff_pixels=20,
        precondition=True,
    )
    # Behavior: after reopen, the note body shows exactly the saved text.
    # The blinking caret just after the final period is masked.
    page.expect_image(
        "atlas-final",
        region=[0, 214, 720, 700],
        masks=[[258, 230, 266, 274]],
        threshold=0.1,
        max_diff_pixels=15,
        observation_window_ms=1600,
    )
