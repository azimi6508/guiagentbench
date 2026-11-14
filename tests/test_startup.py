"""Run launcher boundary regressions when Node is available on the host."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class StartupTests(unittest.TestCase):
    def test_all_live_arms_disable_mcp_connection_reuse(self):
        from gui_agent_bench.arms import ARM_IDS
        from gui_agent_bench.runners.opencode import configuration

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            for arm in ARM_IDS:
                config = configuration(root, Path(temporary) / 'config.json', 'relay', 'scripted', arm)
                if arm == 'judge_visual':
                    self.assertEqual(config['mcp'], {})
                else:
                    self.assertEqual(config['mcp']['gui']['headers'], {'Connection': 'close'})

    @unittest.skipUnless(shutil.which('node'), 'Node needed; alternatively run test_startup.cjs in the agent image')
    def test_launcher_boundaries(self):
        result = subprocess.run(
            ['node', '--test', str(Path(__file__).with_suffix('.cjs'))], capture_output=True, text=True, timeout=20
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
