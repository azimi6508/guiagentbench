"""Build a public arm workspace from explicit files, never a canonical-tree copy."""

import fnmatch
import json
from pathlib import Path
import tomllib

from gui_agent_bench.io import digest, regular_file, strict_json
from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.failures import Failure
from gui_agent_bench.coordinates import PIXEL_COORDINATES, coordinate_instructions


def materialize(
    root: Path, task: Path, evidence: Path, destination: Path, arm: str, platform='web', *, viewport=None
) -> dict:
    if arm not in ARM_IDS:
        raise ValueError('arm is not implemented')
    if destination.exists():
        raise ValueError('workspace must be new for every trial')
    policy = tomllib.loads(regular_file(root / f'configs/arms/{arm}.toml', root).decode())
    if platform == 'tv':
        from gui_agent_bench.tv import TV_ARMS

        if arm not in TV_ARMS:
            raise ValueError('TV UI arms are unavailable')
    overlay = (
        regular_file(root / 'configs/tv-generated-api.md', root)
        if platform == 'tv' and arm.startswith(('test_', 'oracle_'))
        else (
            regular_file(root / 'configs/test-api.md', root)
            if arm.startswith('test_')
            else (
                regular_file(root / 'configs/oracle-api.md', root)
                if arm.startswith('oracle_')
                else regular_file(task / f'arms/{arm}.md', task)
            )
        )
    )
    content = {'instruction.md': regular_file(task / 'instruction.md', task) + b'\n\n' + overlay}
    if arm.startswith('judge_'):
        content['instruction.md'] += (
            b'\n\nJudgment output contract: write a JSON object to /workspace/output/judgment.json.\n'
            b'Use exactly {"verdict":"PASS"} or {"verdict":"FAIL"}, with uppercase verdict values.\n'
            b'An optional "reason" string may contain at most 2000 characters. No other keys,\n'
            b'Markdown fences or surrounding text are permitted; the file must not exceed 16384 bytes.\n'
        )
    if platform == 'tv' and arm.startswith(('test_', 'oracle_')):
        entry = 'test' if arm.startswith('test_') else 'check'
        filename = 'test.py' if entry == 'test' else 'oracle.py'
        content['instruction.md'] += f'\nSave /workspace/output/{filename} with def {entry}(page).\n'.encode()
        content['instruction.md'] += (
            b'This is a full test: start from home, choose and perform your own journey. No steps are supplied.\n'
            if entry == 'test'
            else b'This is an oracle: the supplied steps have already reached the final checkpoint. Execution permits observations and assertions only. gui_reset restores that checkpoint during authoring.\n'
        )
    if arm.startswith(('oracle_', 'test_')):
        content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/visual-api.md', root)
        if arm.endswith('_ui'):
            content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/ui-api.md', root)
    if arm != 'judge_visual':
        geometry = coordinate_instructions(viewport, platform) if viewport is not None else PIXEL_COORDINATES
        content['instruction.md'] += ('\n\n' + geometry).encode()
        content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/failure-api.md', root)
        content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/environment-api.md', root)
    if platform not in {'web', 'mobile', 'tv'}:
        raise ValueError('unsupported platform')
    if platform == 'tv' and arm != 'judge_visual':
        content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/tv-api.md', root)
    if platform == 'mobile' and arm != 'judge_visual':
        content['instruction.md'] += b'\n\n' + regular_file(root / 'configs/mobile-api.md', root)
    # Deliver the required artifact before the app goal in every harness. This
    # is public arm information, not a task solution or a grading result.
    from gui_agent_bench.arms import artifact_name

    artifact = artifact_name(arm)
    entry = (
        'Produce a PASS/FAIL judgment JSON file.'
        if arm.startswith('judge_')
        else (
            'Produce a Python oracle with def check(page).'
            if arm.startswith('oracle_')
            else 'Produce a complete Python test with def test(page).'
        )
    )
    summary = (
        f'Evaluation arm: {arm}. {entry}\n'
        f'Required artifact: /workspace/output/{artifact}. Save it before finishing.\n'
        'Read the complete contract below. A final chat message does not submit an artifact.\n\n'
    )
    content['instruction.md'] = summary.encode() + content['instruction.md']
    if arm == 'judge_test':
        content['test_source.py'] = regular_file(task / 'private/test_source.py', task)
    elif arm.startswith('oracle_'):
        content['steps.json'] = regular_file(evidence / 'steps.json', evidence)
        if not isinstance(strict_json(content['steps.json']), list):
            raise ValueError('invalid steps')
    elif arm == 'judge_visual':
        metadata = tomllib.loads(regular_file(task / 'task.toml', task).decode())['metadata']
        expected = metadata.get('checkpoints', 3)
        content.update(visual_content(evidence, expected))
    # Complete evidence is admitted; never silently truncate it.
    if sum(map(len, content.values())) > 2_000_000:
        raise Failure('evidence_overflow')
    hashes = {}
    for relative, data in content.items():
        virtual = '/workspace/' + relative
        if not any(fnmatch.fnmatchcase(virtual, rule) for rule in policy['files']['read']):
            raise ValueError('materializer attempted a non-allowlisted file')
        path = destination / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[relative] = digest(data)
    (destination / 'output').mkdir()
    return {'arm': arm, 'platform': platform, 'files': hashes, 'total_bytes': sum(map(len, content.values()))}


def visual_content(evidence: Path, expected=3) -> dict:
    manifest = strict_json(regular_file(evidence / 'manifest.json', evidence))
    if (
        type(expected) is not int
        or not 3 <= expected <= 81
        or set(manifest) != {'frames'}
        or len(manifest['frames']) != expected
    ):
        raise ValueError('incomplete or unrecognized smoke evidence manifest')
    content = {
        'steps.json': regular_file(evidence / 'steps.json', evidence),
        'evidence/manifest.json': json.dumps(manifest, indent=2).encode(),
    }
    for index, frame in enumerate(manifest['frames'], 1):
        relative = f'screenshots/{index:04d}.png'
        if set(frame) != {'path', 'sha256', 'index'} or frame['path'] != relative or frame['index'] != index:
            raise ValueError('evidence frame path/order/metadata is invalid')
        data = regular_file(evidence / relative, evidence)
        if not data.startswith(b'\x89PNG\r\n\x1a\n') or digest(data) != frame['sha256']:
            raise ValueError('evidence image hash/type mismatch')
        content['evidence/' + relative] = data
    if not isinstance(strict_json(content['steps.json']), list) or len(strict_json(content['steps.json'])) != expected:
        raise ValueError('invalid step sequence')
    return content


def validate_workspace(workspace: Path, manifest: dict) -> None:
    actual = set()
    for path in workspace.rglob('*'):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(workspace).as_posix()
            actual.add(relative)
            data = regular_file(path, workspace)
            if relative not in manifest['files'] or digest(data) != manifest['files'][relative]:
                raise ValueError('unexpected or modified public workspace file')
    if actual != set(manifest['files']):
        raise ValueError('incomplete public workspace')
