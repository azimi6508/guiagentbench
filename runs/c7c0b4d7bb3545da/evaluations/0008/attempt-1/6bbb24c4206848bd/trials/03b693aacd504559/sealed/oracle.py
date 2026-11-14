def check(page):
    page.expect_image("final", region=[100, 0, 700, 52], precondition=True)
    page.expect_image("final", region=[910, 80, 1190, 230])
