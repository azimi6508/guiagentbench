"""Admitted native reference; submitted programs never execute this file."""


def test_behavior(page, checkpoint):
    page.require_text('atlas')
    checkpoint('The empty atlas.txt note is open in Markor.')
    page.user_step({'action': 'fill', 'role': 'textbox',
                   'name': 'net.gsantner.markor:id/document__fragment__edit__highlighting_editor',
                   'text': 'Bring the blue notebook.'})
    page.require_text('Bring the blue notebook.')
    checkpoint('The note contains Bring the blue notebook.')
    page.reload()
    page.require_text('atlas')
    checkpoint('The application was closed and the same note reopened.')
    stored = page.check_fixture()
    page.require_text('Bring the blue notebook.')
    assert stored, 'saved note differs'
