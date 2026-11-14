def check(page):
    page.get_by_role("heading", name="Accessibility").to_be_visible(precondition=True)
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    page.expect_image("final", region=[963, 200, 1221, 342])
