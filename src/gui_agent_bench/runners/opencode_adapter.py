"""Existing OpenCode authoring, kept separate from Codex authentication/transport."""

import json
from gui_agent_bench.audit import audit_agent
from gui_agent_bench.docker import AGENT_IMAGE, WORKER_IMAGE, docker, inspect, isolation, mount, provider_environment
from gui_agent_bench.io import dump
from gui_agent_bench.runners.opencode import configuration, run as run_agent
from gui_agent_bench.failures import Failure


def author(root, context, model, fixture_verdict, fixture_probe, oracle_control, create, start, variant=None):
    directory = context.public_workspace.parent
    workspace, output, config_dir = context.public_workspace, context.output_directory, context.config_directory
    manifest, arm, timeout = context.workspace_manifest, context.arm, context.timeout_seconds
    app_runtime = {'platform': context.platform}
    prefix, agent_net = 'gab-' + context.trial_id, context.gui_network
    provider_name, model_id = model.split('/', 1)
    config = configuration(root, config_dir / 'opencode.json', 'relay', model_id, arm, app_runtime['platform'], variant)
    selected = ['--variant', variant] if variant is not None else []
    effective = json.loads(
        docker(
            'run',
            '--rm',
            '--network',
            'none',
            *isolation(),
            *mount(workspace, '/workspace'),
            *mount(config_dir, '/config'),
            AGENT_IMAGE,
            'debug',
            'config',
        )
    )
    if (
        effective.get('permission') != config['permission']
        or effective.get('plugin')
        or effective.get('agent', {}).get('bench', {}).get('permission')
        or effective.get('compaction') != config['compaction']
    ):
        raise ValueError('effective OpenCode settings differ from the admitted profile')
    dump(directory / 'effective-config.json', effective)
    provider_args = ['--network', agent_net, '--network-alias', 'provider', *isolation(memory='512m')]
    if provider_name == 'openrouter':
        provider_args += ['--env', 'OPENROUTER_API_KEY']
    fixture_args = []
    if provider_name == 'fixture' and context.fixture_record is not None:
        control_path = directory / 'fixture-control.json'
        dump(control_path, context.fixture_record)
        provider_args += mount(control_path, '/fixture-control.json')
        fixture_args = ['--fixture-config', '/fixture-control.json']
    gateway = create(
        prefix + '-provider',
        *provider_args,
        WORKER_IMAGE,
        '_gateway',
        '--provider',
        provider_name,
        '--model',
        model_id,
        '--fixture-verdict',
        fixture_verdict,
        '--arm',
        arm,
        '--fixture-oracle',
        oracle_control,
        '--platform',
        app_runtime['platform'],
        *(['--fixture-probe'] if fixture_probe else []),
        *fixture_args,
        *(['--reasoning-effort', variant] if variant is not None else []),
        env=provider_environment(),
    )
    if provider_name == 'openrouter':
        docker('network', 'connect', 'bridge', gateway)
    start(gateway)
    if fixture_args:
        from gui_agent_bench.audit import audit_fixture_provider

        details = inspect(gateway)
        dump(directory / 'fixture-provider-container.json', details)
        audit_fixture_provider(details, directory, agent_net)
    agent = create(
        prefix + '-agent',
        '--network',
        agent_net,
        *isolation(),
        *mount(workspace, '/workspace'),
        *mount(output, '/workspace/output', writable=True),
        *mount(config_dir, '/config'),
        AGENT_IMAGE,
        'run',
        '--print-logs',
        '--log-level',
        'DEBUG',
        '--format',
        'json',
        '--model',
        'relay/' + model_id,
        '--agent',
        'bench',
        *selected,
        'This is an unattended evaluation. Complete /workspace/instruction.md independently. '
        'All permitted evidence is already available; choose what to inspect. '
        'No follow-up user response will arrive. Save the requested submission.',
    )
    details = inspect(agent)
    network = json.loads(docker('network', 'inspect', agent_net))[0]
    dump(directory / 'agent-network.json', network)
    audit = audit_agent(details, workspace, manifest, config, network)
    dump(directory / 'isolation.json', audit)
    dump(directory / 'agent-container.json', details)
    summary = run_agent(agent, directory / 'logs/agent', timeout)
    provider_records = [json.loads(line) for line in docker('logs', gateway).splitlines()]
    if any(record.get('capability_error') for record in provider_records) or not any(
        record.get('capabilities_verified') for record in provider_records
    ):
        raise Failure('capability_unavailable')
    return summary
