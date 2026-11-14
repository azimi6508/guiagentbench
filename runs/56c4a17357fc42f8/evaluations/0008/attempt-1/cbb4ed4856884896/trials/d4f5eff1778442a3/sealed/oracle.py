def check(page):
    # Shared forum chrome is independent of the saved biography.
    page.expect_image(
        "reopened-profile",
        region=[104, 0, 345, 52],
        threshold=0.1,
        max_diff_pixels=0,
        precondition=True,
    )
    # The final checkpoint is the reopened profile. Include the entire
    # biography row and its surrounding whitespace to detect extra text.
    page.expect_image(
        "reopened-profile",
        region=[918, 150, 1180, 192],
        threshold=0.1,
        max_diff_pixels=0,
    )
