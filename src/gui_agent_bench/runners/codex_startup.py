"""Same-process no-inference capability attestation."""

import time

from gui_agent_bench.failures import Failure
from .registry import fingerprint


def require(condition):
    if not condition:
        raise Failure('capability_unavailable')


def inventory(driver, method, params, deadline):
    values, cursors = [], set()
    while True:
        response = driver.request(method, params, deadline)
        values.extend(response['data'])
        cursor = response.get('nextCursor')
        if not cursor:
            return values
        require(cursor not in cursors and len(cursors) < 100)
        cursors.add(cursor)
        params = {**params, 'cursor': cursor}


def admitted_layer(layer):
    source = layer.get('name') or {}
    if source.get('type') == 'enterpriseManaged':
        # A ChatGPT workspace may push an admin default model. Admit only that
        # key; startup separately requires the effective model to equal the
        # pinned selection, so the admin value cannot take effect.
        managed = layer.get('config')
        return isinstance(managed, dict) and set(managed) <= {'model'}
    return source.get('type') in {'system', 'user', 'sessionFlags', 'legacyManagedConfigFile'}


def startup(driver, spec, config, tools, *, list_models=False, expected_hooks=None):
    deadline = time.monotonic() + 120
    driver.request(
        'initialize',
        {
            'clientInfo': {'name': 'gui-agent-bench', 'version': 'codex-runner-v1'},
            'capabilities': {'experimentalApi': True, 'requestAttestation': False},
        },
        deadline,
    )
    driver.send({'method': 'initialized', 'params': {}})
    effective = driver.request('config/read', {'cwd': '/session', 'includeLayers': True}, deadline)
    actual = effective['config']
    for key in (
        'model',
        'model_provider',
        'model_reasoning_effort',
        'approval_policy',
        'approvals_reviewer',
        'forced_login_method',
        'web_search',
        'model_auto_compact_token_limit',
    ):
        require(actual.get(key) == config[key])
    require(actual.get('model_catalog_json') == config.get('model_catalog_json'))
    for key in (
        'instructions',
        'developer_instructions',
        'forced_chatgpt_workspace_id',
        'apps',
        'browser_use',
        'computer_use',
    ):
        require(not actual.get(key))
    layers = effective.get('layers') or []
    # The concrete config/read projection omits some native feature fields.
    # Require those fields from the same process's admitted config layers.
    layer_configs = [x.get('config', {}) for x in layers if not x.get('disabledReason')]
    require(
        any(
            v.get('permissions') == config['permissions']
            and v.get('features') == config['features']
            and v.get('mcp_servers') == config['mcp_servers']
            and v.get('tools') == config.get('tools')
            for v in layer_configs
        )
    )
    for layer in layers:
        if not layer.get('disabledReason'):
            require(admitted_layer(layer))
    requirements = driver.request('configRequirements/read', None, deadline)['requirements']
    require(isinstance(requirements, dict))
    for key, expected in dict(
        defaultPermissions='bench',
        allowedPermissionProfiles={'bench': True},
        allowedApprovalPolicies=['never'],
        allowedApprovalsReviewers=['user'],
        allowedWebSearchModes=['disabled'],
        allowManagedHooksOnly=True,
    ).items():
        require(requirements.get(key) == expected)
    hooks = driver.request('hooks/list', {'cwds': ['/session']}, deadline)['data']
    require(len(hooks) == 1 and hooks[0]['cwd'] == '/session' and not hooks[0]['errors'] and not hooks[0]['warnings'])
    actual_hooks = hooks[0]['hooks']
    if expected_hooks is not None:
        require(actual_hooks == expected_hooks)
    require(len(actual_hooks) == 2)
    for event, script in [('preToolUse', 'pre_tool_use.py'), ('preCompact', 'pre_compact.py')]:
        selected = [h for h in actual_hooks if h['eventName'] == event]
        require(len(selected) == 1)
        hook = selected[0]
        require(
            hook['enabled']
            and hook['isManaged']
            and hook['trustStatus'] == 'managed'
            and hook['handlerType'] == 'command'
            and not hook.get('async')
            and hook['timeoutSec'] == 5
            and hook['command'] == '/usr/local/bin/python /opt/bench/hooks/' + script
            and bool(hook['currentHash'])
        )
    account = driver.request('account/read', {'refreshToken': False}, deadline)
    require((account.get('account') or {}).get('type') == 'chatgpt')
    models = inventory(driver, 'model/list', {}, deadline)
    safe_models = [
        {
            'id': m['id'],
            'model': m['model'],
            'supportedReasoningEfforts': [e['reasoningEffort'] for e in m['supportedReasoningEfforts']],
        }
        for m in models
    ]
    if list_models:
        return {'models': safe_models, 'auth_mode': 'chatgpt', 'inference_started': False}
    matching = [m for m in safe_models if m['model'] == spec.model]
    require(len(matching) == 1 and spec.reasoning_effort in matching[0]['supportedReasoningEfforts'])
    thread = driver.request(
        'thread/start',
        dict(
            model=spec.model,
            modelProvider='openai',
            cwd='/session',
            approvalPolicy='never',
            approvalsReviewer='user',
            permissions='bench',
            ephemeral=True,
            allowProviderModelFallback=False,
        ),
        deadline,
    )
    for key, expected in dict(
        model=spec.model,
        modelProvider='openai',
        cwd='/session',
        approvalPolicy='never',
        approvalsReviewer='user',
        reasoningEffort=spec.reasoning_effort,
    ).items():
        require(thread.get(key) == expected)
    require((thread.get('activePermissionProfile') or {}).get('id') == 'bench' and not thread.get('instructionSources'))
    body = thread['thread']
    require(
        body.get('ephemeral') is True
        and not body.get('forkedFromId')
        and not body.get('parentThreadId')
        and not body.get('agentRole')
    )
    require(driver.thread_id in {None, body['id']})
    driver.thread_id = body['id']
    servers = inventory(driver, 'mcpServerStatus/list', {'threadId': body['id'], 'serverName': 'bench'}, deadline)
    require(len(servers) == 1)
    server = servers[0]
    require(
        server['name'] == 'bench'
        and server['runtimeStatus'] == 'connected'
        and not server['toolsError']
        and not server['resources']
        and not server['resourceTemplates']
        and not server.get('pluginId')
    )
    require(set(server['tools']) == {t['name'] for t in tools})
    for tool in tools:
        offered = server['tools'][tool['name']]
        require(offered['inputSchema'] == tool['inputSchema'] and offered['description'] == tool['description'])
    capabilities = server['serverCapabilities']
    require(set(capabilities) <= {'tools', 'experimental'} and not capabilities.get('experimental'))
    return dict(
        schema='codex-startup-v1',
        status='passed',
        thread_id=body['id'],
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        auth_mode='chatgpt',
        auth_status='saved_chatgpt',
        effective_config_sha256=fingerprint(config),
        profile=thread['activePermissionProfile'],
        hooks=actual_hooks,
        tools=tools,
        mcp_server=server,
        upstream_tool_catalog_visibility='qualified fixture only; TLS is opaque',
        inference_started=False,
    )
