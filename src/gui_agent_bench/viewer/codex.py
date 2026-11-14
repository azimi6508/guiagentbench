"""Display actual Codex envelopes without inventing OpenCode event records."""

import base64
import json


def envelope(record):
    if record.get('privacy_projection'):
        return {'method': 'privacy_projection', 'params': {'status': record.get('status')}, '_rpc': record}
    try:
        value = json.loads(base64.b64decode(record['frame_base64'], validate=True))
        return {**value, '_rpc': {k: v for k, v in record.items() if k != 'frame_base64'}}
    except (KeyError, ValueError, TypeError):
        return {'method': 'incomplete_evidence', 'params': record, '_rpc': record}


def identity(event):
    params = event.get('params') or {}
    item = params.get('item') or {}
    if item.get('id') and event.get('method') in {'item/started', 'item/completed'}:
        return (params.get('threadId'), params.get('turnId'), item['id'])
    return None


def presentation(event):
    method = event.get('method', 'rpc_reply')
    params = event.get('params') or {}
    item = params.get('item') or {}
    result = item.get('result') or {}
    text = params.get('delta', item.get('text'))
    tool = item.get('type') == 'mcpToolCall'
    return dict(
        kind=(
            'codex_tool'
            if tool
            else (
                'codex_text'
                if method == 'item/agentMessage/delta' or item.get('type') == 'agentMessage'
                else 'codex_record'
            )
        ),
        title=item.get('tool', method),
        status=item.get('status'),
        call_id=result.get('_meta', {}).get('gui_agent_bench.bridge_call_id'),
        input=item.get('arguments'),
        output=result.get('content') if tool else text,
        error=item.get('error') or ('Incomplete evidence' if method == 'incomplete_evidence' else None),
    )
