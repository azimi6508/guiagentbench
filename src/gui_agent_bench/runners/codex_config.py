"""Reviewed Codex configuration and source identities, with no secret fields."""

import hashlib
import json
import tomllib

from gui_agent_bench.codex_bridge import catalog
from gui_agent_bench.io import dump, digest
from .registry import fingerprint

VERSION = '0.162.0'
CONTRACT = 'codex-runner-v1'
IMAGES = {
    'agent': 'gui-agent-bench-public-codex:0.162.0-bench1',
    'bridge': 'gui-agent-bench-public-codex-bridge:1',
    'egress': 'gui-agent-bench-public-codex-egress:1',
}
MODEL_CATALOG_DIR = 'configs/codex/models'
# Every operator-supplied model catalog must keep Codex on the benchmark's MCP
# tools: direct tool calls, no sub-agents, search, apply_patch or experiments.
RESTRICTED_MODEL_FIELDS = {
    'tool_mode': 'direct',
    'multi_agent_version': None,
    'apply_patch_tool_type': None,
    'supports_search_tool': False,
    'use_responses_lite': False,
    'experimental_supported_tools': [],
}


def model_catalog(root, model):
    """Return the local catalog bytes for one model, or None when none is supplied.

    Catalogs are provider metadata and are not distributed; see the README in
    MODEL_CATALOG_DIR. A supplied catalog must describe exactly this model with
    the restricted tool fields above.
    """
    path = root / MODEL_CATALOG_DIR / (model + '.json')
    if not path.is_file():
        return None
    data = path.read_bytes()
    models = json.loads(data).get('models')
    if (
        not isinstance(models, list)
        or len(models) != 1
        or not isinstance(models[0], dict)
        or models[0].get('slug') != model
        or any(models[0].get(key, object()) != value for key, value in RESTRICTED_MODEL_FIELDS.items())
    ):
        raise ValueError('Codex model catalog must describe only this model with the restricted tool fields')
    return data


def qualification_path(root, spec):
    # The default profile has a fixed certificate path; other identities are hashed.
    if spec.model == 'gpt-6.1-sol':
        return root / 'runtime/codex/qualification.json'
    identity = fingerprint([spec.model, spec.reasoning_effort])
    return root / 'runtime/codex/qualifications' / (identity + '.json')


def schema_digest(root):
    folder = root / 'configs/codex/schema' / VERSION
    result = hashlib.sha256()
    for path in sorted(folder.rglob('*.json'), key=lambda p: p.relative_to(folder).as_posix()):
        result.update(
            path.relative_to(folder).as_posix().encode() + b'\0' + hashlib.sha256(path.read_bytes()).digest() + b'\n'
        )
    return result.hexdigest()


def validate_lock(root):
    lock = json.loads((root / 'runtime/codex/lock.json').read_text())
    if lock['version'] != VERSION or schema_digest(root) != lock['schema_sha256']:
        raise ValueError('Codex protocol lock differs')
    for name, sha in lock['files'].items():
        if digest((root / name).read_bytes()) != sha:
            raise ValueError('Codex runtime source lock differs')
    return lock


def render(root, directory, spec, arm, platform_name, profile='generic'):
    text = (root / 'configs/codex/base.toml').read_text()
    text = text.replace('model = "gpt-6.1-sol"', 'model = ' + json.dumps(spec.model))
    text = text.replace(
        'model_reasoning_effort = "medium"', 'model_reasoning_effort = ' + json.dumps(spec.reasoning_effort)
    )
    text = text[: text.index('# Generate exact per-arm names;')]
    tools = catalog(arm, platform_name, profile)
    names = [tool['name'] for tool in tools]
    text += 'enabled_tools = ' + json.dumps(names) + '\n'
    for name in names:
        text += f'\n[mcp_servers.bench.tools.{name}]\napproval_mode = "approve"\noutput_token_limit = 262144\n'
    directory.mkdir(parents=True, exist_ok=True)
    data = model_catalog(root, spec.model)
    if data is not None:
        (directory / 'model-catalog.json').write_bytes(data)
        text = 'model_catalog_json = "/config/model-catalog.json"\n' + text
    (directory / 'config.toml').write_text(text)
    dump(directory / 'tools.json', ['mcp__bench__' + name for name in names])
    return tomllib.loads(text)


def resolved(root, specs, cells, images, timeout):
    lock = validate_lock(root)
    from gui_agent_bench.budgets import codex_budget

    task_hashes = {}
    for cell in cells:
        folder = root / 'tasks' / cell['task']
        task_hashes[cell['task']] = {
            p.relative_to(folder).as_posix(): digest(p.read_bytes())
            for p in sorted(folder.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts
        }
    value = dict(
        schema='resolved-plan-v1',
        agents=[s.record() for s in specs],
        memberships=[{k: c[k] for k in ('task', 'arm', 'model', 'repeat') if k in c} for c in cells],
        images=images,
        runtime_lock=fingerprint(lock),
        task_hashes=task_hashes,
        policies={a: digest((root / f'configs/arms/{a}.toml').read_bytes()) for a in {c['arm'] for c in cells}},
        budgets={a: codex_budget(a, timeout) for a in {c['arm'] for c in cells}},
        model_catalogs={
            s.model: (digest(c) if (c := model_catalog(root, s.model)) is not None else None) for s in specs
        },
        runner_version=VERSION,
        protocol_contract=CONTRACT,
        billing_mode='chatgpt_subscription',
        automatic_trial_retries=False,
        automatic_fallback=False,
    )
    return value
