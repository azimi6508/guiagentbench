"""Pinned, agent-only exception for the nested Codex Linux sandbox."""

import hashlib
import json
from pathlib import Path
import platform


ROOT = Path(__file__).resolve().parents[3]


def policy(root=ROOT):
    folder = root / 'runtime/codex/security'
    metadata = json.loads((folder / 'policy.json').read_text())
    if metadata.get('schema') != 'codex-container-policy-v1' or metadata.get('scope') != 'agent only':
        raise ValueError('Codex container policy metadata differs')
    expected = {'docker-default-seccomp.json', 'seccomp.json', 'apparmor.profile'}
    if set(metadata.get('files', {})) != expected:
        raise ValueError('Codex container policy manifest differs')
    for name, sha in metadata['files'].items():
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != sha:
            raise ValueError('Codex container policy content differs')
    text = (folder / 'apparmor.profile').read_text()
    name = metadata['apparmor_profile']
    template = text.replace(name, '@PROFILE@')
    if name != 'gab-codex-bwrap-' + hashlib.sha256(template.encode()).hexdigest()[:16]:
        raise ValueError('Codex AppArmor identity differs')
    return metadata


def options(root=ROOT):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Codex container policy requires Linux x86_64')
    metadata = policy(root)
    return [
        '--security-opt',
        'seccomp=' + str((root / 'runtime/codex/security/seccomp.json').resolve()),
        '--security-opt',
        'apparmor=' + metadata['apparmor_profile'],
    ]


def audit(item, role, root=ROOT):
    """Docker inspect embeds the selected seccomp JSON, not its input filename."""
    values = item['HostConfig'].get('SecurityOpt') or []
    if role != 'agent':
        if values != ['no-new-privileges'] or item.get('AppArmorProfile') != 'docker-default':
            raise ValueError('Codex helper container security policy differs')
        return
    metadata = policy(root)
    expected_name = metadata['apparmor_profile']
    if len(values) != 3 or values.count('no-new-privileges') != 1:
        raise ValueError('Codex agent security options differ')
    if values.count('apparmor=' + expected_name) != 1 or item.get('AppArmorProfile') != expected_name:
        raise ValueError('Codex agent AppArmor profile differs')
    selected = [v.removeprefix('seccomp=') for v in values if v.startswith('seccomp=')]
    expected = json.loads((root / 'runtime/codex/security/seccomp.json').read_text())
    if len(selected) != 1:
        raise ValueError('Codex agent seccomp profile missing')
    try:
        actual = json.loads(selected[0])
    except ValueError as exc:
        raise ValueError('Codex agent seccomp profile invalid') from exc
    if actual != expected:
        raise ValueError('Codex agent seccomp profile differs')
