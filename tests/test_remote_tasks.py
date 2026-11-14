"""Remote packages integrate by manifest and profile, without corpus catalogs."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.io import dump
from gui_agent_bench.task_package import seal_manifest, verify
from gui_agent_bench.tv import TV_ARMS

ROOT = Path(__file__).resolve().parents[1]


class RemoteTasks(unittest.TestCase):
    def test_arbitrary_remote_package_needs_only_its_own_files_and_image(self):
        from gui_agent_bench.tv_session import app_mounts
        from gui_agent_bench.preflight import check
        from gui_agent_bench.run_plan import prepare
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = root / 'tasks/tv/new-remote-behavior'
            shutil.copytree(ROOT / 'tasks/tv/aura-013-caption-preview-size', task)
            path = task / 'task.toml'
            text = path.read_text().replace('aura-013-caption-preview-size', 'new-remote-behavior')
            text = text.replace('platform = "web"', 'platform = "tv"')
            text = text.replace('"oracle_visual", "oracle_ui", "test_visual", "test_ui"', '"oracle_visual", "test_visual"')
            text = text.replace('environment_profile = "aura-tv"', 'environment_profile = "tv"')
            path.write_text(text)
            record = json.loads((task / 'private/reference.json').read_text())
            record['platform'] = 'tv'
            record['journey'] = [{'action': 'press', 'key': 'ok'}]
            record['programs'] = {a: p for a, p in record['programs'].items() if a in TV_ARMS}
            dump(task / 'private/reference.json', record)
            seal_manifest(task)
            verify(task)
            self.assertEqual(app_mounts(task, 'tv'), [])
            plan = prepare(root, {'schema': 'run-plan-v1', 'models': ['reference/solution'],
                                 'tasks': [{'task': 'tv/new-remote-behavior', 'arms': list(TV_ARMS)}]})
            with patch('gui_agent_bench.preflight.command', return_value='linux'):
                result = check(root, plan)
            self.assertEqual(result['status'], 'passed')
            self.assertFalse((root / 'datasets').exists())
            self.assertFalse((root / '.tv').exists())

    def test_remote_visual_judge_uses_the_same_default_checkpoint_count_as_capture(self):
        from gui_agent_bench.materialize import materialize
        from gui_agent_bench.io import digest
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            task = base / 'task'
            task.mkdir()
            (task / 'task.toml').write_text('[metadata]\nplatform="tv"\n[integration]\nenvironment_profile="tv"\n')
            (task / 'instruction.md').write_text('Inspect the selected screen.')
            (task / 'arms').mkdir()
            (task / 'arms/judge_visual.md').write_text('Judge the images.')
            evidence = base / 'evidence'
            (evidence / 'screenshots').mkdir(parents=True)
            frames = []
            for index in range(1, 4):
                name = f'screenshots/{index:04d}.png'
                data = b'\x89PNG\r\n\x1a\n' + bytes([index])
                (evidence / name).write_bytes(data)
                frames.append({'path': name, 'sha256': digest(data), 'index': index})
            dump(evidence / 'manifest.json', {'frames': frames})
            dump(evidence / 'steps.json', ['Initial', 'Selection', 'Final'])
            result = materialize(ROOT, task, evidence, base / 'workspace', 'judge_visual', 'tv', viewport=(960, 540))
            self.assertEqual(sum(p.startswith('evidence/screenshots/') for p in result['files']), 3)

    def test_remote_application_audit_rejects_extra_private_mounts(self):
        from gui_agent_bench.tv_session import audit_app, VERSION
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            app = {'HostConfig': {'ReadonlyRootfs': True, 'Privileged': False,
                   'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges']},
                   'Config': {'User': 'app'},
                   'NetworkSettings': {'Networks': {'capture': {}}, 'Ports': {}},
                   'Mounts': [{'Type': 'bind', 'Destination': '/settings.json', 'RW': False}]}
            dump(folder / 'app-container.json', app)
            dump(folder / 'app-network.json', {'Name': 'capture', 'Internal': True})
            dump(folder / 'tv-runtime.json', {'schema': VERSION, 'task': 'tv/new-remote-behavior',
                 'profile': 'tv', 'transport': 'remote-call'})
            self.assertEqual(audit_app(folder)['status'], 'pass')
            app['Mounts'].append({'Type': 'bind', 'Destination': '/private', 'RW': False})
            dump(folder / 'app-container.json', app)
            with self.assertRaises(ValueError):
                audit_app(folder)
