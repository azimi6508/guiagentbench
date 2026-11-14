def test(page):
    page.goto("http://app:8000/")
    # Shared navigation is independent of biography persistence.
    page.expect_image("initial-chrome", region=[110, 8, 335, 43], precondition=True)
    page.click(984, 211)
    page.click(230, 175)
    page.press("ArrowDown")
    # Remove the eleven characters in the initial biography.
    for _ in range(11):
        page.press("Backspace")
    page.type_text("I am a robot")
    page.click(132, 433)
    # Open the profile again from its username link after saving.
    page.click(1019, 93)
    page.expect_image("reopened-biography", region=[104, 80, 371, 116])
    # Check the entire biography area, including surrounding blank space.
    page.expect_image("reopened-biography", region=[918, 153, 1182, 192], threshold=0.1, max_diff_pixels=0)
