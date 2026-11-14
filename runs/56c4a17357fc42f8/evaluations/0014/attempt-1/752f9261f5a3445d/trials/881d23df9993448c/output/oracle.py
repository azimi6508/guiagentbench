def check(page):
    # Shared branding establishes that the application rendered.
    page.expect_image(
        "large-caption-preview",
        region=[54, 18, 219, 65],
        threshold=0.1,
        max_diff_pixels=20,
        precondition=True,
    )
    # Check the actual enlarged subtitle lettering, including its two-line layout.
    page.expect_image(
        "large-caption-preview",
        region=[976, 222, 1210, 323],
        threshold=0.1,
        max_diff_pixels=60,
    )
    # The caption-size control must also display the requested selection.
    page.expect_image(
        "large-caption-preview",
        region=[839, 426, 892, 452],
        threshold=0.1,
        max_diff_pixels=10,
    )
