"""Fixed visual-reference preparation client. Not an evaluated agent.

No model, submitted Python, labels, private grader or filesystem tools. Only the
hand-written observe/coordinate/remote journey is sent to the authoring broker.
"""

import argparse
import json
import time
import urllib.request


def preparation_actions(control, arm):
    from gui_agent_bench.visual_fixtures import author_actions

    return author_actions(control, arm.startswith('test_'))


def preparation_delay(control, arm, previous):
    """Authored navigation pauses; no result checks, new actions or retries."""
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', required=True)
    parser.add_argument('--arm', choices=['oracle_visual', 'test_visual'], required=True)
    parser.add_argument('--control-file', type=__import__('pathlib').Path)
    args = parser.parse_args()
    if args.control_file:
        from gui_agent_bench.reference_controls import load_record_file

        load_record_file(args.control_file, args.control)
    from gui_agent_bench.visual_fixtures import response_delay

    actions = preparation_actions(args.control, args.arm)
    if not actions or len(actions) > 80 or any(name not in {'gui_observe', 'gui_step'} for name, _ in actions):
        raise ValueError('Unrecognized reference preparation')
    messages = []
    for index, (name, arguments) in enumerate(actions):
        pause = max(
            response_delay(messages, args.control, args.arm),
            preparation_delay(args.control, args.arm, actions[index - 1] if index else None),
        )
        if pause:
            print(json.dumps({'reference_pause_seconds': pause, 'before_action': index + 1}), flush=True)
            time.sleep(pause)
        request = urllib.request.Request(
            'http://browser:8081/mcp',
            data=json.dumps(
                {
                    'jsonrpc': '2.0',
                    'id': index + 1,
                    'method': 'tools/call',
                    'params': {'name': name.removeprefix('gui_'), 'arguments': arguments},
                }
            ).encode(),
            headers={'Content-Type': 'application/json', 'Connection': 'close'},
        )
        with urllib.request.urlopen(request, timeout=95) as response:
            result = json.load(response)
        if result.get('error') or result.get('result', {}).get('isError') is not False:
            raise RuntimeError('Reference observation/action failed')
        print(json.dumps({'reference_action': name, 'arguments': arguments, 'completed': True}), flush=True)
        messages.append(
            {'role': 'assistant', 'tool_calls': [{'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
        )


if __name__ == '__main__':
    main()
