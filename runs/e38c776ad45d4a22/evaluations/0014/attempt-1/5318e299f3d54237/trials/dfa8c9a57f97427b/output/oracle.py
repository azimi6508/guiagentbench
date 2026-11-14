def check(page):
    # Precondition: shared app chrome (top navigation bar + Settings header).
    page.expect_image(
        "final-large",
        region=[40, 10, 800, 140],
        threshold=0.1,
        max_diff_pixels=60,
        precondition=True,
    )
    # Behavior: caption preview text rendered at Large reading size.
    page.expect_image(
        "final-large",
        region=[966, 200, 1218, 335],
        threshold=0.1,
        max_diff_pixels=40,
    )
