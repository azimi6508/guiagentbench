def test(page):
    page.goto("http://app:8000/")
    page.expect_image("home", region=[100, 0, 1200, 52], precondition=True)
    page.click(986, 211)
    page.click(400, 230)
    for _ in range(30):
        page.press("Backspace")
    page.type_text("I am a robot")
    page.click(134, 432)
    page.goto("http://app:8000/")
    page.expect_image("home", region=[100, 0, 1200, 52], precondition=True)
    page.expect_image("reopened", region=[910, 66, 1190, 240])
