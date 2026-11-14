import fnmatch
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.runners.codex import require_qualification
from gui_agent_bench.runners.codex_config import model_catalog, qualification_path, render
from gui_agent_bench.runners.registry import fingerprint, resolve


ROOT = Path(__file__).resolve().parents[1]


RESTRICTED = {
    'tool_mode': 'direct',
    'multi_agent_version': None,
    'apply_patch_tool_type': None,
    'supports_search_tool': False,
    'use_responses_lite': False,
    'experimental_supported_tools': [],
}


def checkout_with_catalog(folder, model, **fields):
    """A minimal checkout holding the base config and one synthetic local catalog."""
    root = Path(folder) / 'checkout'
    (root / 'configs/codex/models').mkdir(parents=True)
    shutil.copy(ROOT / 'configs/codex/base.toml', root / 'configs/codex/base.toml')
    entry = {'slug': model, 'display_name': model, **RESTRICTED, **fields}
    (root / 'configs/codex/models' / (model + '.json')).write_text(json.dumps({'models': [entry]}))
    return root


class ModelProfileTests(unittest.TestCase):
    def test_no_provider_catalogs_are_distributed(self):
        # Users supply catalogs locally (see the folder README). They must stay
        # outside every distribution channel: Git, Docker contexts and wheels.
        def rules(name):
            return [
                line.strip()
                for line in (ROOT / name).read_text().splitlines()
                if line.strip() and not line.lstrip().startswith('#')
            ]

        gitignore, dockerignore = rules('.gitignore'), rules('.dockerignore')
        self.assertIn('configs/codex/models/*.json', gitignore)
        for line in gitignore:
            self.assertFalse(line.startswith('!') and fnmatch.fnmatch('configs/codex/models/x.json', line[1:]), line)
        for entry in (ROOT / 'configs/codex/models').iterdir():
            with self.subTest(entry=entry.name):
                # Anything else, such as a subfolder or non-JSON file, would be tracked.
                self.assertTrue(entry.name == 'README.md' or (entry.is_file() and entry.suffix == '.json'))
        self.assertEqual(dockerignore[0], '*')
        for line in dockerignore:
            if line.startswith('!'):
                self.assertFalse(
                    fnmatch.fnmatch('configs/codex/models/x.json', line[1:])
                    or line[1:].rstrip('/') in {'configs/codex/models', 'configs/**', 'configs/codex/**'},
                    line,
                )
        pyproject = (ROOT / 'pyproject.toml').read_text()
        self.assertNotIn('configs/codex/models', pyproject)
        self.assertNotIn('model-catalog', pyproject)

    def test_local_catalog_keeps_exact_identity_and_restricted_tools(self):
        for model in ('gpt-6-luna', 'gpt-6-astra', 'gpt-5.6-luna'):
            with self.subTest(model=model), tempfile.TemporaryDirectory() as folder:
                root = checkout_with_catalog(folder, model)
                output = Path(folder) / 'out'
                config = render(root, output, resolve('codex/' + model), 'test_ui', 'mobile', 'native_extended')
                self.assertEqual(config['model'], model)
                self.assertEqual(config['model_reasoning_effort'], 'medium')
                self.assertEqual(config['model_catalog_json'], '/config/model-catalog.json')
                selected = json.loads((output / 'model-catalog.json').read_text())['models']
                self.assertEqual([m['slug'] for m in selected], [model])
                self.assertEqual({k: selected[0][k] for k in RESTRICTED}, RESTRICTED)

    def test_catalog_is_optional(self):
        with tempfile.TemporaryDirectory() as folder:
            root = checkout_with_catalog(folder, 'other-model')
            output = Path(folder) / 'out'
            config = render(root, output, resolve('codex/gpt-6.1-sol'), 'judge_visual', 'web')
            self.assertNotIn('model_catalog_json', config)
            self.assertFalse((output / 'model-catalog.json').exists())
            self.assertIsNone(model_catalog(root, 'gpt-6.1-sol'))

    def test_catalog_without_tool_restriction_or_for_another_model_is_rejected(self):
        for field, value in [
            ('tool_mode', 'freeform'),
            ('supports_search_tool', True),
            ('multi_agent_version', 'v2'),
            ('experimental_supported_tools', ['x']),
        ]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                root = checkout_with_catalog(folder, 'gpt-6-luna', **{field: value})
                with self.assertRaises(ValueError):
                    render(root, Path(folder) / 'out', resolve('codex/gpt-6-luna'), 'judge_visual', 'web')
        with tempfile.TemporaryDirectory() as folder:
            root = checkout_with_catalog(folder, 'gpt-6-luna')
            (root / 'configs/codex/models/gpt-6-luna.json').rename(root / 'configs/codex/models/gpt-6-astra.json')
            with self.assertRaises(ValueError):
                model_catalog(root, 'gpt-6-astra')

    def test_generic_mobile_certificate_cannot_enable_native_extended(self):
        spec = resolve('codex/gpt-6-luna')
        lock = {'synthetic': True}
        certificate = dict(
            status='passed',
            runtime_lock_sha256=fingerprint(lock),
            images={},
            qualified_profiles=[[spec.model, 'medium', 'test_ui', 'mobile']],
        )
        with (
            tempfile.TemporaryDirectory() as folder,
            patch('gui_agent_bench.runners.codex.validate_lock', return_value=lock),
            patch('gui_agent_bench.runners.codex.image_ids', return_value={}),
        ):
            root = Path(folder)
            path = qualification_path(root, spec)
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(certificate))
            require_qualification(root, spec, 'test_ui', 'mobile')
            with self.assertRaises(ValueError):
                require_qualification(root, spec, 'test_ui', 'mobile', 'native_extended')
            certificate['qualified_environment_profiles'] = [
                [spec.model, 'medium', 'test_ui', 'mobile', 'native_extended']
            ]
            path.write_text(json.dumps(certificate))
            require_qualification(root, spec, 'test_ui', 'mobile', 'native_extended')
            with self.assertRaises(ValueError):
                require_qualification(root, spec, 'test_visual', 'mobile', 'native_extended')

    def test_model_and_effort_certificates_cannot_cross_qualify(self):
        luna = resolve('codex/gpt-5.6-luna')
        sol = resolve('codex/gpt-6.1-sol')
        lock = {'synthetic': True}
        certificate = dict(
            status='passed',
            runtime_lock_sha256=fingerprint(lock),
            images={},
            qualified_profiles=[['gpt-6.1-sol', 'medium', 'judge_visual', 'web']],
        )
        with (
            tempfile.TemporaryDirectory() as folder,
            patch('gui_agent_bench.runners.codex.validate_lock', return_value=lock),
            patch('gui_agent_bench.runners.codex.image_ids', return_value={}),
        ):
            root = Path(folder)
            old = qualification_path(root, sol)
            old.parent.mkdir(parents=True)
            old.write_text(json.dumps(certificate))
            old_bytes = old.read_bytes()
            require_qualification(root, sol, 'judge_visual', 'web')
            with self.assertRaises(ValueError):
                require_qualification(root, luna, 'judge_visual', 'web')
            new = qualification_path(root, luna)
            new.parent.mkdir()
            new.write_text(json.dumps(certificate))
            with self.assertRaises(ValueError):
                require_qualification(root, luna, 'judge_visual', 'web')
            certificate['qualified_profiles'] = [['gpt-5.6-luna', 'medium', 'judge_visual', 'web']]
            new.write_text(json.dumps(certificate))
            require_qualification(root, luna, 'judge_visual', 'web')
            for arm, platform in [('test_ui', 'web'), ('judge_visual', 'mobile')]:
                with self.assertRaises(ValueError):
                    require_qualification(root, luna, arm, platform)
            with self.assertRaises(ValueError):
                require_qualification(
                    root, resolve('codex/gpt-5.6-luna', reasoning_effort='high'), 'judge_visual', 'web'
                )
            self.assertEqual(old.read_bytes(), old_bytes)
