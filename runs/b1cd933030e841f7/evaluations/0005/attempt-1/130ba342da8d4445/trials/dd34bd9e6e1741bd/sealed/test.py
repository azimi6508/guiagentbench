def test(page):
    page.goto("http://app:8000/")
    page.get_by_role("button", name="More options").to_be_visible(precondition=True)
    editor = page.get_by_role(
        "textbox",
        name="net.gsantner.markor:id/document__fragment__edit__highlighting_editor",
    )
    editor.to_be_visible(precondition=True)
    page.get_by_role("paragraph", name="atlas").to_have_text("atlas")
    editor.to_have_value("")
    editor.fill("Bring the blue notebook.")
    page.get_by_role("button", name="Save").click()
    editor.to_have_value("Bring the blue notebook.")
    # Native reload closes and reopens the application, preserving saved data.
    page.reload()
    page.get_by_role("paragraph", name="atlas").to_have_text("atlas")
    editor.to_be_visible()
    editor.to_have_value("Bring the blue notebook.")
