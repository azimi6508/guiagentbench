def check(page):
    page.expect_image(
        "reopened-profile",
        region=[104, 0, 343, 52],
        threshold=0.1,
        max_diff_pixels=0,
        precondition=True,
    )
    page.expect_image(
        "reopened-profile",
        region=[916, 78, 1184, 230],
        masks=[[920, 106, 1178, 148]],
        threshold=0.1,
        max_diff_pixels=0,
    )
