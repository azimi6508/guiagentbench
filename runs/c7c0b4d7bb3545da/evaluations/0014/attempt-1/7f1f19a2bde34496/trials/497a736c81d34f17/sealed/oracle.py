def check(page):
    page.expect_image("final", region=[0, 0, 1280, 80], precondition=True)
    page.expect_image("final", region=[962, 154, 1222, 382])
