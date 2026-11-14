def test(page):
    # Shared site chrome is independent of the biography being tested.
    page.expect_image(
        "initial-profile",
        region=[108, 8, 337, 44],
        precondition=True,
    )
    page.expect_image(
        "initial-profile",
        region=[919, 78, 1112, 145],
    )

    page.click(991, 211)
    page.expect_image(
        "biography-editor",
        region=[101, 81, 692, 154],
    )

    # The initial single-line biography contains eleven characters.
    # ArrowDown moves to its end before clearing it.
    page.click(271, 180)
    page.press("ArrowDown")
    for _ in range(11):
        page.press("Backspace")
    page.type_text("I am a robot")
    page.click(134, 431)

    # Open the actual profile through the editor's profile link.
    page.click(513, 100)
    page.expect_image(
        "reopened-profile",
        region=[103, 80, 372, 116],
    )
    page.expect_image(
        "reopened-profile",
        region=[910, 66, 1191, 240],
        threshold=0.1,
        max_diff_pixels=0,
    )

    # A new document load must retain the same saved biography.
    page.reload()
    page.expect_image(
        "reopened-profile",
        region=[910, 66, 1191, 240],
        threshold=0.1,
        max_diff_pixels=0,
    )
