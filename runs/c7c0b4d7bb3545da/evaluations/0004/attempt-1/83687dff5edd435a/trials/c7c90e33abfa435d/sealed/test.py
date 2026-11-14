def test(page):
    page.goto("http://app:8000/")
    page.expect_image("start", region=[0, 128, 360, 212], precondition=True)
    page.click(360, 500)
    page.type_text("Bring the blue notebook.")
    page.click(569, 170)
    page.reload()
    page.expect_image("start", region=[0, 128, 360, 212], precondition=True)
    page.expect_image("reopened", region=[0, 128, 720, 400])
