def check(page):
    page.expect_image("saved", region=[65, 128, 260, 210], precondition=True)
    page.expect_image("saved", region=[0, 220, 720, 700], masks=[[258, 235, 262, 268]])
