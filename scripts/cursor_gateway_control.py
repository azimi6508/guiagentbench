"""Exercise the actual gateway image with synthetic traffic and no credentials/network."""

import argparse
import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch


def field(number, data):
    def integer(value):
        result = bytearray()
        while value > 127:
            result.append((value & 127) | 128)
            value >>= 7
        result.append(value)
        return bytes(result)

    return integer(number * 8 + 2) + integer(len(data)) + data


def in_container():
    spec = importlib.util.spec_from_file_location('production_gateway', '/opt/bench/gateway.py')
    gateway = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gateway)
    identity = field(1, b'synthetic-model')
    initial_append = field(4, field(1, field(9, identity)))
    expected = gateway.requested_identity(initial_append, 'application/proto')['sha256']
    os.environ.update(
        GAB_CURSOR_ACCESS_TOKEN='synthetic-only-token',
        GAB_CURSOR_MODEL_IDENTITY=expected,
        GAB_CURSOR_PAYLOAD_LIMIT='3',
        GAB_CURSOR_HEARTBEAT_LIMIT='400',
        GAB_CURSOR_METADATA_LIMIT='400',
    )
    server = gateway.GatewayHTTPServer(('127.0.0.1', 0), gateway.Handler)
    server.daemon_threads = True
    server.state = gateway.State()
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    evidence = io.StringIO()
    sent = []
    audit_finished = threading.Condition()
    audit_count = 0
    production_record = gateway.record

    def record(row):
        nonlocal audit_count
        production_record(row)
        with audit_finished:
            audit_count += 1
            audit_finished.notify_all()

    def remote_factory(*args, **kwargs):
        response = Mock(status=200, length=0)
        response.getheader.side_effect = lambda name: 'application/proto' if name == 'Content-Type' else None
        response.read1.return_value = b''
        remote = Mock()
        remote.getresponse.return_value = response
        remote.request.side_effect = lambda *args, **kwargs: sent.append(True)
        return remote

    def request(path, data=b'', tools=True):
        with audit_finished:
            before = audit_count
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        headers = {'Content-Type': 'application/proto'}
        if tools:
            headers['x-cursor-agent-allowed-tools'] = 'mcp_tool_call,get_mcp_tools_tool_call'
        try:
            connection.request('POST', path, data, headers)
            response = connection.getresponse()
            response.read()
            return response.status
        except (http.client.RemoteDisconnected, http.client.IncompleteRead):
            return None
        finally:
            connection.close()
            # The response may precede the handler's finally audit write.
            # Wait for that one record; never resend the synthetic request.
            with audit_finished:
                if not audit_finished.wait_for(lambda: audit_count == before + 1, timeout=5):
                    raise AssertionError('Gateway request audit did not complete exactly once')

    append = '/aiserver.v1.BidiService/BidiAppend'
    run = field(4, field(1, field(9, identity)))
    checks = []
    try:
        with (
            patch.object(gateway.http.client, 'HTTPSConnection', side_effect=remote_factory),
            patch.object(gateway, 'record', new=record),
            contextlib.redirect_stdout(evidence),
        ):
            assert request(append, run) == 200
            for i in range(300):
                # Distinct, bounded heartbeat envelopes; no provider/model call.
                heartbeat = field(4, field(7, b'')) + field(1, str(i).encode())
                assert request(append, heartbeat) == 200
                assert request('/aiserver.v1.DashboardService/GetUserPrivacyMode') == 200
            assert server.state.counts == {'payload': 1, 'heartbeat': 300, 'metadata': 300}
            checks.append('600-routine-requests-preserve-payload-budget')
            assert request(append, field(4, field(2, b'a'))) == 200
            assert request(append, field(4, field(2, b'b'))) == 200
            before = len(sent)
            assert request(append, field(4, field(2, b'c'))) is None
            assert len(sent) == before
            rows = [json.loads(line) for line in evidence.getvalue().splitlines()]
            assert rows[-1]['rejection_reason'] == 'payload_request_limit'
            checks.append('payload-budget-denial-before-upstream')
            assert request('/aiserver.v1.DashboardService/GetMe') is None
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'session_already_failed'
            checks.append('failure-remains-fatal')
            server.state = gateway.State()
            before = len(sent)
            assert request(append, run, tools=False) is None
            assert len(sent) == before
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'tool_policy_mismatch'
            checks.append('missing-tool-policy-denied')
            server.state = gateway.State()
            assert request(append, field(4, field(1, field(9, field(1, b'wrong-model'))))) is None
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'model_identity_mismatch'
            checks.append('model-substitution-denied')
            server.state = gateway.State()
            assert request(append, run) == 200
            assert request(append, run) is None
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'repeated_model_start'
            checks.append('second-model-session-denied')
            server.state = gateway.State()
            before = len(sent)
            catalog = '/aiserver.v1.AiService/AvailableModels'
            payload = b'catalog-control-response'

            def catalog_remote(*args, **kwargs):
                remote = remote_factory(*args, **kwargs)
                response = remote.getresponse.return_value
                response.getheader.side_effect = lambda name: 'application/proto' if name == 'Content-Type' else None
                response.read1.side_effect = [payload, b'']
                return remote

            with patch.object(gateway.http.client, 'HTTPSConnection', side_effect=catalog_remote):
                assert request(catalog, b'fixed-catalog-query') == 200
                assert request(catalog, b'fixed-catalog-query') == 200
                assert len(sent) == before + 1
                assert server.state.catalog[2] == payload
                assert json.loads(evidence.getvalue().splitlines()[-1])['outcome'] == 'trial_catalog_cache'
                assert request(catalog, b'changed-catalog-query') is None
                assert len(sent) == before + 1
                assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'catalog_request_changed'
            checks.append('identical-trial-catalog-cached-without-upstream-retry')
            checks.append('changed-catalog-request-denied')
            server.state = gateway.State()
            before = len(sent)
            assert request('/v1/traces', b'{"synthetic":"telemetry"}') == 200
            assert len(sent) == before and server.state.counts['metadata'] == 1
            assert json.loads(evidence.getvalue().splitlines()[-1])['outcome'] == 'local_metadata'
            checks.append('bounded-telemetry-dropped-without-upstream')
            assert request('/unknown/operation') == 403
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'request_path_not_allowed'
            assert request('/aiserver.v1.DashboardService/GetMe') is None
            assert json.loads(evidence.getvalue().splitlines()[-1])['rejection_reason'] == 'session_already_failed'
            assert len(sent) == before
            checks.append('unknown-path-denial-remains-fatal')
    finally:
        server.shutdown()
        worker.join()
        server.server_close()
    assert 'synthetic-only-token' not in evidence.getvalue()
    return dict(
        schema='cursor-gateway-control-v1',
        status='passed',
        checks=checks,
        real_inference_started=False,
        credentials_used=False,
        network='none',
    )


def main():
    if sys.argv[1:] == ['--in-container']:
        print(json.dumps(in_container()))
        return
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'src'))
    from gui_agent_bench.docker import docker, isolation, mount
    from gui_agent_bench.runners.cursor_config import IMAGES
    from gui_agent_bench.io import dump

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.relative_to(root)
    out.mkdir(parents=True, exist_ok=False)
    result = json.loads(
        docker(
            'run',
            '--rm',
            '--network',
            'none',
            '--user',
            f'{os.getuid()}:{os.getgid()}',
            *isolation(),
            *mount(Path(__file__).resolve(), '/control.py'),
            '--entrypoint',
            'python',
            IMAGES['gateway'],
            '/control.py',
            '--in-container',
        )
    )
    # Import the gateway baked into this exact image, never the checkout copy.
    # The controlled suite injects failed upstream replies without networking,
    # credentials, model turns, action retries or altered production budgets.
    privacy_log = docker(
        'run',
        '--rm',
        '--network',
        'none',
        '--user',
        f'{os.getuid()}:{os.getgid()}',
        *isolation(),
        *mount(root / 'tests/test_cursor_privacy_cache.py', '/privacy_test.py'),
        '--env',
        'GAB_CURSOR_TEST_GATEWAY_PATH=/opt/bench/gateway.py',
        '--entrypoint',
        'python',
        IMAGES['gateway'],
        '/privacy_test.py',
        'GatewayPrivacyTests',
        '-v',
        include_stderr=True,
    )
    (out / 'privacy-image-tests.log').write_text(privacy_log)
    result['checks'].append('privacy-freshness-cancellation-failure-concurrency-and-budget-image-controls')
    result['privacy_image_tests'] = 15
    result['image'] = json.loads(docker('image', 'inspect', IMAGES['gateway']))[0]['Id']
    dump(out / 'control.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
