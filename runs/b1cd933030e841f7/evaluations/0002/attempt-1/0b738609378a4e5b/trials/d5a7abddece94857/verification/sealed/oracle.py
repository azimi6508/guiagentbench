def check(page):
    # Stable editor controls, independent of the note's contents.
    page.expect_image(
        "reopened-note", region=[610, 140, 710, 200],
        threshold=0.1, max_diff_pixels=0, precondition=True,
    )
    # The note identity and entire visible document after reopening.
    page.expect_image(
        "reopened-note", region=[16, 145, 180, 195],
        threshold=0.1, max_diff_pixels=0,
    )
    page.expect_image(
        "reopened-note", region=[0, 220, 720, 1170],
        masks=[[259, 234, 263, 269]],
        threshold=0.1, max_diff_pixels=0,
    )
