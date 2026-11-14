#!/usr/bin/env python3
"""Real pinned client with a credential-free, network-none Responses fixture."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def control(
    output,
    model,
    arm='judge_visual',
    platform='web',
    scenario='happy',
    model_catalog=None,
    profile='generic',
    reasoning_effort='medium',
):
    from PIL import Image
    from gui_agent_bench.budgets import codex_budget
    from gui_agent_bench.codex_audit import reconcile
    from gui_agent_bench.codex_bridge import catalog
    from gui_agent_bench.docker import client_environment, docker, isolation, mount
    from gui_agent_bench.io import digest
    from gui_agent_bench.runners.codex_config import IMAGES, render
    from gui_agent_bench.runners.codex_protocol import Driver
    from gui_agent_bench.runners.codex_security import options, policy
    from gui_agent_bench.runners.registry import resolve

    name = 'gab-codex-client-' + uuid.uuid4().hex[:12]
    output.mkdir(parents=True, exist_ok=False)
    containers = []
    driver = process = None
    report = dict(
        schema='codex-client-control-v1',
        status='failed',
        model=model,
        arm=arm,
        platform=platform,
        environment_profile=profile,
        container_policy=policy(),
        real_inference_started=False,
        synthetic_provider=True,
        scenario=scenario,
        controls=[],
    )
    with tempfile.TemporaryDirectory(prefix='gab-client-control-') as temp:
        root = Path(temp)
        for sub in ['workspace', 'workspace/output', 'output', 'policy', 'config', 'ipc', 'fixture']:
            (root / sub).mkdir()
        for sub in ['agent', 'bridge', 'provider']:
            (output / sub).mkdir()
        content = 'fixture public text 🧑🏽‍💻 e\u0301\n' + ('x' * 7500)
        (root / 'workspace/instruction.md').write_text(content)
        image = io.BytesIO()
        Image.new('RGB', (960, 640), 'purple').save(image, format='PNG')
        (root / 'workspace/screen.png').write_bytes(image.getvalue())
        manifest = dict(
            arm=arm,
            platform=platform,
            files={'instruction.md': digest(content.encode()), 'screen.png': digest(image.getvalue())},
        )
        (root / 'policy/bridge.json').write_text(
            json.dumps(
                dict(arm=arm, platform=platform, viewport=[960, 640], manifest=manifest, environment_profile=profile)
            )
        )
        spec = resolve('codex/' + model, reasoning_effort=reasoning_effort)
        render(ROOT, root / 'config', spec, arm, platform, profile)
        if model_catalog:
            # Explicit test-only candidate; production does not expose this knob.
            data = Path(model_catalog).read_bytes()
            selected = json.loads(data)['models']
            if len(selected) != 1 or selected[0]['slug'] != model:
                raise ValueError('Fixture catalog must select exactly the requested model')
            (root / 'config/model-catalog.json').write_bytes(data)
            report['candidate_model_catalog_sha256'] = digest(data)
        path = root / 'config/config.toml'
        text = path.read_text().replace('model_provider = "openai"', 'model_provider = "fixture"')
        if model_catalog:
            text = 'model_catalog_json = "/config/model-catalog.json"\n' + text
        text = text.replace('forced_login_method = "chatgpt"\n', '')
        if scenario == 'compaction_veto':
            text = text.replace('model_auto_compact_token_limit = 2147483647', 'model_auto_compact_token_limit = 1')
        text += (
            '\n[model_providers.fixture]\nname = "Loopback qualification fixture"\n'
            'base_url = "http://127.0.0.1:8765/v1"\nwire_api = "responses"\n'
            'requires_openai_auth = false\nrequest_max_retries = 0\nstream_max_retries = 0\n'
            'supports_websockets = false\n'
        )
        path.write_text(text)
        shutil.copyfile(ROOT / 'scripts/codex_fixture_provider.py', root / 'fixture/provider.py')
        calls = [
            ('bench_list_files', {}),
            ('bench_read_file', {'path': '/workspace/instruction.md'}),
            ('bench_read_image', {'path': '/workspace/screen.png'}),
            ('bench_write_file', {'path': '/workspace/output/scratch.txt', 'content': 'fixture output'}),
        ]
        steps = [
            dict(
                item=dict(
                    id=f'fc_{i}',
                    type='function_call',
                    call_id=f'call_{i}',
                    name=tool,
                    namespace='mcp__bench',
                    arguments=json.dumps(args),
                    status='completed',
                )
            )
            for i, (tool, args) in enumerate(calls)
        ]
        steps.append(
            dict(
                item=dict(
                    id='msg_final',
                    type='message',
                    role='assistant',
                    status='completed',
                    content=[dict(type='output_text', text='Fixture complete.', annotations=[])],
                )
            )
        )
        if scenario == 'zero_calls':
            steps = [steps[-1]]
        elif scenario == 'native_extended_actions':
            if profile != 'native_extended' or platform != 'mobile' or arm == 'judge_visual':
                raise ValueError('Extended native action control requires its live tool profile')
            mobile_calls = [
                {'action': 'open_app', 'app': 'pro expense'},
                {'action': 'long_press', 'x': 360, 'y': 300},
                {'action': 'scroll', 'dx': 300, 'dy': 0, 'x': 360, 'y': 598},
            ]
            for i, arguments in enumerate(mobile_calls):
                steps.insert(
                    -1,
                    dict(
                        item=dict(
                            id=f'fc_mobile_{i}',
                            type='function_call',
                            call_id=f'call_mobile_{i}',
                            name='gui_step',
                            namespace='mcp__bench',
                            status='completed',
                            arguments=json.dumps(arguments),
                        )
                    ),
                )
        elif scenario == 'target_feedback':
            if platform != 'web' or arm not in {'test_ui', 'judge_test', 'oracle_ui'}:
                raise ValueError('Target feedback control requires web UI tools')
            steps.insert(
                3,
                dict(
                    item=dict(
                        id='fc_target',
                        type='function_call',
                        call_id='call_target',
                        name='gui_step',
                        namespace='mcp__bench',
                        status='completed',
                        arguments=json.dumps({'action': 'click', 'role': 'button', 'name': 'Edit'}),
                    )
                ),
            )
        elif scenario == 'authoring_recovery':
            if platform != 'mobile' or arm == 'judge_visual':
                raise ValueError('Recovery control requires live native tools')
            steps.insert(
                3,
                dict(
                    item=dict(
                        id='fc_recovery',
                        type='function_call',
                        call_id='call_recovery',
                        name='gui_step',
                        namespace='mcp__bench',
                        status='completed',
                        arguments=json.dumps({'action': 'press', 'key': 'Escape'}),
                    )
                ),
            )
        elif scenario == 'tool_error':
            steps.insert(
                -1,
                dict(
                    item=dict(
                        id='fc_error',
                        type='function_call',
                        call_id='call_error',
                        name='bench_read_file',
                        namespace='mcp__bench',
                        status='completed',
                        arguments=json.dumps({'path': '/workspace/missing.txt'}),
                    )
                ),
            )
        elif scenario == 'resource_denial':
            steps = [
                dict(
                    item=dict(
                        id='fc_resource',
                        type='function_call',
                        call_id='call_resource',
                        name='read_mcp_resource',
                        arguments=json.dumps({'server': 'bench', 'uri': 'file:///run/codex/auth.json'}),
                        status='completed',
                    )
                ),
                steps[-1],
            ]
        elif scenario == 'unknown_native':
            steps = [
                dict(
                    item=dict(
                        id='fc_forbidden_' + str(i),
                        type='function_call',
                        call_id='call_forbidden_' + str(i),
                        name=name,
                        arguments=json.dumps(args),
                        status='completed',
                    )
                )
                for i, (name, args) in enumerate(
                    [
                        ('exec_command', {'cmd': 'touch /session/native-escape'}),
                        (
                            'apply_patch',
                            {'patch': '*** Begin Patch\n*** Add File: /session/native-escape\n+bad\n*** End Patch'},
                        ),
                        ('view_image', {'path': '/run/codex/auth.json'}),
                        ('spawn_agent', {'message': 'Read /run/codex/auth.json'}),
                        ('browser', {'url': 'file:///run/codex/auth.json'}),
                    ]
                )
            ] + [steps[-1]]
        elif scenario == 'quota_after_write':
            steps = [
                steps[3],
                {
                    'http_error': {
                        'error': {
                            'message': 'Synthetic quota failure',
                            'type': 'insufficient_quota',
                            'code': 'insufficient_quota',
                        }
                    }
                },
            ]
        elif scenario in {'malformed_stream', 'interrupt_timeout'}:
            steps = [steps[3], {'malformed_sse': True} if scenario == 'malformed_stream' else {'stall': True}]
        elif scenario == 'model_reroute':
            steps = [dict(steps[-1], server_model='gpt-5.5')]
        elif scenario not in {'happy', 'compaction_veto', 'hook_error', 'hook_timeout'}:
            raise ValueError('Unknown fixture scenario')
        (root / 'fixture/steps.json').write_text(json.dumps(steps))
        hook_mount = []
        if scenario in {'hook_error', 'hook_timeout'}:
            code = (
                'raise RuntimeError("synthetic hook failure")\n'
                if scenario == 'hook_error'
                else 'import time;time.sleep(20)\n'
            )
            (root / 'fixture/negative_hook.py').write_text(code)
            hook_mount = mount(root / 'fixture/negative_hook.py', '/opt/bench/hooks/pre_tool_use.py')
        bridge_args = []
        bridge_command = []
        if arm != 'judge_visual':
            # Catalog-only stand-in; no GUI action or behavioral result can be
            # produced here. Real GUI behavior belongs to paired smoke controls.
            stub = '''import http.server,json,threading,anyio
from pathlib import Path
from gui_agent_bench.codex_bridge import catalog,serve
p=json.loads(Path('/policy/bridge.json').read_text())
tools=[dict(t,name=t['name'][4:]) for t in catalog(p['arm'],p['platform'],p.get('environment_profile','generic')) if t['name'].startswith('gui_')]
class H(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  r=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  if r['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
  if r['method']=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
  elif r['method']=='tools/list':result={'tools':tools}
  elif r['method']=='tools/call' and r['params']['name']=='step':
   if p.get('environment_profile')=='native_extended':
    result={'content':[{'type':'text','text':json.dumps({'fixture_received':r['params']['arguments']})}],'isError':False}
   else:
    from gui_agent_bench.authoring_recovery import recovery_result,VERSION
    result=recovery_result({'version':VERSION,'sequence':1,'operation':'step','status':'reset'})
  else:self.send_error(403);return
  b=json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}).encode()
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
s=http.server.HTTPServer(('127.0.0.1',8081),H)
threading.Thread(target=s.serve_forever,daemon=True).start()
anyio.run(serve)
'''
            if scenario == 'target_feedback':
                stub = stub.replace(
                    "result=recovery_result({'version':VERSION,'sequence':1,'operation':'step','status':'reset'})",
                    "from gui_agent_bench.failures import Failure,public_error\n    result={'content':[{'type':'text','text':json.dumps(public_error(Failure('target_ambiguous')))}],'isError':True}",
                )
            (root / 'fixture/catalog_bridge.py').write_text(stub)
            bridge_args = [
                '--add-host',
                'browser:127.0.0.1',
                *mount(root / 'fixture/catalog_bridge.py', '/fixture-bridge.py'),
                '--entrypoint',
                'python',
            ]
            bridge_command = ['/fixture-bridge.py']
        try:
            containers.append(name + '-bridge')
            docker(
                'create',
                '--name',
                containers[-1],
                '--network',
                'none',
                *isolation(),
                '--user',
                f'{os.getuid()}:{os.getgid()}',
                *mount(root / 'workspace', '/workspace'),
                *mount(root / 'output', '/workspace/output', writable=True),
                *mount(root / 'policy', '/policy'),
                *mount(output / 'bridge', '/audit', writable=True),
                *mount(root / 'ipc', '/ipc', writable=True),
                *bridge_args,
                IMAGES['bridge'],
                *bridge_command,
            )
            docker('start', containers[-1])
            deadline = time.monotonic() + 20
            while not (root / 'ipc/bench.sock').exists():
                if time.monotonic() > deadline:
                    raise RuntimeError('Fixture bridge unavailable')
                time.sleep(0.05)
            tmpfs = []
            for path, size in [('codex', '128m'), ('home', '16m'), ('control', '1m')]:
                tmpfs += [
                    '--tmpfs',
                    f'/run/{path}:rw,nosuid,nodev,size={size},mode=0700,uid={os.getuid()},gid={os.getgid()}',
                ]
            containers.append(name + '-agent')
            docker(
                'create',
                '--name',
                containers[-1],
                '--interactive',
                '--network',
                'none',
                *isolation(),
                *options(),
                *tmpfs,
                '--user',
                f'{os.getuid()}:{os.getgid()}',
                *mount(root / 'config', '/config'),
                *mount(root / 'ipc', '/ipc'),
                *mount(root / 'fixture', '/fixture'),
                *mount(output / 'provider', '/fixture-log', writable=True),
                *hook_mount,
                '--entrypoint',
                '/usr/local/bin/python',
                IMAGES['agent'],
                '/fixture/provider.py',
            )
            process = subprocess.Popen(
                ['docker', 'start', '--attach', '--interactive', containers[-1]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
                close_fds=True,
                env=client_environment(),
            )

            class FixtureDriver(Driver):
                def event(self, value, raw_ref):
                    # This exact synthetic fixture warning is recorded here.
                    # Evaluated sessions reject it and never substitute a model.
                    expected = (
                        f'Model metadata for `{model}` not found. Defaulting to fallback metadata; '
                        'this can degrade performance and cause issues.'
                    )
                    if (
                        model == 'gpt-5.4'
                        and value.get('method') == 'warning'
                        and value.get('params', {}).get('message') == expected
                    ):
                        report['fixture_metadata_fallback'] = True
                        self.normalized('warning', value['params'], raw_ref)
                        return
                    if (
                        scenario == 'compaction_veto'
                        and value.get('method') == 'hook/started'
                        and value.get('params', {}).get('run', {}).get('eventName') == 'preCompact'
                    ):
                        # Observe the veto completion after demonstrating that
                        # production rejects the onset. No evaluated trial uses
                        # this observation-only continuation.
                        try:
                            super().event(value, raw_ref)
                        except Exception as exc:
                            report['production_rejection_on_compaction'] = str(exc)
                            return
                        raise ValueError('Production driver accepted compaction onset')
                    return super().event(value, raw_ref)

            driver = FixtureDriver(process, output / 'agent', codex_budget(arm, 60))
            deadline = time.monotonic() + 45
            driver.request(
                'initialize',
                dict(
                    clientInfo=dict(name='gui-agent-bench', version='codex-fixture-v1'),
                    capabilities=dict(experimentalApi=True, requestAttestation=False),
                ),
                deadline,
            )
            driver.send({'method': 'initialized', 'params': {}})
            effective = driver.request('config/read', dict(cwd='/session', includeLayers=True), deadline)
            if effective['config']['model_provider'] != 'fixture':
                raise ValueError('Fixture resolved a non-fixture provider')
            (output / 'effective-config.json').write_text(json.dumps(effective, indent=2) + '\n')
            hooks = driver.request('hooks/list', {'cwds': ['/session']}, deadline)
            (output / 'hooks.json').write_text(json.dumps(hooks, indent=2) + '\n')
            thread = driver.request(
                'thread/start',
                dict(
                    model=model,
                    modelProvider='fixture',
                    cwd='/session',
                    approvalPolicy='never',
                    approvalsReviewer='user',
                    permissions='bench',
                    ephemeral=True,
                    allowProviderModelFallback=False,
                ),
                deadline,
            )
            if thread['modelProvider'] != 'fixture' or thread['activePermissionProfile']['id'] != 'bench':
                raise ValueError('Fixture thread identity differs')
            driver.thread_id = thread['thread']['id']
            servers = driver.request(
                'mcpServerStatus/list', {'threadId': driver.thread_id, 'serverName': 'bench'}, deadline
            )
            (output / 'mcp.json').write_text(json.dumps(servers, indent=2) + '\n')
            if (
                len(servers['data']) != 1
                or servers['data'][0].get('toolsError')
                or set(servers['data'][0]['tools']) != {t['name'] for t in catalog(arm, platform, profile)}
            ):
                raise ValueError('Real-client MCP discovery failed')
            turn_failure = None
            try:
                driver.turn(
                    model, spec.reasoning_effort, 2 if scenario == 'interrupt_timeout' else 60, instruction=content
                )
            except Exception as exc:
                turn_failure = type(exc).__name__ + ': ' + str(exc)
                if scenario not in {
                    'quota_after_write',
                    'resource_denial',
                    'compaction_veto',
                    'hook_error',
                    'hook_timeout',
                    'malformed_stream',
                    'interrupt_timeout',
                    'model_reroute',
                }:
                    raise
            if scenario == 'model_reroute':
                from gui_agent_bench.codex_audit import records

                envelopes = [
                    json.loads(base64.b64decode(r['frame_base64']))
                    for r in records(output / 'agent/codex-rpc.ndjson')
                    if r.get('direction') == 'in' and r.get('frame_base64')
                ]
                if (
                    not turn_failure
                    or driver.completed
                    or not any(v.get('method') == 'model/rerouted' for v in envelopes)
                ):
                    raise ValueError('Actual model reroute was not observed and rejected')
                report.update(
                    status='passed', expected_turn_failure=turn_failure, controls=['rerouted_model_ineligible']
                )
                return report
            if scenario in {'resource_denial', 'compaction_veto', 'hook_error', 'hook_timeout'}:
                from gui_agent_bench.codex_audit import records

                envelopes = [
                    json.loads(base64.b64decode(r['frame_base64']))
                    for r in records(output / 'agent/codex-rpc.ndjson')
                    if r.get('direction') == 'in' and r.get('frame_base64')
                ]
                event_name = 'preCompact' if scenario == 'compaction_veto' else 'preToolUse'
                hooks_seen = [
                    v['params']['run']
                    for v in envelopes
                    if v.get('method') in {'hook/started', 'hook/completed'}
                    and v['params']['run']['eventName'] == event_name
                ]
                if not turn_failure or driver.completed or not hooks_seen:
                    raise ValueError('Required hook did not make the turn ineligible')
                vetoed = (
                    any(
                        v['status'] == 'stopped'
                        and {'kind': 'stop', 'text': 'Context compaction is not permitted.'} in v['entries']
                        for v in hooks_seen
                    )
                    if scenario == 'compaction_veto'
                    else False
                )
                if not vetoed and not any(v['status'] in {'blocked', 'failed', 'cancelled'} for v in hooks_seen):
                    raise ValueError('Required hook failure/veto completion was not observed')
                if scenario == 'resource_denial' and bool((output / 'bridge/bridge.ndjson').read_bytes()):
                    raise ValueError('Forbidden resource request reached the bridge action handler')
                report.update(
                    status='passed',
                    expected_turn_failure=turn_failure,
                    hooks_observed=hooks_seen,
                    controls=[scenario, 'ineligible_turn'],
                )
                return report
            if scenario in {'quota_after_write', 'malformed_stream', 'interrupt_timeout'}:
                if (
                    not turn_failure
                    or driver.completed
                    or (root / 'output/scratch.txt').read_text() != 'fixture output'
                ):
                    raise ValueError('Provider failure after an artifact did not invalidate the turn')
                requests = list((output / 'provider').glob('request-*.json'))
                if len(requests) != 2:
                    raise ValueError('Provider failure triggered an unexpected retry')
                report.update(
                    status='passed',
                    expected_turn_failure=turn_failure,
                    controls=['artifact_does_not_override_provider_failure', 'no_provider_retry'],
                )
                if scenario == 'interrupt_timeout':
                    driver.interrupt()
                    report['controls'].append('timeout_interrupt_and_cleanup')
                return report
            process.stdin.close()
            process.wait(timeout=10)
            driver.drain()
            if process.returncode != 0:
                raise ValueError('Fixture server did not shut down successfully')
            if scenario in {'resource_denial', 'unknown_native'}:
                requests = [json.loads(p.read_text()) for p in sorted((output / 'provider').glob('request-*.json'))]
                if len(requests) != len(steps):
                    raise ValueError('Negative control request count differs')
                outcomes = [v for v in requests[-1]['input'] if v.get('type') == 'function_call_output']
                if len(outcomes) != len(steps) - 1:
                    raise ValueError('Missing negative control result')
                report['negative_outputs'] = outcomes
                if bool((output / 'bridge/bridge.ndjson').read_bytes()) or list((root / 'output').iterdir()):
                    raise ValueError('Forbidden native/resource call reached an output or bridge action')
                if any(
                    not any(
                        word in json.dumps(v['output']).lower()
                        for word in ['denied', 'not permitted', 'unknown', 'unsupported', 'unrecognized']
                    )
                    for v in outcomes
                ):
                    raise ValueError('Forbidden capability did not return a denial')
                report.update(status='passed', controls=[scenario, 'no_bridge_action_or_output', 'clean_shutdown'])
                return report
            report['reconciliation'] = reconcile(
                output / 'agent', output / 'bridge', catalog(arm, platform, profile), platform
            )
            requests = [json.loads(p.read_text()) for p in sorted((output / 'provider').glob('request-*.json'))]
            if len(requests) != len(steps):
                raise ValueError('Fixture request count differs')
            report['offered_tools'] = requests[0]['tools']
            offered = requests[0]['tools']
            if {t.get('name') for t in offered} != {
                'list_mcp_resources',
                'list_mcp_resource_templates',
                'read_mcp_resource',
                'mcp__bench',
            }:
                raise ValueError('Actual offered catalog exposes unexpected capabilities')
            namespace = next(t for t in offered if t['name'] == 'mcp__bench')
            if namespace['type'] != 'namespace' or {t['name'] for t in namespace['tools']} != {
                t['name'] for t in catalog(arm, platform, profile)
            }:
                raise ValueError('Actual offered MCP namespace differs')
            if scenario == 'zero_calls':
                if (
                    report['reconciliation']['bridge_calls'] != 0
                    or (output / 'bridge/bridge.ndjson').read_bytes() != b''
                    or list((root / 'output').iterdir())
                ):
                    raise ValueError('Zero-call session did not retain an empty ledger and output')
                report.update(
                    status='passed',
                    controls=[
                        'exact_actual_catalog',
                        'zero_calls_empty_ledger',
                        'terminal_reconciliation',
                        'no_submission_created',
                        'clean_shutdown',
                    ],
                )
                return report
            if (root / 'output/scratch.txt').read_text() != 'fixture output':
                raise ValueError('Fixture tool write did not execute')
            followup = {
                v['call_id']: v['output'] for v in requests[-1]['input'] if v.get('type') == 'function_call_output'
            }
            page_blocks = followup['call_1']
            pages = []
            for block in page_blocks:
                try:
                    value = json.loads(block.get('text', ''))
                except ValueError:
                    continue
                if isinstance(value, dict) and value.get('path') == '/workspace/instruction.md':
                    pages.append(value['text'])
            image_blocks = [v for v in followup['call_2'] if v['type'] == 'input_image']
            if (
                pages != [content]
                or len(image_blocks) != 1
                or image_blocks[0]['image_url']
                != 'data:image/png;base64,' + base64.b64encode(image.getvalue()).decode()
            ):
                raise ValueError('Fixture following input lost text/image content')
            if scenario == 'authoring_recovery':
                if len(report['reconciliation']['authoring_recoveries']) != 1:
                    raise ValueError('Native recovery evidence missing')
                if 'call_recovery' not in followup:
                    raise ValueError('Recovery feedback missing from model input')
                report['authoring_recovery_following_input'] = followup['call_recovery']
            if scenario == 'target_feedback':
                blocks = followup.get('call_target', [])
                if not any('target_ambiguous' in block.get('text', '') for block in blocks):
                    raise ValueError('Target feedback missing from following model input')
                from gui_agent_bench.codex_audit import records

                actions = [
                    r
                    for r in records(output / 'bridge/bridge.ndjson')
                    if r.get('phase') == 'completed' and r.get('tool') == 'gui_step'
                ]
                if len(actions) != 1 or report['reconciliation']['authoring_recoveries']:
                    raise ValueError('Target feedback repeated an action or reset')
                report['target_feedback'] = {
                    'following_write_succeeded': True,
                    'action_calls': 1,
                    'automatic_reset': False,
                    'automatic_retry': False,
                }
            if scenario == 'native_extended_actions':
                for i, arguments in enumerate(mobile_calls):
                    blocks = followup[f'call_mobile_{i}']
                    received = []
                    for block in blocks:
                        try:
                            value = json.loads(block.get('text', ''))
                        except ValueError:
                            continue  # The native client also inserts a wall-time text block.
                        if isinstance(value, dict):
                            received.append(value.get('fixture_received'))
                    if arguments not in received:
                        raise ValueError(
                            'Extended native extension arguments did not survive the client/bridge round trip'
                        )
                report['native_extended_actions'] = mobile_calls
            if scenario == 'tool_error':
                from gui_agent_bench.codex_audit import records

                calls = records(output / 'bridge/bridge.ndjson')
                if not any(r.get('result', {}).get('isError') for r in calls):
                    raise ValueError('Missing expected bridge error result')
                if 'call_error' not in followup or not followup['call_error']:
                    raise ValueError('Following model input lost the tool error')
                report['tool_error_following_input'] = followup['call_error']
            report['controls'] = [
                'exact_actual_catalog',
                'real_client_mcp_calls',
                'text_image_following_input',
                'bridge_meta_bijection',
                'managed_hooks',
                'clean_shutdown',
            ]
            report['status'] = 'passed'
        except Exception as exc:
            report['failure'] = type(exc).__name__ + ': ' + str(exc)
            if driver:
                driver.interrupt()
        finally:
            if driver:
                driver.close()
            for container in reversed(containers):
                (output / (container.rsplit('-', 1)[-1] + '-container.log')).write_text(
                    docker('logs', container, check=False, include_stderr=True)
                )
                docker('rm', '-f', container, check=False)
            if process and process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            report['cleanup'] = all(not docker('ps', '-aq', '--filter', 'name=^/' + n + '$') for n in containers)
            (output / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--arm', default='judge_visual')
    parser.add_argument('--platform', default='web')
    parser.add_argument('--profile', choices=['generic', 'native_extended'], default='generic')
    parser.add_argument('--model-catalog', type=Path, help='Test-only explicit model metadata candidate')
    parser.add_argument('--reasoning-effort', choices=['low', 'medium', 'high', 'xhigh'], default='medium')
    parser.add_argument(
        '--scenario',
        choices=[
            'happy',
            'resource_denial',
            'unknown_native',
            'quota_after_write',
            'compaction_veto',
            'hook_error',
            'hook_timeout',
            'malformed_stream',
            'interrupt_timeout',
            'model_reroute',
            'tool_error',
            'authoring_recovery',
            'native_extended_actions',
            'target_feedback',
            'zero_calls',
        ],
        default='happy',
    )
    args = parser.parse_args()
    report = control(
        args.output.resolve(),
        args.model,
        args.arm,
        args.platform,
        args.scenario,
        args.model_catalog,
        args.profile,
        args.reasoning_effort,
    )
    print(json.dumps({k: report[k] for k in ['status', 'cleanup', 'failure'] if k in report}))
    raise SystemExit(0 if report['status'] == 'passed' else 1)
