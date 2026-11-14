"""One outer CLI; platform and harness details stay behind the trial interface."""

import argparse
import json
from pathlib import Path
from gui_agent_bench.arms import ARM_IDS
from gui_agent_bench.budgets import DEFAULT_TIMEOUT_SECONDS, check_timeout


def parser():
    cli = argparse.ArgumentParser(prog='gui-agent-bench')
    cli.add_argument(
        '--root',
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help='benchmark checkout containing configs/tasks (required for non-editable installs)',
    )
    # Internal container entry points stay callable but are not advertised.
    commands = cli.add_subparsers(dest='command', required=True, metavar='{build,run,verify,verify-oracle,verify-test}')
    build = commands.add_parser('build', help='build pinned runtime and app Docker images')
    build.add_argument('--runner', choices=['opencode', 'codex', 'cursor', 'claude', 'all'], default='opencode')
    build.add_argument(
        '--app-only', action='store_true', help='Build only the selected application; reuse shared framework images'
    )
    build.add_argument(
        '--task', help='also build this task\'s application image; without it only shared runtime images are built'
    )
    run = commands.add_parser(
        'run', help='run any of the six arms with isolated OpenCode, Codex, Cursor or Claude Code'
    )
    from gui_agent_bench.runners.registry import add_options

    add_options(run)
    run.add_argument('--task', required=True, help='task ID, for example web/webarena-399-profile-bio')
    run.add_argument('--arm', choices=ARM_IDS, default='judge_visual')
    run.add_argument('--variant', choices=['correct', 'faulty', 'pair'], default='pair')
    run.add_argument(
        '--model',
        required=True,
        help='reference/solution, fixture/scripted, openrouter/<model>, codex/<model>, cursor/<model> or claude/<model>',
    )
    run.add_argument('--output', type=Path, default=None)
    run.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument('--fixture-verdict', choices=['PASS', 'FAIL', 'INVALID', 'MISSING'], default='PASS')
    run.add_argument('--fixture-probe', action='store_true')
    run.add_argument(
        '--fixture-oracle',
        '--fixture-program',
        default='auto',
        help='Task-local reference (auto), its alias, or pass/fail/crash/missing/forbidden',
    )
    run.add_argument(
        '--allow-candidate',
        action='store_true',
        help='evaluate an unadmitted task candidate for review; never a research score',
    )
    verify = commands.add_parser('verify', help='grade a sealed judge JSON artifact without an agent harness')
    verify.add_argument('--submission', type=Path, required=True)
    verify.add_argument('--labels', type=Path, required=True)
    verify.add_argument('--variant', choices=['correct', 'faulty'], required=True)
    verify.add_argument('--output', type=Path, required=True)
    oracle = commands.add_parser(
        'verify-oracle', help='seal external Python and execute it five times on each fresh variant'
    )
    oracle.add_argument('--task', required=True)
    oracle.add_argument('--arm', choices=['oracle_visual', 'oracle_ui'], required=True)
    oracle.add_argument('--submission', type=Path, required=True)
    oracle.add_argument(
        '--references', type=Path, help='named screenshots and manifest captured during permitted authoring'
    )
    oracle.add_argument('--output', type=Path, required=True)
    oracle.add_argument('--allow-candidate', action='store_true')
    test = commands.add_parser(
        'verify-test', help='seal a complete Python test and execute it five times on each fresh variant'
    )
    test.add_argument('--task', required=True)
    test.add_argument('--arm', choices=['test_visual', 'test_ui'], required=True)
    test.add_argument('--submission', type=Path, required=True)
    test.add_argument(
        '--references', type=Path, help='named screenshots and manifest captured during permitted authoring'
    )
    test.add_argument('--output', type=Path, required=True)
    test.add_argument('--allow-candidate', action='store_true')
    gateway = commands.add_parser('_gateway')
    gateway.add_argument('--provider', choices=['fixture', 'openrouter'], required=True)
    gateway.add_argument('--model', required=True)
    gateway.add_argument('--fixture-verdict', choices=['PASS', 'FAIL', 'INVALID', 'MISSING'], default='PASS')
    gateway.add_argument('--fixture-probe', action='store_true')
    gateway.add_argument('--arm', choices=ARM_IDS, default='judge_visual')
    gateway.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    gateway.add_argument('--fixture-oracle', default='auto')
    gateway.add_argument('--fixture-config', type=Path)
    gateway.add_argument('--reasoning-effort', help='selected OpenCode variant that every agent turn must carry')
    broker = commands.add_parser('_broker')
    broker.add_argument('--viewport-width', type=int, default=1280)
    broker.add_argument('--viewport-height', type=int, default=720)
    broker.add_argument('--timezone', default='UTC')
    broker.add_argument('--profile', default='generic')
    broker.add_argument('--preparation', default='{}')
    broker.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    return cli


def known_task(root, task_id):
    from gui_agent_bench.task_package import discover

    tasks = discover(root)
    if task_id not in tasks:
        raise ValueError(f"Unknown task '{task_id}'. Available tasks: {', '.join(sorted(tasks)) or 'none'}")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'build':
            from gui_agent_bench.docker import build

            build(args.root.resolve(), args.task, args.runner, app_only=args.app_only)
        elif args.command == 'run':
            from gui_agent_bench.trial import run
            from gui_agent_bench.runners.registry import spec_for
            from gui_agent_bench.preflight import require_runtime

            check_timeout(args.timeout)
            known_task(args.root.resolve(), args.task)
            agent_spec = spec_for(
                args.model,
                codex_effort=args.codex_reasoning_effort,
                claude_effort=args.claude_effort,
                opencode_variant=args.opencode_variant,
                fixture_probe=args.fixture_probe,
            )
            require_runtime(args.root.resolve(), args.task, args.arm, args.model)
            summary = run(
                args.root.resolve(),
                args.task,
                args.arm,
                args.variant,
                args.model,
                args.output or args.root / 'runs',
                args.timeout,
                args.fixture_verdict,
                args.fixture_probe,
                args.allow_candidate,
                args.fixture_oracle,
                agent_spec=agent_spec,
                credential_source=(
                    args.cursor_auth_dir
                    if args.model.startswith('cursor/')
                    else None if args.model.startswith('claude/') else args.codex_auth_dir
                ),
            )
            from gui_agent_bench.run_plan import health, reference_validation_failed

            if not summary.get('run_directory'):
                return int(summary.get('invalid_or_missing', 0) > 0 or reference_validation_failed(summary))
            return int(health(Path(summary['run_directory']), summary, args.model)['errors'])
        elif args.command == 'verify':
            from gui_agent_bench.verifier.judge import grade

            recorded = args.output / 'metrics.json'
            if recorded.is_file() and json.loads(recorded.read_text()).get('status') != 'planned':
                raise ValueError(
                    f'Output directory already holds a result: {args.output}. Use a new directory for each verification.'
                )
            result = grade(args.submission, args.labels, args.variant, args.output)
            print(json.dumps(result, indent=2))
            # A wrong or invalid submission is an evaluated outcome; verifier errors are operational failures.
            return int(result['status'] == 'verifier_error')
        elif args.command in {'verify-oracle', 'verify-test'}:
            import tomllib
            from gui_agent_bench.task_package import discover, verify
            from gui_agent_bench.verifier.oracle import verify_pair

            known_task(args.root.resolve(), args.task)
            if args.output.exists():
                raise ValueError(
                    f'Output directory already exists: {args.output}. Use a new directory for each verification.'
                )
            task = args.root.resolve() / 'tasks' / args.task
            metadata = tomllib.loads((task / 'task.toml').read_text())['metadata']
            if args.arm not in metadata['eligible_arms']:
                raise ValueError(
                    f"Task {args.task} does not support arm {args.arm}. Eligible arms: {', '.join(metadata['eligible_arms'])}"
                )
            if metadata['status'] == 'candidate' and not args.allow_candidate:
                raise ValueError('This task is a candidate; pass --allow-candidate for a review run')
            verify(task)
            from gui_agent_bench.preflight import require_runtime

            require_runtime(args.root.resolve(), args.task, args.arm, 'external/submission')
            result = verify_pair(
                task,
                args.submission.resolve(),
                args.output.resolve(),
                args.arm,
                references=args.references.resolve() if args.references else None,
            )
            print(json.dumps(result, indent=2))
            return int(result['status'] != 'graded')
        elif args.command == '_gateway':
            if args.fixture_config:
                if args.provider != 'fixture':
                    raise ValueError('Fixture records are forbidden for evaluated model providers')
                from gui_agent_bench.reference_controls import load_record_file

                load_record_file(args.fixture_config, args.fixture_oracle)
            from gui_agent_bench.gateway import serve

            serve(
                args.provider,
                args.model,
                args.fixture_verdict,
                args.fixture_probe,
                args.arm,
                args.fixture_oracle,
                args.platform,
                reasoning_effort=args.reasoning_effort,
            )
        elif args.command == '_broker':
            from gui_agent_bench.broker import serve
            from gui_agent_bench.environment import decode_preparation

            serve(
                (args.viewport_width, args.viewport_height),
                args.timezone,
                args.platform,
                args.profile,
                decode_preparation(args.preparation),
            )
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    'status': 'interrupted',
                    'reason': 'Interrupted; containers and networks of this command were removed.',
                }
            )
        )
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print(json.dumps({'status': 'error', 'reason': str(exc)}))
        return 1
    return 0
