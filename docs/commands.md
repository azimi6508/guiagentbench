# Command reference

Run commands from the checkout root with the host environment activated. `python scripts/bench.py --help` and each subcommand's `--help` show the supported flags; plan options are listed by `python scripts/bench.py run --plan <json> --help`.

| Command | Purpose |
| --- | --- |
| `build --task <id> --app-only` | Build only the selected application |
| `build --task <id>` | Build shared runtime and selected application images |
| `build --runner opencode\|codex\|cursor\|claude\|all` | Select agent images to build |
| `run --task <id> --arm <arm> --model <id>` | Execute one task/arm evaluation |
| `run --plan <json> --check-plan` | Validate fixed membership without execution |
| `run --plan <json> --preflight-only` | Check selected prerequisites without inference |
| `run --plan <json>` | Execute the planned cells sequentially |
| `verify --submission <json> --labels <json> --variant correct\|faulty --output <dir>` | Grade one judge artifact |
| `verify-oracle --task <id> --arm oracle_visual\|oracle_ui --submission <py> --output <dir>` | Grade an oracle (five runs per state) |
| `verify-test --task <id> --arm test_visual\|test_ui --submission <py> --output <dir>` | Grade a complete test (five runs per state) |
| `view [directory] --port <port> --no-open` | Start the loopback evidence viewer |

Use `--references <dir>` for generated programs with named image assertions. The directory contains the author-selected PNG captures and manifest. Use `--root <checkout>` before the subcommand when the package is installed outside an editable checkout.

Common run options:

| Option | Meaning |
| --- | --- |
| `--variant pair\|correct\|faulty` | Select paired or single-state judgment; generated code requires pair |
| `--timeout <seconds>` | Authoring wall-clock limit, checked against the budget contract |
| `--output <parent>` | Parent for a newly created, neutrally named run directory |
| `--fixture-program <name>` | Explicit trusted scripted control |
| `--fixture-probe` | Add forbidden-access probes; scripted runner only |
| `--allow-candidate` | Explicitly allow packages whose metadata uses candidate status |
| `--opencode-variant low\|medium\|high` | OpenCode model variant (reasoning effort) for `openrouter/` models; default none |
| `--codex-auth-dir <external-dir>` | Dedicated Codex saved-login directory |
| `--codex-reasoning-effort low\|medium\|high\|xhigh` | Exact Codex effort selection |
| `--cursor-auth-dir <external-dir>` | Dedicated Cursor CLI login directory |
| `--claude-effort low\|medium\|high\|xhigh\|max` | Claude Code effort level (default `medium`) |

Setup and checks:

```sh
python scripts/check_structure.py
python scripts/pin_sources.py
python scripts/mobile_sdk.py
python scripts/mobile_setup.py prepare --python /path/to/python3.11
python scripts/mobile_setup.py start
python scripts/mobile_setup.py install-app --task <id>
python scripts/mobile_setup.py check --task <id>
python scripts/mobile_setup.py stop
python scripts/qualify_framework.py --install
python scripts/check_leakage.py --run <evaluation-directory> --require-probes
python scripts/check_leakage.py --run <plan-run-directory> --record
```

`pin_sources.py` refreshes identities after an intentional edit. It does not qualify the changed runtime. Qualification commands retain evidence under local ignored directories and install certificates only after their controls pass.

Run statuses are described in [architecture](architecture.md#scoring-and-errors). A zero-credit model outcome is a completed evaluation and exits 0. Preflight failure and unresolved operational errors exit 1; an interrupted command (Ctrl+C or a termination signal) removes its containers and exits 130. A reference solution that does not earn full credit, or an invalid result from a scripted control, exits 1. `verify-oracle` and `verify-test` exit 0 only when the program was graded.

Task package commands (run with `python scripts/tasks.py`):

| Command | Purpose |
| --- | --- |
| `list` | Discover task folders |
| `new <id> --from <example-id>` | Create a runnable starting point without overwriting |
| `seal <id>` | Refresh reviewed package file hashes |
| `validate <id>` | Check metadata, files, provenance and reference programs |
| `plan <id> --output <json>` | Create a plan for every eligible arm |

Use `--model <model-id>` and `--arms <arm> ...` with `plan` to select its model and workflows. `qualify_framework.py --task <id> --install` qualifies one package independently. See [task authoring](task-authoring.md) for the complete workflow.
