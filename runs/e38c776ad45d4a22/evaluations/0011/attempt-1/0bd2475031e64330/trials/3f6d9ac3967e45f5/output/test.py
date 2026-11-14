def test(page):
    page.goto("http://app:8000/")
    # Preconditions: shared chrome / profile sidebar landmarks
    page.get_by_role("link", name="Home").to_be_visible(precondition=True)
    page.get_by_role("heading", name="Toolbox").to_be_visible(precondition=True)
    page.get_by_role("link", name="Edit biography").to_be_visible(precondition=True)

    # Open the biography editor and save the new biography
    page.get_by_role("link", name="Edit biography").click()
    page.get_by_role("textbox", name="Biography").to_be_visible(precondition=True)
    page.get_by_role("textbox", name="Biography").fill("I am a robot")
    page.get_by_role("button", name="Save").click()

    # Reopen the profile
    page.goto("http://app:8000/")
    page.get_by_role("heading", name="Toolbox").to_be_visible(precondition=True)
    page.get_by_text("I am a robot").to_be_visible()
    page.get_by_text("I am a robot").to_have_count(1)
    page.get_by_text("t2_5adwlxvn").to_be_hidden()

    # Reopen the editor and confirm the stored value is exact
    page.get_by_role("link", name="Edit biography").click()
    page.get_by_role("textbox", name="Biography").to_have_value("I am a robot")
