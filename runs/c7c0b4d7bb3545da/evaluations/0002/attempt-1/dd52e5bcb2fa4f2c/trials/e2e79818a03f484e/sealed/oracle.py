def check(page):
    page.expect_image("final", region=[0, 1175, 720, 1244], precondition=True)
    page.expect_image("final", region=[0, 220, 720, 300])
