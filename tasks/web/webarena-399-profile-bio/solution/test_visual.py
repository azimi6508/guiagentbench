def test(page):
    import time
    page.expect_image("screen", region=[920, 80, 1110, 106], precondition=True)
    page.click(986, 212)  # Edit biography
    time.sleep(2)
    page.click(500, 175)  # end of the biography text
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.press('Backspace')
    page.type_text('I am a robot')
    time.sleep(2)
    page.click(134, 432)  # Save
    time.sleep(2)
    page.click(150, 25)  # forum home, which is the profile
    time.sleep(2)
    page.reload()
    time.sleep(2)
    page.expect_image("saved", region=[920, 80, 1110, 106], precondition=True)
    page.expect_image("saved", region=[920, 157, 1130, 190], masks=[])
