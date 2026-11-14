"""Validate remote-task packages through the shared task-local manifest."""

from gui_agent_bench.task_package import verify, metadata


def verify_task(task):
    if metadata(task)['metadata']['platform'] != 'tv':
        raise ValueError('Expected a remote-only TV execution package')
    return verify(task)
