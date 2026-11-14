"""Bounded recovery of a known native app-scope loss during authoring only."""

import json

from gui_agent_bench.failures import Failure, issue, public_error

VERSION = 'authoring-recovery-v1'
LIMIT = 3
OPERATIONS = {'step', 'observe', 'dump_ui', 'open_url'}
MESSAGE = (
    'The operation failed because the app left the permitted scope. '
    'The harness reset the app to this arm\'s starting state. '
    'Exploration progress was discarded; the failed action was not repeated. '
    'Continue from the restored state within the remaining budget.'
)


def recovery_result(marker):
    return {
        'content': [
            {
                'type': 'text',
                'text': json.dumps({'cause': 'app_scope_lost', 'message': MESSAGE, 'recovery': marker}, sort_keys=True),
            }
        ],
        'isError': True,
    }


def recovery_from_result(result, platform, tool):
    if platform != 'mobile' or tool.removeprefix('gui_') not in OPERATIONS or result.get('isError') is not True:
        return None
    content = result.get('content')
    if (
        not isinstance(content, list)
        or len(content) != 1
        or not isinstance(content[0], dict)
        or content[0].get('type') != 'text'
    ):
        return None
    try:
        value = json.loads(content[0]['text'])
        marker = value['recovery']
        if (
            set(marker) != {'version', 'sequence', 'operation', 'status'}
            or marker['version'] != VERSION
            or marker['status'] != 'reset'
            or marker['operation'] != tool.removeprefix('gui_')
            or type(marker['sequence']) is not int
            or not 1 <= marker['sequence'] <= LIMIT
            or value != json.loads(recovery_result(marker)['content'][0]['text'])
        ):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    return marker


class AuthoringRecovery:
    def __init__(self, platform, reset, log):
        self.platform, self.reset, self.log = platform, reset, log
        self.count = 0
        self.blocked = None

    def check(self):
        if self.blocked:
            raise Failure(self.blocked)

    def handle(self, exc, operation):
        original = issue(exc, phase='authoring', operation=operation, impact='feedback')
        marker = None
        if (
            not self.blocked
            and self.platform == 'mobile'
            and isinstance(exc, Failure)
            and exc.cause == 'app_scope_lost'
            and operation in OPERATIONS
        ):
            if self.count >= LIMIT:
                self.blocked = 'budget_exhausted'
                self.log(recovery_event={'version': VERSION, 'status': 'exhausted', 'failure': original})
                exc = Failure(self.blocked)
            else:
                self.count += 1
                base = {'version': VERSION, 'sequence': self.count, 'operation': operation}
                self.log(recovery_event={**base, 'status': 'started', 'failure': original})
                try:
                    self.reset()
                except Exception as reset_exc:
                    self.blocked = 'reset_failure'
                    self.log(
                        recovery_event={
                            **base,
                            'status': 'failed',
                            'failure': issue(
                                reset_exc, phase='authoring', operation='recovery_reset', impact='zero_credit'
                            ),
                        }
                    )
                    exc = Failure(self.blocked)
                else:
                    marker = {**base, 'status': 'reset'}
                    self.log(recovery_event=marker)
                    return recovery_result(marker), original, marker
        failure = issue(exc, phase='authoring', operation=operation, impact='feedback')
        return {'content': [{'type': 'text', 'text': json.dumps(public_error(exc))}], 'isError': True}, failure, marker


def audit_recovery_events(records, platform):
    """Replay trusted reset events and their corresponding failed tool records."""
    completed, active, pending = [], None, None
    for record in records:
        event = record.get('recovery_event')
        if event is not None:
            if platform != 'mobile' or event.get('version') != VERSION:
                raise ValueError('Unexpected authoring recovery contract')
            status = event.get('status')
            if status == 'started':
                if (
                    active
                    or pending
                    or event.get('sequence') != len(completed) + 1
                    or type(event.get('sequence')) is not int
                    or len(completed) >= LIMIT
                    or event.get('operation') not in OPERATIONS
                    or event.get('failure', {}).get('cause') != 'app_scope_lost'
                    or event['failure'].get('phase') != 'authoring'
                ):
                    raise ValueError('Invalid authoring reset start')
                active = {k: event[k] for k in ('version', 'sequence', 'operation')}
            elif status == 'reset' and active and event == dict(active, status='reset'):
                pending, active = event, None
            else:
                raise ValueError('Authoring recovery failed or is incomplete')
        if 'recovery' in record:
            marker = record['recovery']
            if (
                not pending
                or marker != pending
                or record.get('tool') != marker['operation']
                or record.get('operation_failed') is not True
                or record.get('denied') is not False
                or record.get('failure', {}).get('cause') != 'app_scope_lost'
            ):
                raise ValueError('Authoring recovery lacks matching reset evidence')
            completed.append(marker)
            pending = None
    if active or pending:
        raise ValueError('Incomplete authoring reset evidence')
    return completed
