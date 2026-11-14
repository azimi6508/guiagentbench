"""Sealed reference test for WebArena task 399 ("Change my reddit bio to 'I am a robot'").

The trusted harness resets the forum first; checkpoint only records screenshots.
The final assertion is the upstream WebArena program_html check: the profile's
`.user-bio__biography` text must exactly equal the requested biography.
"""
from playwright.sync_api import expect


def test_behavior(page, checkpoint):
    expect(page.get_by_role('heading', name='MarvelsGrantMan136', exact=True)).to_be_visible()
    checkpoint('The signed-in profile is open with its initial biography.')
    page.get_by_role('link', name='Edit biography', exact=True).click()
    page.get_by_role('textbox', name='Biography', exact=True).fill('I am a robot')
    checkpoint('The biography editor contains I am a robot before saving.')
    page.get_by_role('button', name='Save', exact=True).click()
    page.get_by_role('link', name='Home', exact=True).click()
    page.reload(wait_until='domcontentloaded')
    expect(page.get_by_role('heading', name='MarvelsGrantMan136', exact=True)).to_be_visible()
    checkpoint('Save was clicked and the profile was reopened and reloaded.')
    expect(page.locator('.user-bio__biography')).to_have_text('I am a robot')
