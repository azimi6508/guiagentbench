def check(page):
    page.get_by_role("navigation", name="Main navigation").to_be_visible(precondition=True)
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    page.expect_image(
        "large-caption-preview",
        region=[974, 220, 1212, 325],
        threshold=0.1,
        max_diff_pixels=100,
        include_aa=False,
    )
