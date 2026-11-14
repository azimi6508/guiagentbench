def test(page):
    page.goto("http://app:8000/")
    # Shared AURA branding is independent of caption preferences.
    page.expect_image("home-chrome", region=[50, 16, 220, 65],
                      threshold=0.1, max_diff_pixels=20, precondition=True)
    page.click(1159, 40)
    page.click(142, 326)
    page.click(640, 440)
    # Confirm the Caption size chooser before selecting Large.
    page.expect_image("caption-size-options", region=[390, 185, 880, 280],
                      threshold=0.1, max_diff_pixels=30)
    page.click(550, 446)
    # Verify both the applied value and the actual enlarged subtitle glyphs.
    page.expect_image("large-caption-preview", region=[280, 408, 917, 471],
                      threshold=0.1, max_diff_pixels=40)
    page.expect_image("large-caption-preview", region=[970, 215, 1215, 330],
                      threshold=0.1, max_diff_pixels=40)
