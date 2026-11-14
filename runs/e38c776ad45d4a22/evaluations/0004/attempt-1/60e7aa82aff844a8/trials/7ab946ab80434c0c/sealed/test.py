def test(page):
    # Precondition: Markor editor chrome with the "atlas" note title is shown.
    page.expect_image("initial-editor", region=[0, 128, 330, 212],
                      threshold=0.1, max_diff_pixels=20, precondition=True)

    # Focus the editor body and type the note text.
    page.click(360, 600)
    page.type_text("Bring the blue notebook.")

    # Save explicitly via the toolbar save icon.
    page.click(569, 170)

    # Close and reopen the application.
    page.reload()

    # Behavioral check: the saved text is visible after reopening.
    page.expect_image("saved-reopened", region=[0, 215, 720, 330],
                      threshold=0.1, max_diff_pixels=10,
                      observation_window_ms=2000)
