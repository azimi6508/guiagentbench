def test(page):
    # Shared editor controls, independent of the note's contents.
    page.expect_image(
        "initial-editor", region=[480, 140, 710, 200],
        threshold=0.1, max_diff_pixels=0, precondition=True,
    )
    # Confirm the intended note is open.
    page.expect_image(
        "initial-editor", region=[10, 140, 180, 200],
        threshold=0.1, max_diff_pixels=0,
    )
    page.click(150, 252)
    page.type_text("Bring the blue notebook.")
    page.expect_image(
        "typed-note", region=[10, 220, 710, 1170],
        masks=[[259, 234, 264, 270]],
        threshold=0.1, max_diff_pixels=0,
    )
    page.click(570, 170)
    # Native reload closes and reopens the application.
    page.reload()
    page.expect_image(
        "reopened-note", region=[10, 140, 180, 200],
        threshold=0.1, max_diff_pixels=0,
    )
    page.expect_image(
        "reopened-note", region=[10, 220, 710, 1170],
        masks=[[259, 234, 264, 270]],
        threshold=0.1, max_diff_pixels=0,
    )
