Exact UI contract (UI-capable arms only)

`page.get_by_role(role, name="exact accessible name")` requires the `name`
keyword, including `name=""` for an unnamed node. Empty names are permitted;
actions must still identify a unique actionable node. This is a scoped API,
so ordinary Playwright's optional-name signature does not apply. Query strings
are literal, not patterns. Names and text queries have at most 200 characters;
text queries must be nonempty. Expected text/value strings may contain up to
2000 characters. Counts are integers in 0..100.

Supported roles, for both actions and assertions:
alert, alertdialog, application, article, banner, blockquote, button, caption,
cell, checkbox, code, columnheader, combobox, complementary, contentinfo,
definition, deletion, dialog, directory, document, emphasis, feed, figure,
form, generic, grid, gridcell, group, heading, img, insertion, link, list,
listbox, listitem, log, main, marquee, math, menu, menubar, menuitem,
menuitemcheckbox, menuitemradio, meter, navigation, none, note, option,
paragraph, presentation, progressbar, radio, radiogroup, region, row, rowgroup,
rowheader, scrollbar, search, searchbox, separator, slider, spinbutton,
status, strong, subscript, superscript, switch, tab, table, tablist, tabpanel,
term, textbox, time, timer, toolbar, tooltip, tree, treegrid, treeitem.
Native platforms expose only roles actually present in their public UI dump.
A supported role does not guarantee that a matching node exists or is actionable.

Positive preconditions may check visibility, a positive count, or exact
text/value equality, including an empty string. First establish a visible
screen/control before checking an empty value. Hidden-node checks and zero
counts are behavioral assertions; they cannot serve as positive preconditions.

On Android, `name` and `text` are distinct fields: an accessibility description
can supply a name while text is empty. Use exact role/name targeting for such
nodes. `get_by_text` compares the dump's text field, not its name. UI information
and these queries remain unavailable to visual-only arms.
