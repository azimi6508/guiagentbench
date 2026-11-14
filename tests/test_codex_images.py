import base64
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

from gui_agent_bench.codex_bridge import Bridge
from gui_agent_bench.io import digest
from gui_agent_bench.viewer.evidence import allowed, image_parts


@unittest.skipUnless(
    importlib.util.find_spec('PIL') and importlib.util.find_spec('jsonschema'), 'Visual and Codex extras required'
)
class ImageTests(unittest.TestCase):
    def test_original_image_and_metadata(self):
        from PIL import Image

        data = io.BytesIO()
        Image.new('RGB', (960, 640), 'purple').save(data, format='PNG')
        png = data.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'workspace').mkdir()
            (root / 'output').mkdir()
            (root / 'workspace/screen.png').write_bytes(png)
            bridge = Bridge(
                root / 'workspace',
                root / 'output',
                root / 'audit',
                {'files': {'screen.png': digest(png)}},
                'judge_visual',
                'web',
                (960, 640),
            )
            result = bridge.call('bench_read_image', {'path': '/workspace/screen.png'}, 1)
            self.assertFalse(result['isError'])
            self.assertEqual(base64.b64decode(result['content'][0]['data']), png)
            self.assertIn('width=960', result['content'][1]['text'])
            self.assertEqual((root / 'audit/images' / f'{digest(png)}.png').read_bytes(), png)
            self.assertEqual(next(image_parts(result))[2], png)
            bridge.viewport = (1, 1)
            self.assertTrue(bridge.call('bench_read_image', {'path': '/workspace/screen.png'}, 2)['isError'])

    def test_viewer_excludes_auth_and_runtime(self):
        for path in [
            'auth.json',
            'logs/agent/auth.json',
            'config/config.toml',
            'run/codex/auth.json',
            'logs/bridge/images/../auth.json',
        ]:
            self.assertFalse(allowed(path))
        self.assertTrue(allowed('logs/bridge/images/' + 'a' * 64 + '.png'))
        self.assertTrue(allowed('logs/agent/codex-rpc.ndjson'))
