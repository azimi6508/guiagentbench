"""Trusted controller finalization: retain evidence and finish every owned cleanup."""

from gui_agent_bench.failures import Failure, issue
from gui_agent_bench.io import dump


class CleanupFailure(Failure):
    def __init__(self, issues):
        super().__init__(issues[0]['cause'])
        self.diagnostic_issues = issues


def finalize_resources(session, containers, networks, logs, folder, docker):
    """Attempt each operation once, collecting safe zero-credit diagnostics."""
    issues, cleanup = [], []

    def failed(error, operation, source):
        issues.append(issue(error, phase='cleanup', operation=operation, impact='zero_credit', source=source))

    if session is not None:
        try:
            session.close()
        except BaseException as error:
            failed(error, 'native_shutdown', {'file': 'mobile-shutdown.json'})
    for name, path, include_stderr in logs:
        try:
            text = docker('logs', name, check=False, include_stderr=include_stderr)
            path.write_text(text, encoding='utf-8')
        except BaseException as error:
            failed(error, 'collect_logs', {'file': path.relative_to(folder).as_posix()})
    for index, name in enumerate(reversed(containers)):
        removed = False
        try:
            docker('rm', '-f', name, check=False)
            removed = not bool(docker('ps', '-aq', '--filter', f'name=^{name}$'))
            if not removed:
                raise Failure('infrastructure_error')
        except BaseException as error:
            failed(error, 'remove_container', {'file': 'cleanup.json', 'container_index': index})
        cleanup.append({'container': name, 'removed': removed})
    for index, name in enumerate(reversed(networks)):
        try:
            docker('network', 'rm', name, check=False)
            remaining = docker('network', 'ls', '--filter', f'name={name}', '--format', '{{.Name}}')
            if name in remaining.splitlines():
                raise Failure('infrastructure_error')
        except BaseException as error:
            failed(error, 'remove_network', {'file': 'cleanup.json', 'network_index': index})
    try:
        dump(folder / 'cleanup.json', cleanup)
    except BaseException as error:
        failed(error, 'write_cleanup_evidence', {'file': 'cleanup.json'})
    return issues
