def check(page):
    page.get_by_role("button", name="More options").to_be_visible(precondition=True)
    page.get_by_role("paragraph", name="atlas").to_have_text("atlas")
    editor = page.get_by_role(
        "textbox",
        name="net.gsantner.markor:id/document__fragment__edit__highlighting_editor",
    )
    editor.to_be_visible()
    editor.to_have_text("Bring the blue notebook.")
