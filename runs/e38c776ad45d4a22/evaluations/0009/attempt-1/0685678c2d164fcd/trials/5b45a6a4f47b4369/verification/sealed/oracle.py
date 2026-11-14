def check(page):
    # Preconditions: shared profile chrome, independent of biography content.
    page.get_by_role("link", name="Edit biography").to_be_visible(precondition=True)
    page.get_by_role("heading", name="MarvelsGrantMan136").to_be_visible(precondition=True)

    # Behavior: the reopened profile shows exactly the saved biography.
    page.get_by_text("I am a robot").to_be_visible()
    page.get_by_text("I am a robot").to_have_count(1)
    page.expect_image(
        "final_profile",
        region=[912, 150, 1188, 230],
        threshold=0.1,
        max_diff_pixels=20,
    )
