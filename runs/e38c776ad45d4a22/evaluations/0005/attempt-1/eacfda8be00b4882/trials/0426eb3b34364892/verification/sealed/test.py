EDITOR = "net.gsantner.markor:id/document__fragment__edit__highlighting_editor"
TEXT = "Bring the blue notebook."


def test(page):
    # Preconditions: Markor editor for atlas note is open and empty.
    page.get_by_role("paragraph", name="atlas").to_be_visible(precondition=True)
    page.get_by_role("button", name="More options").to_be_visible(precondition=True)
    editor = page.get_by_role("textbox", name=EDITOR)
    editor.to_be_visible(precondition=True)
    editor.to_have_text("", precondition=True)

    # Enter the text and save.
    editor.fill(TEXT)
    editor.to_have_text(TEXT)
    page.get_by_role("button", name="Save").click()

    # Close and reopen the application.
    page.reload()

    # Shared chrome after reopen.
    page.get_by_role("paragraph", name="atlas").to_be_visible(precondition=True)

    # Behavioral: saved text persisted and visible.
    reopened = page.get_by_role("textbox", name=EDITOR)
    reopened.to_be_visible()
    reopened.to_have_text(TEXT)
