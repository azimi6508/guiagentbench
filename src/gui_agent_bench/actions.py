"""Shared public action contract. UI adds targeting; visual never reads structure."""

from gui_agent_bench.failures import Failure, checked
from gui_agent_bench.coordinates import PIXEL_COORDINATES
from gui_agent_bench.ui_contract import ROLES

KEYS = ['Enter', 'Tab', 'Escape', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Backspace']
ACTION_CONTRACT = 'ui-superset-v1'


def step_tool(ui=False):
    properties = {
        'action': {'type': 'string', 'enum': ['click', 'hover', 'scroll', 'type', 'press', 'reload']},
        'x': {
            'type': 'integer',
            'minimum': 0,
            'description': 'Horizontal original-screenshot pixel coordinate from the left edge.',
        },
        'y': {
            'type': 'integer',
            'minimum': 0,
            'description': 'Vertical original-screenshot pixel coordinate from the top edge.',
        },
        'dx': {'type': 'integer', 'minimum': -2000, 'maximum': 2000},
        'dy': {'type': 'integer', 'minimum': -2000, 'maximum': 2000},
        'text': {'type': 'string', 'maxLength': 2000},
        'key': {'type': 'string', 'enum': KEYS},
    }
    description = (
        'One action: click/hover require x,y; scroll requires dx,dy; type requires text; '
        'press requires key; reload takes no other fields. ' + PIXEL_COORDINATES
    )
    if ui:
        properties['action']['enum'].append('fill')
        properties.update(role={'type': 'string', 'enum': list(ROLES)}, name={'type': 'string', 'maxLength': 200})
        description += (
            'Alternatively click/hover/press can use exact role,name instead of coordinates/focus; '
            'fill requires role,name,text. Never mix targeting forms. '
        )
    description += 'No selectors, code, scripts, HTTP, test execution or action batches.'
    return {
        'name': 'step',
        'description': description,
        'inputSchema': {
            'type': 'object',
            'properties': properties,
            'required': ['action'],
            'additionalProperties': False,
        },
    }


def validate_visual_step(args, viewport, *, native=False, scroll_origin=False):
    if not isinstance(args, dict):
        raise ValueError('invalid action')
    action = args.get('action')
    permitted = {'click', 'hover', 'scroll', 'type', 'press', 'reload'} | (
        {'long_press', 'open_app'} if native else set()
    )
    if isinstance(action, str) and action not in permitted:
        raise Failure('policy_violation')
    fields = {
        'click': {'x', 'y'},
        'hover': {'x', 'y'},
        'scroll': {'dx', 'dy'},
        'type': {'text'},
        'press': {'key'},
        'reload': set(),
    }
    if native:
        fields.update(long_press={'x', 'y'}, open_app={'app'})
    expected = {'action'} | fields.get(action, set())
    if scroll_origin and action == 'scroll' and ('x' in args or 'y' in args):
        expected |= {'x', 'y'}
    if action not in fields or set(args) != expected:
        raise ValueError('action denied')
    for key, bound in [('x', viewport[0]), ('y', viewport[1])]:
        if key in args and (type(args[key]) is not int or not 0 <= args[key] < bound):
            raise ValueError('coordinate outside viewport')
    for key in ('dx', 'dy'):
        if key in args and (type(args[key]) is not int or abs(args[key]) > 2000):
            raise ValueError('scroll budget')
    if action == 'type' and (not isinstance(args['text'], str) or len(args['text']) > 2000):
        raise ValueError('text budget')
    if action == 'open_app' and (not isinstance(args['app'], str) or not 1 <= len(args['app']) <= 100):
        raise ValueError('invalid app name')
    if action == 'press' and args['key'] not in KEYS:
        raise ValueError('key denied')


def validate_step(args, viewport, *, ui, platform, mobile_touch_top=128):
    if platform not in {'web', 'mobile'} or not isinstance(args, dict):
        raise ValueError('action platform or arguments denied')
    if args.get('action') in {'long_press', 'open_app'} and (platform != 'mobile' or mobile_touch_top not in (48, 68)):
        raise Failure('policy_violation')
    targeted = 'role' in args or 'name' in args
    if targeted:
        if not ui:
            raise Failure('policy_violation')
        from gui_agent_bench.broker import validate_call

        validate_call('step', args)
    else:
        validate_visual_step(
            args, viewport, native=platform == 'mobile', scroll_origin=platform == 'mobile' and mobile_touch_top == 68
        )
    if platform == 'mobile':
        if mobile_touch_top not in (48, 68, 128):
            raise ValueError('Unadmitted native touch region')
        if args['action'] == 'hover':
            raise Failure('policy_violation')
        if (
            not targeted
            and (args['action'] in {'click', 'long_press'} or (args['action'] == 'scroll' and 'x' in args))
            and not mobile_touch_top <= args['y'] < (1184 if mobile_touch_top in (48, 68) else 1244)
        ):
            raise Failure('policy_violation')
    return targeted


def execute_step(adapter, args, viewport, *, ui, platform):
    top = getattr(adapter, 'mobile_touch_top', 128)
    top = top if type(top) is int else 128
    targeted = checked(validate_step, args, viewport, ui=ui, platform=platform, mobile_touch_top=top)
    if targeted:
        return adapter.user_step(args)
    if platform == 'mobile':
        return adapter.visual_step(args)
    adapter._require_context()
    action = args['action']
    if action in {'click', 'hover'}:
        (adapter.page.mouse.click if action == 'click' else adapter.page.mouse.move)(args['x'], args['y'])
    elif action == 'scroll':
        adapter.page.mouse.wheel(args['dx'], args['dy'])
    elif action == 'type':
        adapter.page.keyboard.insert_text(args['text'])
    elif action == 'press':
        adapter.page.keyboard.press(args['key'])
    else:
        adapter.page.reload(wait_until='domcontentloaded')
    adapter._wait_for_settled_page()
