def check(page):
    # Shared app chrome (navbar with signed-in user menu) - setup landmark.
    page.expect_image(
        "profile-bio-robot",
        region=[0, 0, 1280, 52],
        threshold=0.1,
        max_diff_pixels=40,
        precondition=True,
    )
    # Behavior: reopened profile sidebar shows biography exactly "I am a robot".
    page.expect_image(
        "profile-bio-robot",
        region=[910, 66, 1191, 240],
        threshold=0.1,
        max_diff_pixels=10,
    )
    # Tight check on the biography text line itself.
    page.expect_image(
        "profile-bio-robot",
        region=[912, 155, 1190, 192],
        threshold=0.05,
        max_diff_pixels=0,
    )
