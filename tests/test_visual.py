"""Behavioral image comparisons and reference-boundary regression checks."""

import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.visual import (
    ReferenceStore,
    ImageAssertions,
    audit_images,
    read_references,
    reference_digest,
    seal_references,
    validate_image_assertion,
)
from gui_agent_bench.oracle_broker import validate_assertion, tools_for
from gui_agent_bench.oracle_api import Page


def png(color='white', size=(100, 80), box=None):
    image = Image.new('RGB', size, color)
    if box:
        ImageDraw.Draw(image).rectangle(box, fill='black')
    out = io.BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


def assertion(**overrides):
    return {
        'kind': 'image',
        'reference': 'saved',
        'region': None,
        'masks': [],
        'threshold': 0.1,
        'max_diff_pixels': 0,
        'include_aa': False,
        'precondition': False,
        **overrides,
    }


class VisualRegression(unittest.TestCase):
    def test_matches_pixels_and_detects_local_change_with_inspectable_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ReferenceStore(root / 'references', (100, 80))
            store.capture('saved', png())
            images = ImageAssertions(root / 'references', root / 'evidence', (100, 80))
            records = []
            for actual, expected in [(png(), True), (png(box=(20, 20, 29, 29)), False)]:
                result = images.check(actual, assertion(include_aa=True))
                self.assertEqual(result['matched'], expected)
                self.assertEqual(result['different_pixels'], 0 if expected else 100)
                records.append({'assertion': assertion(include_aa=True), 'matched': expected, 'image': result})
            audit_images(root / 'evidence', records, store.manifest)
            (root / 'evidence/0002/diff.png').write_bytes(png('red'))
            with self.assertRaises(ValueError):
                audit_images(root / 'evidence', records, store.manifest)

    def test_cloned_run_without_image_checks_has_no_evidence_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ReferenceStore(root / 'references', (100, 80))
            store.capture('saved', png())
            audit_images(root / 'absent', [], store.manifest)
            images = ImageAssertions(root / 'references', root / 'evidence', (100, 80))
            result = images.check(png(), assertion())
            records = [{'assertion': assertion(), 'matched': True, 'image': result}]
            with self.assertRaises(ValueError):
                audit_images(root / 'absent', records, store.manifest)

    def test_model_chosen_crop_mask_and_tolerance_control_comparison(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ReferenceStore(root / 'references', (100, 80)).capture('saved', png())
            images = ImageAssertions(root / 'references', root / 'evidence', (100, 80))
            changed = png(box=(20, 20, 29, 29))
            for options in [
                dict(region=[50, 40, 100, 80]),
                dict(masks=[[20, 20, 30, 30]]),
                dict(max_diff_pixels=100, include_aa=True),
            ]:
                self.assertTrue(images.check(changed, assertion(**options))['matched'])
            self.assertFalse(images.check(changed, assertion(max_diff_pixels=99, include_aa=True))['matched'])
            with self.assertRaises(ValueError):
                images.check(png(size=(99, 80)), assertion())
            # An unknown reference is an invalid operation, never a detected bug.
            with self.assertRaises(ValueError):
                images.check(changed, assertion(reference='missing'))

    def test_no_vacuous_masks_or_budgets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ReferenceStore(root / 'references', (100, 80)).capture('saved', png())
            images = ImageAssertions(root / 'references', root / 'evidence', (100, 80))
            for options in [
                dict(masks=[[0, 0, 100, 80]]),
                dict(max_diff_pixels=8000),
                dict(masks=[[0, 0, 50, 80], [25, 0, 100, 80]]),
            ]:
                with self.assertRaises(ValueError):
                    images.check(png(), assertion(**options))
            result = images.check(png(), assertion(masks=[[0, 0, 50, 80], [25, 0, 75, 80]]))
            self.assertEqual(result['compared_pixels'], 2000)

    def test_reference_manifest_is_immutable_allowlisted_and_sealed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ReferenceStore(root / 'references', (100, 80))
            store.capture('saved', png())
            with self.assertRaises(ValueError):
                store.capture('saved', png('red'))
            for name in ['../secret', '/private/file', 'UPPER', 'file.png', 'x' * 49]:
                with self.assertRaises(ValueError):
                    store.capture(name, png())
            sha = seal_references(root / 'references', root / 'sealed', (100, 80))
            self.assertEqual(sha, reference_digest(root / 'references'))
            (root / 'references/saved.png').write_bytes(png('red'))
            with self.assertRaises(ValueError):
                read_references(root / 'references')
            self.assertEqual(reference_digest(root / 'sealed'), sha)
            (root / 'sealed/extra').mkdir()
            with self.assertRaises(ValueError):
                reference_digest(root / 'sealed')

    def test_rejects_traversal_wrong_viewport_and_symlink_bundles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ReferenceStore(root / 'references', (100, 80))
            store.capture('saved', png())
            with self.assertRaises(ValueError):
                seal_references(root / 'references', root / 'other', (99, 80))
            original = copy.deepcopy(store.manifest)
            store.manifest['references']['saved']['file'] = '../outside.png'
            (root / 'references/manifest.json').write_text(json.dumps(store.manifest))
            with self.assertRaises(ValueError):
                read_references(root / 'references')
            (root / 'references/manifest.json').write_text(json.dumps(original))
            try:
                (root / 'link').symlink_to(root / 'references', target_is_directory=True)
            except OSError:
                return  # Windows may not allow unprivileged symlink creation.
            with self.assertRaises(ValueError):
                read_references(root / 'link')

    def test_strict_parameters_and_removed_text_api(self):
        self.assertFalse(hasattr(Page, 'expect_text'))
        for arm in ('oracle_visual', 'test_visual', 'oracle_ui', 'test_ui'):
            validate_assertion(assertion(), arm, (100, 80))
            with self.assertRaises(ValueError):
                validate_assertion({'kind': 'pixels_text', 'precondition': False}, arm, (100, 80))
            observe = next(t for t in tools_for(arm) if t['name'] == 'observe')
            self.assertIn('reference', observe['inputSchema']['properties'])
        for options in [
            dict(threshold=float('nan')),
            dict(threshold=1),
            dict(threshold=True),
            dict(max_diff_pixels=True),
            dict(region=[0, 0, 101, 80]),
            dict(masks=[[0, 0, 100, 80]], region=[0, 0, 50, 50]),
            dict(reference='../saved'),
            dict(include_aa=1),
            dict(region=[0, 0, 0, 5]),
        ]:
            with self.assertRaises(ValueError):
                validate_image_assertion(assertion(**options), (100, 80))

    def test_native_screenshot_dimensions_and_region(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shot = png(size=(720, 1280))
            ReferenceStore(root / 'references', (720, 1280)).capture('saved', shot)
            images = ImageAssertions(root / 'references', root / 'evidence', (720, 1280))
            self.assertTrue(images.check(shot, assertion(region=[85, 875, 430, 960]))['matched'])

    def test_malformed_unused_reference_fails_before_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ReferenceStore(root / 'references', (100, 80))
            store.capture('saved', png())
            # Intact dimensions and manifest hash are insufficient: the payload
            # must be decodable even when the submission never uses this name.
            store.capture('unused', png()[:40])
            with self.assertRaises((ValueError, OSError, SyntaxError)):
                ImageAssertions(root / 'references', root / 'evidence', (100, 80))


if __name__ == '__main__':
    unittest.main()
