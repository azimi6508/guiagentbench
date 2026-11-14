def check(page):
    page.get_by_role("navigation", name="Main navigation").to_be_visible(precondition=True)
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    page.expect_image(
        "large-caption-preview",
        region=[976, 220, 1210, 324],
        threshold=0.1,
        max_diff_pixels=100,
    )
