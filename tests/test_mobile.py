import json
from pathlib import Path
import sys
import tempfile
import shutil
import io
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.mobile_driver import Driver, nodes_from_xml
from gui_agent_bench.materialize import materialize
from gui_agent_bench.oracle_broker import tools_for, validate_assertion
from gui_agent_bench.failures import Failure
from gui_agent_bench.broker import platform_tools
from gui_agent_bench.task_runtime import runtime


class MobileBoundaries(unittest.TestCase):

    def test_readiness_checks_native_schema_and_rejects_platform_mismatch(self):
        from gui_agent_bench.readiness import main

        responses = [
            io.BytesIO(json.dumps(v).encode())
            for v in (
                {'ready': True, 'platform': 'mobile'},
                {'result': {}},
                {'result': {'tools': platform_tools(tools_for('test_visual'), 'mobile')}},
            )
        ]
        with patch('urllib.request.urlopen', side_effect=responses):
            main('test_visual', platform='mobile')
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"ready":true,"platform":"web"}')):
            with self.assertRaises(ValueError):
                main('test_visual', platform='mobile')

    def test_reference_tampering_fails_native_lineage(self):
        from gui_agent_bench.task_package import verify as verify_mobile

        original = ROOT / 'tasks/mobile/markor-note-persistence'
        self.assertEqual(verify_mobile(original)['status'], 'pass')
        with tempfile.TemporaryDirectory() as temp:
            task = Path(temp) / 'task'
            shutil.copytree(original, task)
            (task / 'private/test_source.py').write_text('def test_behavior(*args): pass\n')
            with self.assertRaises(ValueError):
                verify_mobile(task)

    def test_mobile_goal_workspace_has_no_reference_or_recording(self):
        task = ROOT / 'tasks/mobile/markor-note-persistence'
        with tempfile.TemporaryDirectory() as temp:
            for arm in ('test_visual', 'test_ui'):
                dest = Path(temp) / arm
                manifest = materialize(ROOT, task, Path(temp) / 'absent', dest, arm, 'mobile')
                self.assertEqual(set(manifest['files']), {'instruction.md'})
                self.assertNotIn('lose_note_on_restart', (dest / 'instruction.md').read_text())
                self.assertNotIn('document__fragment', (dest / 'instruction.md').read_text())

    def test_native_driver_never_accepts_raw_device_capabilities(self):
        driver = object.__new__(Driver)
        for op in ('shell', 'adb', 'install_app', 'evaluate', 'pull', 'open_url', 'dump_hierarchy'):
            with self.assertRaises(ValueError):
                driver.call(op, {})
        for op in ('reset', 'home', 'reload', 'screenshot', 'ui', 'check_fixture'):
            with self.assertRaises(ValueError):
                driver.call(op, {'path': '/private/labels.json'})

    def test_visual_queries_are_rejected_before_driver(self):
        query = {
            'kind': 'ui',
            'query': {'text': 'secret'},
            'condition': 'visible',
            'expected': True,
            'precondition': False,
        }
        for arm in ('oracle_visual', 'test_visual'):
            self.assertNotIn('dump_ui', [t['name'] for t in platform_tools(tools_for(arm), 'mobile')])
            with self.assertRaises(ValueError):
                validate_assertion(query, arm, (720, 1280))

    def test_native_tree_contains_only_admitted_package(self):
        xml = '<hierarchy><node package="other.app" text="private" bounds="[0,0][1,1]"/>'
        xml += '<node package="net.gsantner.markor" class="android.widget.EditText" resource-id="editor" '
        xml += 'text="note" bounds="[0,128][720,900]" enabled="true"/></hierarchy>'
        nodes = nodes_from_xml(xml, 'net.gsantner.markor')
        self.assertEqual(len(nodes), 1)
        self.assertEqual((nodes[0]['role'], nodes[0]['name'], nodes[0]['text']), ('textbox', 'editor', 'note'))

    def test_mobile_settling_timeout_does_not_report_success(self):
        driver = object.__new__(Driver)
        with (
            patch.object(driver, 'nodes', return_value=[]),
            patch('time.sleep'),
            patch('time.monotonic', side_effect=[0, 1, 2, 13, 13]),
        ):
            with self.assertRaises(Failure) as caught:
                driver.settle()
            self.assertEqual(caught.exception.cause, 'app_not_ready')

    def test_runtime_and_native_tool_surface_are_explicit(self):
        values = runtime(ROOT / 'tasks/mobile/markor-note-persistence')
        self.assertEqual(values['platform'], 'mobile')
        self.assertEqual((values['viewport_width'], values['viewport_height']), (720, 1280))
        for arm in ('oracle_visual', 'oracle_ui', 'test_visual', 'test_ui'):
            tools = platform_tools(tools_for(arm), 'mobile')
            step = next(t for t in tools if t['name'] == 'step')
            self.assertNotIn('hover', step['inputSchema']['properties']['action']['enum'])

    def test_native_sample_returning_after_deadline_cannot_succeed(self):
        driver = object.__new__(Driver)
        with (
            patch.object(driver, 'nodes', return_value=[{'text': 'stable'}]),
            patch('time.sleep'),
            patch('time.monotonic', side_effect=[0, 0, 0, 0.1, 13, 13, 13]),
        ):
            with self.assertRaises(Failure) as caught:
                driver.settle()
            self.assertEqual(caught.exception.cause, 'app_not_ready')


if __name__ == '__main__':
    unittest.main()
