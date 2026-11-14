def check(page):
    # Shared Markor editor chrome (independent of note content)
    page.get_by_role("button", name="Search").to_be_visible(precondition=True)
    page.get_by_role("button", name="More options").to_be_visible(precondition=True)
    # Behavior: note title and exact persisted content after reopen
    page.get_by_role("paragraph", name="atlas").to_have_text("atlas")
    page.get_by_role(
        "textbox",
        name="net.gsantner.markor:id/document__fragment__edit__highlighting_editor",
    ).to_have_text("Bring the blue notebook.")
