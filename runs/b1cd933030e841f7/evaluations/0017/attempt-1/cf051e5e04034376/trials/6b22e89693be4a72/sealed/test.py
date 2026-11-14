def test(page):
    page.goto("http://app:8000/")
    page.get_by_role("navigation", name="Main navigation").to_be_visible(precondition=True)
    page.get_by_role("button", name="Settings").click()
    page.get_by_role("button", name="Accessibility").click()
    page.get_by_role("heading", name="Accessibility").to_be_visible()
    page.get_by_role("button", name="Caption size Medium").to_be_visible()
    page.get_by_role("button", name="Caption size Medium").click()
    page.get_by_role("dialog", name="Caption size").to_be_visible()
    page.get_by_role("button", name="Large").click()
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    # Check the actual enlarged subtitle, independently of the setting label.
    page.expect_image(
        "large-caption-preview",
        region=[970, 210, 1215, 335],
        threshold=0.1,
        max_diff_pixels=80,
        include_aa=False,
    )
