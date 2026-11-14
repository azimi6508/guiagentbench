def test(page):
    # Shared chrome precondition
    page.get_by_role("button", name="Switch profile, Alex").to_be_visible(precondition=True)
    page.get_by_role("button", name="Search library").to_be_visible(precondition=True)

    # Open Settings via the header gear icon
    page.click(1158, 40)
    page.get_by_role("button", name="Accessibility").click()
    page.get_by_role("heading", name="Accessibility").to_be_visible(precondition=True)
    page.get_by_role("button", name="Caption size Medium").to_be_visible(precondition=True)

    # Choose Large caption size
    page.get_by_role("button", name="Caption size Medium").click()
    page.get_by_role("dialog", name="Caption size").to_be_visible(precondition=True)
    page.get_by_role("button", name="Large").click()

    # Behavioral checks
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    # Caption preview text rendered at the Large reading size
    page.expect_image(
        "large_preview",
        region=[970, 200, 1215, 340],
        threshold=0.1,
        max_diff_pixels=150,
    )
