import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from gui_agent_bench.runners.codex_security import ROOT, audit, options, policy


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.metadata = policy()
        self.seccomp = json.loads((ROOT / 'runtime/codex/security/seccomp.json').read_text())
        self.item = {
            'AppArmorProfile': self.metadata['apparmor_profile'],
            'HostConfig': {
                'SecurityOpt': [
                    'no-new-privileges',
                    'seccomp=' + json.dumps(self.seccomp),
                    'apparmor=' + self.metadata['apparmor_profile'],
                ]
            },
        }

    def test_accepts_docker_embedded_policy(self):
        audit(self.item, 'agent')

    def test_rejects_unconfined_missing_duplicate_and_tampered_policy(self):
        for value in ['unconfined', json.dumps(dict(self.seccomp, defaultAction='SCMP_ACT_ALLOW'))]:
            item = copy.deepcopy(self.item)
            item['HostConfig']['SecurityOpt'][1] = 'seccomp=' + value
            with self.assertRaises(ValueError):
                audit(item, 'agent')
        for value in [
            self.item['HostConfig']['SecurityOpt'][:-1],
            self.item['HostConfig']['SecurityOpt'] + ['apparmor=unconfined'],
        ]:
            item = copy.deepcopy(self.item)
            item['HostConfig']['SecurityOpt'] = value
            with self.assertRaises(ValueError):
                audit(item, 'agent')
        item = copy.deepcopy(self.item)
        item['AppArmorProfile'] = 'unconfined'
        with self.assertRaises(ValueError):
            audit(item, 'agent')

    def test_exception_never_applies_to_bridge_or_proxy(self):
        for role in ('bridge', 'egress'):
            with self.assertRaises(ValueError):
                audit(self.item, role)
            audit({'AppArmorProfile': 'docker-default', 'HostConfig': {'SecurityOpt': ['no-new-privileges']}}, role)

    def test_policy_drift_blocks_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'runtime/codex/security'
            shutil.copytree(ROOT / 'runtime/codex/security', target)
            (target / 'seccomp.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'content differs'):
                options(root)

    def test_default_seccomp_rules_preserved(self):
        base = json.loads((ROOT / 'runtime/codex/security/docker-default-seccomp.json').read_text())
        self.assertEqual(
            {k: v for k, v in self.seccomp.items() if k != 'syscalls'},
            {k: v for k, v in base.items() if k != 'syscalls'},
        )
        self.assertEqual(self.seccomp['syscalls'][: len(base['syscalls'])], base['syscalls'])
        additional = self.seccomp['syscalls'][len(base['syscalls']) :]
        self.assertEqual(
            set(n for r in additional for n in r['names']), {'clone', 'unshare', 'mount', 'pivot_root', 'umount2'}
        )
        self.assertTrue(all(r['args'] for r in additional if r['names'] in [['clone'], ['unshare']]))
