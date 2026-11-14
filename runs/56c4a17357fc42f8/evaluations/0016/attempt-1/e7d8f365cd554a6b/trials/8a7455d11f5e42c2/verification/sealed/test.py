def test(page):
    page.goto("http://app:8000/")
    # Shared application landmark, independent of caption preferences.
    page.expect_image(
        "aura-home", region=[54, 18, 219, 64],
        threshold=0.1, max_diff_pixels=20, precondition=True,
    )

    page.click(1159, 40)  # Settings
    page.click(139, 324)  # Accessibility
    page.expect_image(
        "caption-default", region=[280, 181, 700, 275],
        threshold=0.1, max_diff_pixels=40,
    )

    page.click(599, 439)  # Caption size
    page.click(554, 444)  # Large
    page.expect_image(
        "caption-large", region=[278, 405, 920, 473],
        threshold=0.1, max_diff_pixels=60,
    )
    # Check the actual subtitle rendering, separately from its setting label.
    page.expect_image(
        "caption-large", region=[973, 217, 1213, 329],
        threshold=0.1, max_diff_pixels=80,
    )
