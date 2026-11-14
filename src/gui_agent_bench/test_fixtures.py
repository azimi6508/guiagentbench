"""Hand-written complete tests, separate from evaluated agent inputs."""


def source(control, arm):
    from gui_agent_bench.reference_controls import CONTROLS

    if control in CONTROLS:
        return CONTROLS[control].source(control, arm)
    from gui_agent_bench.oracle_fixtures import source as oracle_source

    code = oracle_source(control, arm.replace('test_', 'oracle_'))
    return code.replace('def check(', 'def test(') if code else None
