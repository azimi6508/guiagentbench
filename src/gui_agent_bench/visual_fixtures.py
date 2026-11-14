"""Public screenshot journeys and sealed reference programs."""


def implementation(control):
    from gui_agent_bench.reference_controls import CONTROLS

    if control in CONTROLS:
        return CONTROLS[control]
    raise ValueError('Unknown screenshot reference control')


def journey(control):
    return implementation(control).journey(control)


def regions(control, full_test=False):
    return implementation(control).regions(control, full_test)


def author_actions(control, full_test):
    if control in {'missing', 'pass', 'fail', 'crash', 'forbidden'}:
        return []
    return implementation(control).author_actions(control, full_test)


def response_delay(messages, control, arm):
    if control in {'missing', 'pass', 'fail', 'crash', 'forbidden'}:
        return 0
    return implementation(control).response_delay(messages, control, arm)


def source(control, full_test):
    return implementation(control).source(control, 'test_visual' if full_test else 'oracle_visual')
