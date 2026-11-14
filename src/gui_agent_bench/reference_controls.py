"""Task-local trusted controls, loaded only by reference and scripted helpers."""

import copy
import math
from gui_agent_bench.io import regular_file, strict_json

CONTROLS = {}


def validate_record(record):
    allowed = {'programs', 'journey', 'regions', 'viewport', 'platform', 'initial_delay', 'action_delay', 'capture_ui'}
    if (
        not isinstance(record, dict)
        or set(record) - allowed
        or not {'programs', 'journey', 'regions', 'viewport'} <= set(record)
    ):
        raise ValueError('Unknown or incomplete reference record')
    record = copy.deepcopy(record)
    viewport = record['viewport']
    if (
        not isinstance(viewport, list)
        or len(viewport) != 2
        or any(type(x) is not int or not 320 <= x <= 1920 for x in viewport)
    ):
        raise ValueError('Invalid reference viewport')
    if not isinstance(record['journey'], list) or len(record['journey']) > 77:
        raise ValueError('Reference journey must fit the 80-operation execution cap')
    from gui_agent_bench.actions import validate_visual_step

    for step in record['journey']:
        if record.get('platform') == 'tv':
            from gui_agent_bench.tv import validate_step

            validate_step(step)
        else:
            validate_visual_step(step, viewport)
    from gui_agent_bench.visual import rectangle

    if set(record['regions']) != {'false', 'true'}:
        raise ValueError('Declare regions for oracle and complete-test preparation')
    for regions in record['regions'].values():
        if not isinstance(regions, list) or len(regions) != 3:
            raise ValueError('Each region set needs initial, final and behavior rectangles')
        for region in regions:
            rectangle(region, viewport)
    if not isinstance(record['programs'], dict) or any(
        not isinstance(x, str) or len(x.encode()) > 65_536 for x in record['programs'].values()
    ):
        raise ValueError('Invalid reference source programs')
    for field in ('initial_delay', 'action_delay'):
        value = record.get(field, 0)
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 5:
            raise ValueError('Reference delays must be finite and bounded')
    if type(record.get('capture_ui', False)) is not bool:
        raise ValueError('capture_ui must be boolean')
    return record


class TaskControl:
    def __init__(self, record):
        self.record = validate_record(record)

    def source(self, control, arm):
        return self.record['programs'][arm]

    def journey(self, control):
        return copy.deepcopy(self.record['journey'])

    def regions(self, control, full_test=False):
        return copy.deepcopy(self.record['regions'][str(full_test).lower()])

    def author_actions(self, control, full_test):
        if not full_test:
            return [('gui_observe', {'reference': 'saved'})]
        return [
            ('gui_observe', {'reference': 'screen'}),
            *[('gui_step', step) for step in self.journey(control)],
            ('gui_observe', {'reference': 'saved'}),
        ]

    def response_delay(self, messages, control, arm):
        if not arm.startswith('test_'):
            return 0
        advanced = any(m.get('role') == 'assistant' and m.get('tool_calls') for m in messages)
        return self.record.get('action_delay', 0) if advanced else self.record.get('initial_delay', 0)


def register_record(name, record):
    CONTROLS[name] = TaskControl(record)
    return name


def register_task(task):
    from gui_agent_bench.task_package import metadata, load_control

    data = metadata(task)
    identifier = data['metadata'].get('domain', data['metadata']['platform']) + '/' + data['metadata']['task_id']
    return register_record(identifier, load_control(task))


def load_record_file(path, name='task'):
    record = strict_json(regular_file(path, path.parent))
    return register_record(name, record)


# Backward-compatible, task-owned aliases for command examples. New packages are
# loaded afresh by register_task; discovery itself never executes task code.
def _checkout_aliases():
    from gui_agent_bench.task_package import ROOT, discover, integration, task_path, load_control

    for identifier in discover(ROOT):
        try:
            task = task_path(ROOT, identifier)
            alias = integration(task).get('reference_alias')
            if alias:
                register_record(alias, load_control(task))
        except (ValueError, OSError, KeyError, TypeError):
            # Compatibility aliases are not admission. Selected packages are
            # always validated explicitly before any execution.
            continue


_checkout_aliases()
