def check(page):
    page.expect_image("saved", region=[56, 21, 214, 59], precondition=True, threshold=0.03)
    page.expect_image("saved", region=[953, 150, 1227, 662], threshold=0.03)
