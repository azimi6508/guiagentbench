def test(page):
    # Precondition: shared forum chrome (top navigation bar) is visible.
    page.expect_image("initial-profile", region=[0, 0, 1280, 52],
                      threshold=0.1, max_diff_pixels=50, precondition=True)

    # Open the biography editor from the profile sidebar.
    page.click(986, 211)
    # Precondition: biography editor heading is shown.
    page.expect_image("editor-original", region=[100, 80, 700, 125],
                      threshold=0.1, max_diff_pixels=50, precondition=True)

    # Focus the textarea (caret at end), clear existing text and type new bio.
    page.click(500, 250)
    for _ in range(15):
        page.press("Backspace")
    page.type_text("I am a robot")

    # Move focus to Save via keyboard (layout shifts when preview appears).
    page.press("Tab")
    page.press("Tab")
    page.expect_image("editor-typed-robot", region=[106, 160, 500, 195],
                      threshold=0.1, max_diff_pixels=20)
    page.press("Enter")

    # After save, the sidebar on the returned edit page shows the new bio.
    page.expect_image("editor-after-save", region=[915, 150, 1185, 192],
                      threshold=0.1, max_diff_pixels=20,
                      observation_window_ms=2000)

    # Reopen the profile and verify the persisted biography.
    page.goto("http://app:8000/")
    page.expect_image("initial-profile", region=[0, 0, 1280, 52],
                      threshold=0.1, max_diff_pixels=50, precondition=True)
    page.expect_image("reopened-robot-bio", region=[910, 67, 1191, 195],
                      threshold=0.1, max_diff_pixels=20)
