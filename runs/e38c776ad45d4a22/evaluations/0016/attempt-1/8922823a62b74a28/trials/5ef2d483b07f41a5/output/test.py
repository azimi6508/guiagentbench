def test(page):
    # Open Settings from the header gear icon
    page.click(1158, 40)
    # Go to the Accessibility category
    page.click(133, 325)

    # Precondition: settings chrome (title + category sidebar) is visible.
    page.expect_image(
        "acc-page-medium",
        region=[40, 95, 250, 650],
        threshold=0.1,
        max_diff_pixels=40,
        precondition=True,
    )

    # Open the Caption size picker and choose Large
    page.click(598, 439)
    page.click(640, 446)

    # Behavior: the built-in caption preview shows the Large reading size.
    page.expect_image(
        "caption-large-preview",
        region=[963, 155, 1222, 382],
        threshold=0.1,
        max_diff_pixels=60,
    )
