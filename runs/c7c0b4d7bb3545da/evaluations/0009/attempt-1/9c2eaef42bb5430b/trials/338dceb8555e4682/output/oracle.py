def check(page):
    page.get_by_role("link", name="Edit biography").to_be_visible(precondition=True)
    page.get_by_text("I am a robot").to_have_text("I am a robot")
    page.expect_image("final", region=[910, 150, 1190, 195])
