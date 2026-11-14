def test(page):
    page.get_by_text("atlas").to_be_visible(precondition=True)
    page.get_by_role("textbox", name="net.gsantner.markor:id/document__fragment__edit__highlighting_editor").fill("Bring the blue notebook.")
    page.get_by_text("Bring the blue notebook.").to_be_visible(precondition=True)
    page.reload()
    page.get_by_text("atlas").to_be_visible(precondition=True)
    page.get_by_text("Bring the blue notebook.").to_be_visible()
