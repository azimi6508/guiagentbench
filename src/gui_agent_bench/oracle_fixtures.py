"""Hand-written oracle controls use the same public tools as evaluated code."""


def source(control, arm):
    from gui_agent_bench.reference_controls import CONTROLS

    if control in CONTROLS:
        return CONTROLS[control].source(control, arm)
    if control == 'missing':
        return None
    negatives = {
        'pass': 'pass',
        'fail': 'raise AssertionError("control failure")',
        'crash': 'raise RuntimeError("control crash")',
        'forbidden': 'page._call("evaluate", code="document.body.innerHTML")',
    }
    if control not in negatives:
        raise ValueError('Unknown reference control')
    return 'def check(page):\n    ' + negatives[control] + '\n'
