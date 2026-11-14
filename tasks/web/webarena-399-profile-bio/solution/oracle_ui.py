def check(page):
    page.get_by_role("heading", name="MarvelsGrantMan136").to_be_visible(precondition=True)
    page.get_by_text("I am a robot").to_be_visible()
