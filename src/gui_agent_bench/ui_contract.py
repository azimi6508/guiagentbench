"""Public exact-role vocabulary pinned to Playwright's installed 1.55 API.

Roles identify observed UI nodes; admitting a role never admits selectors,
evaluation, implementation source, or UI access in a visual-only arm.
"""

ROLES = tuple(
    sorted(
        '''alert alertdialog application article banner blockquote
button caption cell checkbox code columnheader combobox complementary contentinfo
definition deletion dialog directory document emphasis feed figure form generic
grid gridcell group heading img insertion link list listbox listitem log main
marquee math menu menubar menuitem menuitemcheckbox menuitemradio meter navigation
none note option paragraph presentation progressbar radio radiogroup region row
rowgroup rowheader scrollbar search searchbox separator slider spinbutton status
strong subscript superscript switch tab table tablist tabpanel term textbox time
timer toolbar tooltip tree treegrid treeitem'''.split()
    )
)


def validate_role_name(role, name):
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('role denied')
    if not isinstance(name, str) or len(name) > 200:
        raise ValueError('accessible name budget')


def positive_precondition(condition, expected):
    """Empty string equality is positive; invisibility/absence is not."""
    if condition in {'text', 'value'}:
        return isinstance(expected, str)
    if condition == 'visible':
        return expected is True
    return condition == 'count' and type(expected) is int and expected > 0
