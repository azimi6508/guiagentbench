def check(page):
    # Shared app chrome landmark (precondition)
    page.get_by_role("button", name="Home").to_be_visible(precondition=True)
    page.get_by_role("complementary", name="Settings categories").to_be_visible(precondition=True)
    # Behavioral: Large selected
    page.get_by_role("button", name="Caption size Large").to_be_visible()
    # Behavioral: caption preview rendered at Large reading size
    page.expect_image(
        "large-preview",
        region=[964, 156, 1220, 342],
        threshold=0.1,
        max_diff_pixels=150,
    )
