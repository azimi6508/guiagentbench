def test(page):
    # Shared editor controls establish the initial app screen.
    page.expect_image(
        "initial-editor",
        region=[0, 1176, 720, 1243],
        threshold=0.1,
        max_diff_pixels=20,
        precondition=True,
    )
    page.click(150, 280)
    page.type_text("Bring the blue notebook.")
    page.expect_image(
        "entered-note",
        region=[8, 220, 710, 1170],
        threshold=0.1,
        max_diff_pixels=20,
    )
    page.click(569, 169)
    # Native reload closes and reopens the task application.
    page.reload()
    page.expect_image(
        "reopened-note",
        region=[12, 140, 150, 198],
        threshold=0.1,
        max_diff_pixels=10,
    )
    page.expect_image(
        "reopened-note",
        region=[8, 220, 710, 1170],
        threshold=0.1,
        max_diff_pixels=20,
    )
