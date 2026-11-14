import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gui_agent_bench.failures import Failure
from gui_agent_bench.runners.cursor_logs import collect_gateway_logs, provider_records, validate_streams
from gui_agent_bench.runners.cursor import provider_record_success
from gui_agent_bench.cursor_audit import validate_provider_records


class CursorLogTests(unittest.TestCase):
    def paths(self, root):
        return (
            root / 'cursor-provider.ndjson',
            root / 'cursor-provider-stderr.log',
            root / 'cursor-provider-streams.json',
        )

    def test_streams_are_preserved_byte_exact_and_stderr_is_not_silently_accepted(self):
        stdout = b'{"outcome":"completed","status":200}\n'
        stderr = b'Traceback: synthetic diagnostic\n'
        with tempfile.TemporaryDirectory() as name:
            paths = self.paths(Path(name))
            result = subprocess.CompletedProcess([], 0, stdout, stderr)
            with patch('gui_agent_bench.runners.cursor_logs.subprocess.run', return_value=result):
                collect_gateway_logs('synthetic-gateway', *paths)
            self.assertEqual(paths[0].read_bytes(), stdout)
            self.assertEqual(paths[1].read_bytes(), stderr)
            self.assertEqual(provider_records(paths[0]), [{'outcome': 'completed', 'status': 200}])
            with self.assertRaises(ValueError):
                validate_streams(*paths)

    def test_malformed_stdout_is_never_filtered_or_repaired(self):
        for stdout in (
            b'',
            b'{"status":200}\nTraceback: unexpected stdout\n',
            b'{"a":1,"a":2}\n',
            b'[]\n',
            b'{"a":NaN}\n',
        ):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as name:
                paths = self.paths(Path(name))
                with patch(
                    'gui_agent_bench.runners.cursor_logs.subprocess.run',
                    return_value=subprocess.CompletedProcess([], 0, stdout, b''),
                ):
                    collect_gateway_logs('synthetic-gateway', *paths)
                self.assertEqual(paths[0].read_bytes(), stdout)
                with self.assertRaises(ValueError):
                    validate_streams(*paths)

    def test_hash_mismatch_or_missing_stream_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            paths = self.paths(Path(name))
            with patch(
                'gui_agent_bench.runners.cursor_logs.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, b'{"status":200}\n', b''),
            ):
                collect_gateway_logs('synthetic-gateway', *paths)
            validate_streams(*paths)
            paths[0].write_bytes(b'{"status":403}\n')
            with self.assertRaises(ValueError):
                validate_streams(*paths)
            paths[1].unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                validate_streams(*paths)

    def test_failed_docker_collection_retains_both_streams_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as name:
            paths = self.paths(Path(name))
            with patch(
                'gui_agent_bench.runners.cursor_logs.subprocess.run',
                return_value=subprocess.CompletedProcess([], 1, b'partial stdout\n', b'collection failed\n'),
            ):
                with self.assertRaises(Failure):
                    collect_gateway_logs('synthetic-gateway', *paths)
            self.assertEqual(paths[0].read_bytes(), b'partial stdout\n')
            self.assertEqual(paths[1].read_bytes(), b'collection failed\n')
            self.assertEqual(json.loads(paths[2].read_text())['exit_code'], 1)

    def test_idle_reset_cannot_stand_in_for_a_rpc_or_hide_real_failure(self):
        idle = dict(
            event='client_connection_closed_before_request',
            outcome='client_closed_before_request',
            path=None,
            status=None,
            stage='request_line',
            exception_kind='ConnectionResetError',
            request_category=None,
            sent_bytes=0,
            received_bytes=0,
        )
        self.assertTrue(provider_record_success(idle))
        with self.assertRaises(ValueError):
            validate_provider_records([idle])
        validate_provider_records([idle, {'outcome': 'completed', 'status': 200}])
        for key, value in [
            ('path', '/agent.v1.AgentService/RunSSE'),
            ('sent_bytes', 1),
            ('received_bytes', 1),
            ('stage', 'client_write'),
            ('exception_kind', 'OSError'),
            ('rejection_reason', 'denied'),
        ]:
            with self.subTest(key=key):
                self.assertFalse(provider_record_success({**idle, key: value}))


if __name__ == '__main__':
    unittest.main()
