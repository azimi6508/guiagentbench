"""Host command routing for evaluations, batch plans and the run viewer."""

import argparse
from pathlib import Path
import sys

from gui_agent_bench import cli


def interrupt_on_termination():
    """Let SIGTERM and SIGHUP unwind like Ctrl+C, so cleanup and run records complete."""
    import signal
    import threading

    if threading.current_thread() is not threading.main_thread():
        return

    def interrupt(*_):
        raise KeyboardInterrupt

    for name in ('SIGTERM', 'SIGHUP'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupt)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    interrupt_on_termination()
    # Parse just the common root prefix and command to delegate every existing
    # invocation unchanged, including its help and error handling.
    prefix = argparse.ArgumentParser(add_help=False)
    prefix.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    prefix.add_argument('command', nargs='?')
    args, _ = prefix.parse_known_args(argv)
    if args.command == 'run' and any(a == '--plan' or a.startswith('--plan=') for a in argv):
        from gui_agent_bench.run_plan import main as run_plan

        return run_plan(argv, args.root)
    if args.command != 'view':
        if argv in (['--help'], ['-h']):
            cli.parser().print_help()
            print('\nHost tools:\n  view [directory] [--port PORT] [--no-open]  Browse saved and live run evidence')
            print('  run --plan FILE [--check-plan]  Run a fixed multi-task, multi-arm plan')
            return 0
        return cli.main(argv)
    parser = argparse.ArgumentParser(prog='gui-agent-bench view')
    parser.add_argument('--root', type=Path, default=args.root)
    parser.add_argument('command', choices=['view'], help=argparse.SUPPRESS)
    parser.add_argument('directory', nargs='?', type=Path, help='runs directory or a single run (default: <root>/runs)')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--no-open', action='store_true', help='print the URL without opening a browser')
    options = parser.parse_args(argv)
    from gui_agent_bench.viewer.app import main as view

    return view(
        [
            *([str(options.directory)] if options.directory else []),
            '--port',
            str(options.port),
            *(['--no-open'] if options.no_open else []),
        ],
        default_root=options.root / 'runs',
    )
