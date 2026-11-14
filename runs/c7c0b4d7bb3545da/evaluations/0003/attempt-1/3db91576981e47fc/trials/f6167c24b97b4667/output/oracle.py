def check(page):
    page.get_by_role("button", name="More options").to_be_visible(precondition=True)
    page.get_by_role("textbox", name="net.gsantner.markor:id/document__fragment__edit__highlighting_editor").to_have_value("Bring the blue notebook.")
    page.get_by_text("Bring the blue notebook.").to_be_visible()
