def check(page):
    page.get_by_text("atlas").to_be_visible(precondition=True)
    page.get_by_text("Bring the blue notebook.").to_be_visible()
