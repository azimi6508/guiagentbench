def test(page):
    editor_name = "net.gsantner.markor:id/document__fragment__edit__highlighting_editor"
    note_text = "Bring the blue notebook."

    # Establish the shared editor chrome before checking the note.
    page.get_by_role("button", name="View mode").to_be_visible(precondition=True)
    page.get_by_role("textbox", name=editor_name).to_be_visible(precondition=True)
    page.get_by_text("atlas").to_be_visible()
    page.get_by_role("textbox", name=editor_name).to_have_text("")

    page.get_by_role("textbox", name=editor_name).fill(note_text)
    page.get_by_role("textbox", name=editor_name).to_have_text(note_text)
    page.get_by_role("button", name="Save").click()

    # Native reload closes and reopens the application, retaining saved files.
    page.reload()
    page.get_by_text("atlas").to_be_visible()
    page.get_by_role("textbox", name=editor_name).to_be_visible()
    page.get_by_role("textbox", name=editor_name).to_have_text(note_text)
