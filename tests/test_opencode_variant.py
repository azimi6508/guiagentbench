"""The optional OpenCode model variant: selection, client profile and relay enforcement."""

import json
import tempfile
import threading
import unittest
from contextlib import contextmanager, redirect_stdout
from http.client import HTTPConnection
from http.server import HTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gui_agent_bench import gateway
from gui_agent_bench.cli import parser
from gui_agent_bench.runners.opencode import configuration
from gui_agent_bench.runners.registry import resolve, spec_for

ROOT = Path(__file__).resolve().parents[1]
TOOLS = [{'type': 'function', 'function': {'name': 'read'}}]


@contextmanager
def relay(reasoning_effort):
    servers, ready = [], threading.Event()

    def bind(_address, handler):
        servers.append(HTTPServer(('127.0.0.1', 0), handler))
        ready.set()
        return servers[0]

    with patch.object(gateway, 'HTTPServer', side_effect=bind):
        thread = threading.Thread(
            target=gateway.serve,
            args=('fixture', 'scripted'),
            kwargs={'reasoning_effort': reasoning_effort},
            daemon=True,
        )
        thread.start()
        try:
            if not ready.wait(5):
                raise RuntimeError('relay fixture did not bind')
            yield servers[0].server_address
        finally:
            servers[0].shutdown()
            servers[0].server_close()
            thread.join(5)


def post(address, payload):
    connection = HTTPConnection(*address, timeout=5)
    connection.request('POST', '/v1/chat/completions', json.dumps(payload), {'Content-Type': 'application/json'})
    response = connection.getresponse()
    response.read()
    connection.close()
    return response.status


class OpenCodeVariantTests(unittest.TestCase):
    def test_variant_applies_only_to_the_opencode_runner(self):
        self.assertIsNone(spec_for('openrouter/provider/model').reasoning_effort)
        self.assertEqual(spec_for('openrouter/provider/model', opencode_variant='high').reasoning_effort, 'high')
        self.assertEqual(spec_for('fixture/scripted', opencode_variant='low').reasoning_effort, 'low')
        self.assertEqual(
            spec_for('codex/model', codex_effort='medium', opencode_variant='high').reasoning_effort, 'medium'
        )
        self.assertEqual(
            spec_for('claude/claude-model', claude_effort='low', opencode_variant='high').reasoning_effort, 'low'
        )
        self.assertIsNone(spec_for('reference/solution', opencode_variant='high').reasoning_effort)
        with self.assertRaisesRegex(ValueError, 'variant'):
            resolve('openrouter/provider/model', variant='max')

    def test_cli_accepts_only_admitted_variants(self):
        base = ['run', '--task', 'web/webarena-399-profile-bio', '--model', 'openrouter/provider/model']
        self.assertIsNone(parser().parse_args(base).opencode_variant)
        self.assertEqual(parser().parse_args(base + ['--opencode-variant', 'high']).opencode_variant, 'high')
        with self.assertRaises(SystemExit), redirect_stdout(StringIO()), patch('sys.stderr', StringIO()):
            parser().parse_args(base + ['--opencode-variant', 'max'])

    def test_default_profile_is_unchanged_and_variant_declares_reasoning(self):
        with tempfile.TemporaryDirectory() as folder:
            plain = configuration(ROOT, Path(folder) / 'plain.json', 'relay', 'model', 'test_ui')
            high = configuration(ROOT, Path(folder) / 'high.json', 'relay', 'model', 'test_ui', variant='high')
        entry = plain['provider']['relay']['models']['model']
        self.assertNotIn('reasoning', entry)
        self.assertNotIn('variants', entry)
        selected = high['provider']['relay']['models']['model']
        self.assertEqual((selected['reasoning'], selected['variants']), (True, {'high': {'reasoningEffort': 'high'}}))
        selected = {k: v for k, v in selected.items() if k not in ('reasoning', 'variants')}
        self.assertEqual(selected, entry)
        self.assertEqual(
            {k: v for k, v in high.items() if k != 'provider'}, {k: v for k, v in plain.items() if k != 'provider'}
        )

    def test_relay_requires_the_selected_variant_on_every_agent_turn(self):
        turn = {'model': 'scripted', 'messages': [{'role': 'user', 'content': 'x'}], 'tools': TOOLS}
        output = StringIO()
        with redirect_stdout(output), relay('high') as address:
            # The client's title request offers no tools and keeps its own setting.
            self.assertEqual(post(address, {'model': 'scripted', 'messages': [], 'reasoning_effort': 'low'}), 200)
            self.assertEqual(post(address, dict(turn, reasoning_effort='high')), 200)
            self.assertEqual(post(address, turn), 400)
            self.assertEqual(post(address, dict(turn, reasoning_effort='low')), 400)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([r['reasoning_effort'] for r in records if r.get('variant_verified')], ['high'])
        self.assertEqual(sum(bool(r.get('capability_error')) for r in records), 2)
        self.assertEqual([r['failure']['cause'] for r in records if 'failure' in r], ['capability_unavailable'] * 2)

    def test_relay_without_a_variant_adds_no_requirement(self):
        output = StringIO()
        with redirect_stdout(output), relay(None) as address:
            self.assertEqual(
                post(address, {'model': 'scripted', 'messages': [{'role': 'user', 'content': 'x'}], 'tools': TOOLS}),
                200,
            )
        self.assertFalse(any('variant_verified' in line for line in output.getvalue().splitlines()))
        with self.assertRaisesRegex(ValueError, 'reasoning effort'):
            gateway.serve('fixture', 'scripted', reasoning_effort='max')

    def test_plan_run_passes_and_records_the_variant_for_every_cell(self):
        from gui_agent_bench.run_plan import execute

        seen = []

        def runner(root, task, arm, variant, model, destination, *args, **kwargs):
            seen.append(kwargs.get('agent_spec'))
            raise ValueError('stop before any container')

        plan = {
            'schema': 'run-plan-v1',
            'name': 'variant',
            'models': ['fixture/scripted'],
            'tasks': [{'task': 'web/webarena-399-profile-bio', 'arms': ['judge_visual', 'test_ui'], 'repeats': 1}],
        }
        for variant in ('high', None):
            seen.clear()
            with tempfile.TemporaryDirectory() as folder, redirect_stdout(StringIO()):
                _, manifest = execute(
                    ROOT,
                    plan,
                    Path(folder),
                    runner=runner,
                    preflight=lambda *_, **__: {'status': 'passed', 'checks': []},
                    opencode_variant=variant,
                )
            self.assertEqual([spec.reasoning_effort if spec else None for spec in seen], [variant, variant])
            self.assertEqual([cell.get('model_variant') for cell in manifest['cells']], [variant, variant])


if __name__ == '__main__':
    unittest.main()
