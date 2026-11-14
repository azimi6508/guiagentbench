def check(page):
    page.get_by_role("link", name="Home").to_be_visible(precondition=True)
    page.get_by_role("heading", name="MarvelsGrantMan136").to_be_visible()
    page.get_by_role("link", name="Edit biography").to_be_visible()
    page.get_by_text("I am a robot").to_be_visible()
    page.get_by_text("I am a robot").to_have_text("I am a robot")
