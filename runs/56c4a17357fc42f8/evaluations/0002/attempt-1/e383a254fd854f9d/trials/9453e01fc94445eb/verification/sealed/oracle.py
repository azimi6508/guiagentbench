def check(page):
    page.expect_image(
        "final-note",
        region=[605, 140, 710, 200],
        threshold=0.1,
        max_diff_pixels=0,
        precondition=True,
    )
    page.expect_image(
        "final-note",
        region=[16, 145, 150, 195],
        threshold=0.1,
        max_diff_pixels=0,
    )
    page.expect_image(
        "final-note",
        region=[0, 220, 720, 1174],
        threshold=0.1,
        max_diff_pixels=0,
    )
