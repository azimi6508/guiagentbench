import json
import os
from pathlib import Path
import tempfile
import unittest

from gui_agent_bench.runners.codex_auth import AuthSession, validate_directory, validate_bytes
from gui_agent_bench.docker import client_environment


@unittest.skipUnless(hasattr(os, 'getuid') and os.getuid() != 0, 'Non-root Linux auth contract')
class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gab-auth-test-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.data = json.dumps(
            {
                'auth_mode': 'chatgpt',
                'tokens': {
                    'access_token': 'SYNTHETIC_ACCESS',
                    'id_token': 'SYNTHETIC_ID',
                    'refresh_token': 'SYNTHETIC_REFRESH',
                },
            }
        ).encode()
        (self.path / 'auth.json').write_bytes(self.data)
        (self.path / 'auth.json').chmod(0o600)

    def test_stages_only_auth_and_locks(self):
        (self.path / 'personal-history').write_text('must not stage')
        with AuthSession(self.path) as session:
            self.assertEqual([p.name for p in session.staged.parent.iterdir()], ['auth.json'])
            self.assertEqual(session.staged.read_bytes(), self.data)
            staged = session.staged
            with self.assertRaises(ValueError):
                with AuthSession(self.path):
                    pass
        self.assertFalse(staged.exists())

    def test_atomic_refresh_and_modes(self):
        refreshed = self.data.replace(b'SYNTHETIC_ACCESS', b'REFRESHED_ACCESS')
        with AuthSession(self.path) as session:
            session.persist(refreshed)
        self.assertEqual((self.path / 'auth.json').read_bytes(), refreshed)
        self.assertEqual((self.path / 'auth.json').stat().st_mode & 0o777, 0o600)

    def test_directory_and_file_modes(self):
        self.path.chmod(0o755)
        with self.assertRaises(ValueError):
            validate_directory(self.path)
        self.path.chmod(0o700)
        (self.path / 'auth.json').chmod(0o644)
        with self.assertRaises(ValueError):
            validate_directory(self.path)

    def test_symlink_and_repository_denied(self):
        with self.assertRaises(ValueError):
            validate_directory(self.path, [self.path.parent])
        (self.path / 'saved').write_bytes(self.data)
        (self.path / 'auth.json').unlink()
        (self.path / 'auth.json').symlink_to(self.path / 'saved')
        with self.assertRaises(ValueError):
            validate_directory(self.path)

    def test_invalid_auth_safe_message(self):
        for data in [b'bad SYNTHETIC_ACCESS', b'{"OPENAI_API_KEY":"SYNTHETIC_ACCESS"}', b'x' * 1_048_577]:
            with self.assertRaises(ValueError) as exc:
                validate_bytes(data)
            self.assertNotIn('SYNTHETIC_ACCESS', str(exc.exception))

    def test_transport_drops_credentials_and_proxy(self):
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {
                'OPENAI_API_KEY': 'SYNTHETIC_ACCESS',
                'OPENROUTER_API_KEY': 'SYNTHETIC_ACCESS',
                'ALL_PROXY': 'http://unsafe',
            },
        ):
            self.assertFalse(set(client_environment()) & {'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'ALL_PROXY'})
