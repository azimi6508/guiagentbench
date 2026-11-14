def check(page):
    page.expect_image("saved", region=[920, 80, 1110, 106], precondition=True)
    page.expect_image("saved", region=[920, 157, 1130, 190], masks=[])
