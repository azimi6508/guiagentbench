def test(page):
    ed = "net.gsantner.markor:id/document__fragment__edit__highlighting_editor"
    page.get_by_role("button", name="Search").to_be_visible(precondition=True)
    page.get_by_role("paragraph", name="atlas").to_have_text("atlas", precondition=True)
    page.get_by_role("textbox", name=ed).click()
    page.type_text("Bring the blue notebook.")
    page.get_by_role("textbox", name=ed).to_have_text("Bring the blue notebook.")
    page.get_by_role("button", name="Save").click()
    page.reload()
    page.get_by_role("button", name="Search").to_be_visible(precondition=True)
    page.get_by_role("textbox", name=ed).to_have_text("Bring the blue notebook.")
