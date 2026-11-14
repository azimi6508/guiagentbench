def check(page):
    # Shared branding is independent of the caption preference.
    page.expect_image(
        "caption-large-final", region=[54, 18, 220, 64],
        threshold=0.1, max_diff_pixels=20, precondition=True,
    )
    # Verify both the selected size and the enlarged rendered sample.
    page.expect_image(
        "caption-large-final", region=[812, 421, 891, 459],
        threshold=0.1, max_diff_pixels=15,
    )
    page.expect_image(
        "caption-large-final", region=[976, 220, 1210, 324],
        threshold=0.1, max_diff_pixels=50,
    )
