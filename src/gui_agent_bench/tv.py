"""Remote-key tool contract and trusted journey checkpoint validation."""

from gui_agent_bench.failures import Failure

TV_ARMS = ('judge_visual', 'judge_test', 'oracle_visual', 'test_visual')
TV_KEYS = ('back', 'down', 'exit', 'left', 'menu', 'ok', 'right', 'up')


def validate_step(args):
    if isinstance(args, dict) and (args.get('action') != 'press' or set(args) - {'action', 'key'}):
        raise Failure('policy_violation')
    if (
        not isinstance(args, dict)
        or set(args) != {'action', 'key'}
        or args['action'] != 'press'
        or not isinstance(args['key'], str)
        or args['key'] not in TV_KEYS
    ):
        raise ValueError('TV accepts one allowlisted remote key only')


def validate_call(name, args):
    if name in {'observe', 'reset'} and args == {}:
        return
    if name == 'step':
        return validate_step(args)
    raise Failure('policy_violation')


def tools_for(tools):
    from gui_agent_bench.broker import schema

    result = []
    for tool in tools:
        if tool['name'] not in {'observe', 'reset', 'step'}:
            continue
        if tool['name'] == 'step':
            tool = {
                'name': 'step',
                'description': 'Press one remote key on the TV. No pointer, UI tree, code or state selection.',
                'inputSchema': schema(
                    {'action': {'type': 'string', 'enum': ['press']}, 'key': {'type': 'string', 'enum': list(TV_KEYS)}},
                    ['action', 'key'],
                ),
            }
        result.append(tool)
    return result


def checkpoint_count(source):
    """Called only for admitted reference code, never for a submission."""
    value = source.get('CHECKPOINTS', 3)
    if type(value) is not int or not 3 <= value <= 81:
        raise ValueError('invalid reference checkpoint count')
    return value
