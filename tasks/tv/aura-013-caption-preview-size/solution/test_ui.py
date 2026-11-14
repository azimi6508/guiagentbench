def test(page):
    import time
    time.sleep(0.7)
    page.expect_image("screen", region=[56, 21, 214, 59], precondition=True, threshold=0.03)
    page.click(1159, 40)
    time.sleep(0.1)
    page.click(147, 326)
    time.sleep(0.1)
    page.click(599, 440)
    time.sleep(0.1)
    page.click(640, 446)
    time.sleep(0.1)
    page.expect_image("saved", region=[56, 21, 214, 59], precondition=True, threshold=0.03)
    page.expect_image("saved", region=[953, 150, 1227, 662], threshold=0.03)
