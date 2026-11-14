import json
from pathlib import Path
import subprocess
import sys
import unittest

from gui_agent_bench.runners.registry import resolve, fingerprint
from gui_agent_bench.run_plan import prepare
from gui_agent_bench.cli import parser
from gui_agent_bench.budgets import codex_budget, agent_steps

ROOT = Path(__file__).resolve().parents[1]


class RegistryTests(unittest.TestCase):
    def test_prefixes(self):
        for identifier, runner, model in [
            ('fixture/scripted', 'opencode', 'scripted'),
            ('openrouter/vendor/model', 'opencode', 'vendor/model'),
            ('codex/gpt-6.1-sol', 'codex', 'gpt-6.1-sol'),
            ('reference/solution', 'reference', 'solution'),
        ]:
            value = resolve(identifier)
            self.assertEqual((value.identifier, value.runner, value.model), (identifier, runner, model))

    def test_invalid_models(self):
        for identifier in ['', 'codex/', 'codex/ a', 'fixture/other', 'reference/foo', 'other/foo', 'codex/../x']:
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                resolve(identifier)

    def test_probe_exclusivity(self):
        with self.assertRaises(ValueError):
            resolve('codex/gpt-6.1-sol', fixture_probe=True)

    def test_identity_effort(self):
        self.assertNotEqual(
            fingerprint(resolve('codex/x', reasoning_effort='low').record()), fingerprint(resolve('codex/x').record())
        )
        self.assertNotIn('auth_dir', json.dumps(resolve('codex/x').record()))

    def test_structural_plan_without_auth(self):
        spec = json.loads((ROOT / 'jobs/codex-example.json').read_text())
        self.assertEqual(len(prepare(ROOT, spec)['cells']), 6)
        spec['models'].append('reference/solution')
        with self.assertRaises(ValueError):
            prepare(ROOT, spec)

    def test_parser(self):
        args = parser().parse_args(
            [
                'run',
                '--task',
                'web/webarena-399-profile-bio',
                '--model',
                'codex/x',
                '--codex-auth-dir',
                '/synthetic',
                '--codex-reasoning-effort',
                'high',
            ]
        )
        self.assertEqual(args.codex_reasoning_effort, 'high')
        self.assertEqual(parser().parse_args(['build', '--runner', 'all']).runner, 'all')

    def test_plan_parser_authless(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / 'scripts/bench.py'),
                'run',
                '--plan',
                str(ROOT / 'jobs/codex-example.json'),
                '--check-plan',
                '--codex-reasoning-effort',
                'high',
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_mcp_required_for_cli(self):
        script = '''import builtins
original=builtins.__import__
def guard(name,*args,**kwargs):
 if name=='mcp' or name.startswith('mcp.'):raise ImportError('not installed')
 return original(name,*args,**kwargs)
builtins.__import__=guard
from gui_agent_bench.cli import parser
from gui_agent_bench.runners.registry import resolve
from gui_agent_bench.runners.opencode_adapter import author
parser();resolve('fixture/scripted')
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_budget_cohorts(self):
        self.assertEqual(agent_steps('test_ui'), 200)
        value = codex_budget('test_ui', 600)
        self.assertEqual(value['bridge_calls'], 800)
        self.assertIsNone(value['model_requests'])
        self.assertIsNone(value['per_request_output_token_cap'])
