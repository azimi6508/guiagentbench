def test(page):
    page.click(1159, 40)
    page.click(132, 325)
    page.expect_image("access-before", region=[56, 150, 240, 650], precondition=True)
    page.click(600, 439)
    page.click(600, 446)
    page.expect_image("large-set", region=[962, 154, 1222, 382])
    page.expect_image("large-set", region=[262, 400, 935, 480])
