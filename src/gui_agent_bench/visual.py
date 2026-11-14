"""Screenshot references and deterministic image assertions. No UI structure is read.

The controller handles only bounded PNG bytes/manifests. Image decoding and
comparison happen in the isolated browser broker, never in submitted Python.
"""

import io
import base64
import json
import math
from pathlib import Path
import re
import struct
import time

from gui_agent_bench.io import digest, dump, regular_file, strict_json
from gui_agent_bench.failures import Failure

VERSION = 'visual-v1'
COMPARATOR = 'pixelmatch-py-0.4.0/pillow-11.3.0'
CAPTURE_CONTRACT = 'visual-observation-window-v1'
SAMPLE_FRACTIONS = (0, 0.23, 0.51, 0.77, 1)
MAX_IMAGE_BYTES = 4_000_000
MAX_REFERENCES = 64
MAX_REFERENCE_BYTES = 32_000_000
MAX_EVIDENCE_BYTES = 128_000_000
NAME = re.compile(r'[a-z][a-z0-9_-]{0,47}\Z')


def reference_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError('reference must be a short lowercase name, not a path')
    return name


def png_size(data):
    if (
        len(data) < 33
        or len(data) > MAX_IMAGE_BYTES
        or data[:8] != b'\x89PNG\r\n\x1a\n'
        or data[8:16] != b'\x00\x00\x00\rIHDR'
    ):
        raise ValueError('bounded PNG required')
    size = struct.unpack('>II', data[16:24])
    if not all(0 < n <= 4096 for n in size) or size[0] * size[1] > 4_000_000:
        raise ValueError('image dimensions exceed budget')
    return size


def rectangle(value, viewport):
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(n) is not int for n in value)
        or not 0 <= value[0] < value[2] <= viewport[0]
        or not 0 <= value[1] < value[3] <= viewport[1]
    ):
        raise ValueError('rectangle outside viewport')
    return value


def validate_image_assertion(args, viewport):
    fields = {'kind', 'reference', 'region', 'masks', 'threshold', 'max_diff_pixels', 'include_aa', 'precondition'}
    if set(args) not in (fields, fields | {'observation_window_ms'}):
        raise ValueError('unknown image assertion fields')
    window = args.get('observation_window_ms', 0)  # Exact legacy wire contract stays single-frame.
    if type(window) is not int or not 0 <= window <= 2000:
        raise ValueError('observation window must be an integer in 0..2000 ms')
    reference_name(args['reference'])
    if type(args['precondition']) is not bool or type(args['include_aa']) is not bool:
        raise ValueError('boolean assertion flags required')
    region = rectangle(args['region'], viewport) if args['region'] is not None else [0, 0, *viewport]
    if not isinstance(args['masks'], list) or len(args['masks']) > 32:
        raise ValueError('at most 32 masks allowed')
    for mask in args['masks']:
        rectangle(mask, viewport)
        if not (region[0] <= mask[0] < mask[2] <= region[2] and region[1] <= mask[1] < mask[3] <= region[3]):
            raise ValueError('mask must be inside the comparison region')
    threshold = args['threshold']
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold < 1:
        raise ValueError('threshold must be finite and in [0, 1)')
    if type(args['max_diff_pixels']) is not int or args['max_diff_pixels'] < 0:
        raise ValueError('max_diff_pixels must be a nonnegative integer')
    return region


def read_references(root, viewport=None):
    """Validate every file, including unused references; reject links and extras."""
    data = regular_file(root / 'manifest.json', root, 65536)
    manifest = strict_json(data)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {'version', 'viewport', 'references'}
        or manifest['version'] != VERSION
    ):
        raise ValueError('unsupported reference manifest')
    size = manifest['viewport']
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(n) is not int or not 0 < n <= 4096 for n in size)
        or size[0] * size[1] > 4_000_000
        or (viewport is not None and tuple(size) != tuple(viewport))
    ):
        raise ValueError('reference viewport differs')
    entries = manifest['references']
    if not isinstance(entries, dict) or len(entries) > MAX_REFERENCES:
        raise ValueError('reference count budget')
    files = {'manifest.json': data}
    for name, entry in entries.items():
        reference_name(name)
        if not isinstance(entry, dict) or set(entry) != {'file', 'sha256'} or entry['file'] != name + '.png':
            raise ValueError('invalid reference entry')
        image = regular_file(root / entry['file'], root, MAX_IMAGE_BYTES)
        if digest(image) != entry['sha256'] or png_size(image) != tuple(size):
            raise ValueError('reference bytes or dimensions changed')
        files[entry['file']] = image
    if sum(map(len, files.values())) > MAX_REFERENCE_BYTES:
        raise ValueError('reference byte budget exceeded')
    if {p.name for p in root.iterdir()} != set(files):
        raise ValueError('unexpected reference file or directory')
    return manifest, files


def reference_digest(root, viewport=None):
    _, files = read_references(root, viewport)
    return digest('\n'.join(name + ':' + digest(data) for name, data in sorted(files.items())).encode())


def seal_references(source, destination, viewport):
    """Copy bounded allowlisted files into a new immutable-for-the-agent bundle."""
    if source is None:
        destination.mkdir(parents=True, exist_ok=False)
        dump(destination / 'manifest.json', {'version': VERSION, 'viewport': list(viewport), 'references': {}})
    else:
        _, files = read_references(source, viewport)
        destination.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            (destination / name).write_bytes(data)
    return reference_digest(destination, viewport)


class ReferenceStore:
    """Author-only capture. The submitted program cannot create/replace a baseline."""

    def __init__(self, root, viewport):
        self.root, self.viewport = root, tuple(viewport)
        self.manifest = {'version': VERSION, 'viewport': list(viewport), 'references': {}}
        self.total = 0
        root.mkdir(parents=True, exist_ok=False)
        dump(root / 'manifest.json', self.manifest)

    def capture(self, name, png):
        reference_name(name)
        if name in self.manifest['references']:
            raise Failure('invalid_arguments')
        if png_size(png) != self.viewport:
            raise ValueError('capture viewport differs')
        if len(self.manifest['references']) >= MAX_REFERENCES or self.total + len(png) + 65536 > MAX_REFERENCE_BYTES:
            raise Failure('evidence_overflow')
        entry = {'file': name + '.png', 'sha256': digest(png)}
        (self.root / entry['file']).write_bytes(png)
        self.manifest['references'][name] = entry
        self.total += len(png)
        dump(self.root / 'manifest.json', self.manifest)
        return entry


class ImageAssertions:
    def __init__(self, references, evidence, viewport):
        self.manifest, self.files = read_references(references, viewport)
        self.viewport, self.evidence = tuple(viewport), evidence
        # External bundles can contain unused references too. Validate their
        # complete PNG payload in the broker before any execution is accepted.
        for entry in self.manifest['references'].values():
            self._decode(self.files[entry['file']]).close()
        evidence.mkdir(parents=True, exist_ok=False)
        self.count = 0

    def _decode(self, data):
        from PIL import Image

        if png_size(data) != self.viewport:
            raise ValueError('image viewport differs; not a behavioral failure')
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('single-frame PNG required')
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.convert('RGBA')

    def check(self, actual_png, args):
        return self._check_samples([actual_png], args)

    def observe_and_check(self, observe, args):
        # One assertion measurement, never an action/trial retry. Capture every
        # scheduled observation even if an earlier frame would match. Only
        # screenshot pixels enter comparison; no UI or fault metadata is read.
        validate_image_assertion(args, self.viewport)
        if args['reference'] not in self.manifest['references']:
            raise Failure('invalid_arguments')
        window = args.get('observation_window_ms', 0)
        started = time.monotonic()
        samples, elapsed = [], []
        try:
            for fraction in SAMPLE_FRACTIONS if window else (0,):
                pause = started + fraction * window / 1000 - time.monotonic()
                if pause > 0:
                    time.sleep(pause)
                # An observation error is fatal; never sample again to conceal it.
                samples.append(observe())
                elapsed.append(round((time.monotonic() - started) * 1000))
            return self._check_samples(samples, args, elapsed)
        except Exception:
            # Preserve already obtained frames even when a later observation or
            # comparison fails. Partial measurements cannot qualify for credit.
            failed = getattr(self, 'failed_measurements', 0) + 1
            self.failed_measurements = failed
            folder = self.evidence / f'failed-{failed:04d}'
            folder.mkdir()
            retained = []
            for index, png in enumerate(samples):
                if len(png) > MAX_IMAGE_BYTES:
                    raise Failure('evidence_overflow') from None
                name = f'sample-{index + 1:04d}.png'
                (folder / name).write_bytes(png)
                retained.append({'file': name, 'sha256': digest(png), 'elapsed_ms': elapsed[index]})
            dump(
                folder / 'result.json',
                {'capture_contract': CAPTURE_CONTRACT, 'status': 'failed', 'assertion': args, 'observations': retained},
            )
            raise

    def _check_samples(self, samples, args, elapsed=None):
        from PIL import Image, ImageDraw
        from pixelmatch.contrib.PIL import pixelmatch

        region = validate_image_assertion(args, self.viewport)
        entry = self.manifest['references'].get(args['reference'])
        if entry is None:
            raise Failure('invalid_arguments')
        expected_png = self.files[entry['file']]
        images = []
        for data in (expected_png, *samples):
            with self._decode(data) as image:
                images.append(image.crop(region))
        expected, actuals = images[0], images[1:]
        mask_bitmap = Image.new('1', expected.size)
        for mask in args['masks']:
            box = (mask[0] - region[0], mask[1] - region[1], mask[2] - region[0] - 1, mask[3] - region[1] - 1)
            ImageDraw.Draw(mask_bitmap).rectangle(box, fill=1)
        compared = expected.width * expected.height - sum(mask_bitmap.getdata())
        if compared <= args['max_diff_pixels']:
            raise ValueError('assertion must check unmasked pixels beyond its mismatch allowance')
        # Mask both images identically, and exclude the masked area from the budget.
        for image in images:
            image.paste((0, 0, 0, 255), mask=mask_bitmap)
        comparisons = []
        for actual in actuals:
            diff = Image.new('RGBA', expected.size)
            mismatches = pixelmatch(expected, actual, diff, threshold=args['threshold'], includeAA=args['include_aa'])
            comparisons.append((mismatches, actual, diff))
        selected = min(range(len(comparisons)), key=lambda index: comparisons[index][0])
        mismatches, actual, diff = comparisons[selected]
        actual_png = samples[selected]
        self.count += 1
        folder = self.evidence / f'{self.count:04d}'
        folder.mkdir()
        (folder / 'capture.png').write_bytes(actual_png)
        hashes = {'capture.png': digest(actual_png)}
        observations = []
        if elapsed is not None:
            for index, png in enumerate(samples):
                name = f'sample-{index + 1:04d}.png'
                (folder / name).write_bytes(png)
                hashes[name] = digest(png)
                observations.append(
                    {
                        'file': name,
                        'sha256': hashes[name],
                        'elapsed_ms': elapsed[index],
                        'different_pixels': comparisons[index][0],
                    }
                )
        for name, image in [('expected', expected), ('actual', actual), ('diff', diff)]:
            path = folder / (name + '.png')
            image.save(path, format='PNG')
            hashes[path.name] = digest(path.read_bytes())
        report = {
            'comparator': COMPARATOR,
            'reference_sha256': entry['sha256'],
            'actual_sha256': digest(actual_png),
            'compared_pixels': compared,
            'different_pixels': mismatches,
            'matched': mismatches <= args['max_diff_pixels'],
            'evidence': {'directory': folder.name, 'sha256': hashes},
        }
        if elapsed is not None:
            report.update(
                capture_contract=CAPTURE_CONTRACT,
                observation_window_ms=args.get('observation_window_ms', 0),
                selected_sample=selected,
                observations=observations,
            )
        dump(folder / 'result.json', {'assertion': args, **report})
        return report


def audit_images(root, records, manifest):
    """Replay evidence integrity against the trusted broker's assertion ledger."""
    checks = [record for record in records if record.get('assertion', {}).get('kind') == 'image']
    expected_dirs = {f'{index:04d}' for index in range(1, len(checks) + 1)}
    # Git does not keep empty folders, so a cloned run without image checks has no evidence folder.
    present = {p.name for p in root.iterdir()} if root.is_dir() else set()
    if present != expected_dirs:
        raise ValueError('image assertion evidence is incomplete')
    for index, record in enumerate(checks, 1):
        report = record['image']
        folder = root / f'{index:04d}'
        saved = strict_json(regular_file(folder / 'result.json', root, 65536))
        if saved != {'assertion': record['assertion'], **report} or record['matched'] != report['matched']:
            raise ValueError('image evidence differs from ledger')
        entry = manifest['references'][record['assertion']['reference']]
        if report['comparator'] != COMPARATOR or report['reference_sha256'] != entry['sha256']:
            raise ValueError('image comparison version/reference differs')
        files = report['evidence']['sha256']
        required = {'expected.png', 'actual.png', 'diff.png', 'capture.png'}
        if 'capture_contract' in report:
            window = record['assertion'].get('observation_window_ms', 0)
            samples = report.get('observations', [])
            count = len(SAMPLE_FRACTIONS) if window else 1
            selected = report.get('selected_sample')
            if (
                report['capture_contract'] != CAPTURE_CONTRACT
                or report['observation_window_ms'] != window
                or len(samples) != count
                or type(selected) is not int
                or not 0 <= selected < count
            ):
                raise ValueError('invalid observation window evidence')
            required |= {f'sample-{i + 1:04d}.png' for i in range(count)}
            times = []
            for i, sample in enumerate(samples):
                name = f'sample-{i + 1:04d}.png'
                if (
                    set(sample) != {'file', 'sha256', 'elapsed_ms', 'different_pixels'}
                    or sample['file'] != name
                    or sample['sha256'] != files.get(name)
                    or type(sample['elapsed_ms']) is not int
                    or sample['elapsed_ms'] < 0
                    or type(sample['different_pixels']) is not int
                    or sample['different_pixels'] < 0
                ):
                    raise ValueError('invalid observation sample')
                times.append(sample['elapsed_ms'])
            if (
                times != sorted(times)
                or times[-1] < window
                or files.get('capture.png') != samples[selected]['sha256']
                or report['different_pixels'] != min(x['different_pixels'] for x in samples)
                or samples[selected]['different_pixels'] != report['different_pixels']
            ):
                raise ValueError('observation selection differs')
        if set(files) != required or report['evidence']['directory'] != folder.name:
            raise ValueError('invalid image evidence manifest')
        if {p.name for p in folder.iterdir()} != set(files) | {'result.json'}:
            raise ValueError('unexpected comparison artifact')
        for name, sha in files.items():
            if digest(regular_file(folder / name, root, MAX_IMAGE_BYTES)) != sha:
                raise ValueError('image evidence was modified')
        if files['capture.png'] != report['actual_sha256']:
            raise ValueError('captured image hash differs')


def _export_name(name, kind):
    if kind == 'references':
        return name == 'manifest.json' or bool(re.fullmatch(r'[a-z][a-z0-9_-]{0,47}\.png', name))
    return bool(
        re.fullmatch(
            r'00(?:0[1-9]|[1-7][0-9]|80)/(?:expected|actual|diff|capture|sample-000[1-5])\.png|(?:failed-)?00(?:0[1-9]|[1-7][0-9]|80)/result\.json|failed-00(?:0[1-9]|[1-7][0-9]|80)/sample-000[1-5]\.png',
            name,
        )
    )


def export_files(kind):
    """Bounded export from broker tmpfs; Docker cp cannot read tmpfs reliably."""
    root = Path('/tmp/references' if kind == 'references' else '/tmp/image-assertions')
    limit = MAX_REFERENCE_BYTES if kind == 'references' else MAX_EVIDENCE_BYTES
    files, total = {}, 0
    for path in sorted(root.rglob('*')):
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix()
        if not _export_name(name, kind):
            raise ValueError('unexpected evidence path')
        data = regular_file(path, root, MAX_IMAGE_BYTES)
        total += len(data)
        if total > limit:
            raise ValueError('evidence byte budget exceeded')
        files[name] = base64.b64encode(data).decode('ascii')
    return files


def collect_files(container, destination, kind):
    """Controller-only bounded transfer. No submitted code executes here."""
    import subprocess

    if kind not in {'references', 'image-assertions'}:
        raise ValueError('unknown visual evidence kind')
    process = subprocess.run(
        ['docker', 'exec', container, 'python', '-m', 'gui_agent_bench.visual', kind],
        capture_output=True,
        timeout=60,
        check=True,
    )
    limit = MAX_REFERENCE_BYTES if kind == 'references' else MAX_EVIDENCE_BYTES
    if len(process.stdout) > limit * 4 // 3 + 65536:
        raise ValueError('export exceeds evidence budget')
    files = strict_json(process.stdout)
    if not isinstance(files, dict) or len(files) > (MAX_REFERENCES + 1 if kind == 'references' else 800):
        raise ValueError('invalid visual evidence export')
    destination.mkdir(parents=True, exist_ok=False)
    total = 0
    for name, encoded in files.items():
        if not _export_name(name, kind) or not isinstance(encoded, str):
            raise ValueError('invalid evidence path or encoding')
        data = base64.b64decode(encoded, validate=True)
        total += len(data)
        if len(data) > MAX_IMAGE_BYTES or total > limit:
            raise ValueError('evidence byte budget exceeded')
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['references', 'image-assertions'])
    print(json.dumps(export_files(parser.parse_args().kind)))
