# GUIAgentBench

GUIAgentBench provides isolated execution, evaluation and evidence viewing for GUI testing agents. It supports screenshot judgment, test judgment, oracle generation and complete end-to-end test generation on web, Android and smart-TV applications. A task contains a correct state and a faulty state. The framework keeps the private verifier outside the agent workspace and grades the submitted artifact against both states.

The repository includes the execution controller, tool brokers, sandboxed verifiers, OpenCode/Codex/Cursor/Claude Code runners, run viewer, task-authoring template and the complete AURA web application. It accompanies the paper *GUIAgentBench: A Cross-Platform Benchmark for GUI Test Judgment and Generation* and ships one runnable example task for each domain (web, Android and smart TV); new tasks are added as self-contained packages without framework changes.

## Relationship to the paper

The paper evaluates six model configurations on 800 tasks (400 web, 200 Android and 200 smart TV) with OpenCode as the common agent harness. This repository contains the artifacts the paper cites: the execution and evaluation framework, the evaluation viewer and the AURA application. It also includes three runnable example tasks, one per domain, so the complete workflow can be reproduced on a new machine. The 800-task corpus and the paper's result records are not part of this repository.

The arms, artifact contracts, paired scoring, five executions per version and resource limits implemented here are the ones the paper describes; [architecture](docs/architecture.md) lists them. The Codex, Cursor and Claude Code runners are additional harness integrations. They were not used for the paper's results.

## Evaluation workflows

| Arm | Available evidence | Required output |
| --- | --- | --- |
| `judge_visual` | Goal and recorded screenshots | `judgment.json` containing `PASS` or `FAIL` |
| `judge_test` | Goal, test source and live application; execution of the supplied test is blocked | `judgment.json` predicting the test's verdict |
| `oracle_visual` | Goal, supplied journey and live screenshot/coordinate tools | `oracle.py` with `check(page)` |
| `oracle_ui` | Oracle workflow plus structured UI tools | `oracle.py` with `check(page)` |
| `test_visual` | Goal and live screenshot/coordinate tools | `test.py` with `test(page)` |
| `test_ui` | Test workflow plus structured UI tools | `test.py` with `test(page)` |

UI workflows retain the visual tools. Agents choose which permitted tools to use. A visual workflow never receives a DOM, accessibility tree or UI dump.

An oracle checks the endpoint of the supplied journey. A complete test chooses and performs its own journey. Reference images are captured during authoring and sealed before grading. Generated code executes in a separate sandbox on fresh application states.

## Included examples

| Task ID | Application | Behavior |
| --- | --- | --- |
| `web/webarena-399-profile-bio` | Postmill forum from WebArena (task 399) | A saved profile biography is still shown after reopening the profile |
| `mobile/markor-note-persistence` | Markor on a dedicated Android emulator | Saved note text survives closing and reopening the app |
| `tv/aura-013-caption-preview-size` | AURA TV app | Selecting Large captions enlarges the caption preview |

Task folders classify the domain. AURA is in `tv/` and uses the browser execution driver, preserving all six arms and the same tool capabilities.

Each package contains its public goal, environment recipe, paired variants, private verifier and source provenance. All three expose the six workflows above. See the package's `task.toml` for its source and license information.

## Install

Requirements:

- A Linux x86_64 host with Docker Engine that your user can run without `sudo`.
- Python 3.11 or newer for the host controller.
- About 15 GB of free disk space for the web and AURA examples (the WebArena forum image alone is about 8.5 GB).
- Node.js 22 only for the JavaScript regression checks.
- For the Android example: KVM, Java 17 or newer, the pinned Android SDK and system image (roughly 17 GB more) and a Python 3.11.9 interpreter for the native driver. The web and AURA examples need no emulator.

The [installation guide](docs/setup.md) has the details; [troubleshooting](docs/running.md#troubleshooting) lists common first-run problems.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[visual,codex]'
python scripts/check_structure.py
python -m unittest discover -s tests -v
node tests/viewer_frontend.cjs
```

The last three commands are optional self-checks. The native Android driver has its own pinned environment. Node.js is used only for the frontend and AURA JavaScript tests; the AURA application itself runs with Python alone.

Build the shared runtime and the web example:

```sh
python scripts/bench.py build --task web/webarena-399-profile-bio
```

The web example runs the full Postmill forum from WebArena. Its first build downloads the large, digest-pinned WebArena-Verified image, and each fresh forum instance takes up to about 90 seconds to start.

Build the AURA example:

```sh
python scripts/bench.py build --task tv/aura-013-caption-preview-size
```

The images use the `gui-agent-bench-public-` prefix. The benchmark runtimes pin their base images and runtime dependencies. For Android, follow [the dedicated setup guide](docs/setup.md#android).

## Run a task without a paid model

The privileged reference runner submits a hand-written solution through the normal verifier. It is useful for checking a new installation or task package.

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio \
  --arm test_ui \
  --model reference/solution
```

The command prints the output directory and the paired result. The reference runner bypasses the evaluated agent and remains separate from model results.

A scripted runner exercises the real OpenCode tool path with programmed actions:

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio \
  --arm test_ui \
  --model fixture/scripted \
  --fixture-program profile-bio \
  --fixture-probe
```

Audit the printed evaluation directory:

```sh
python scripts/check_leakage.py --run runs/<evaluation-id> --require-probes
```

Use the actual directory printed by the command. For a multi-task plan, each attempt has its own evaluation directory beneath the parent run.

## View a run

```sh
python scripts/view.py
```

Open [http://127.0.0.1:8080](http://127.0.0.1:8080). The viewer reads `runs/` by default and refreshes live evidence while execution proceeds. A fresh checkout already contains four sample runs of the example tasks (GPT Sol 6.1 and GPT-6 Astra through Codex, Claude Sonnet 5.5 and Opus 5.5 through Claude Code, all at medium effort), so the viewer has something to show before you run anything. `python scripts/check_leakage.py --run runs/<run-id>` re-audits one from its recorded evidence.

To inspect one run or another output directory:

```sh
python scripts/view.py runs/<run-id> --port 8081 --no-open
```

The viewer provides the task-by-arm outcome matrix, per-evaluation status and diagnostics, agent trajectory, screenshots, tool calls, sealed artifacts, paired executions, image comparisons and raw evidence navigation. It reads evidence without changing scores or run files. It serves on the loopback interface.

## Run all example workflows

A plan fixes task, arm, model and repeat membership before execution. The supplied reference plan contains all three examples and six arms each:

```sh
python scripts/bench.py run --plan jobs/examples-reference.json --check-plan
python scripts/bench.py run --plan jobs/examples-reference.json --preflight-only
python scripts/bench.py run --plan jobs/examples-reference.json
```

The three-example plans include the Android task, so their preflight passes only after the [Android setup](docs/setup.md#android). `jobs/web-reference.json` runs just the web example through all six arms and needs Docker alone; start with it. `jobs/examples-scripted.json` exercises the agent tool path. Scripted judges use a constant verdict and are protocol controls; use `reference/solution` to validate private labels and paired correctness.

Every planned evaluation stays in the denominator. Failed or missing artifacts earn zero. An operational error remains an error needing inspection. The controller records one attempt per cell and does not automatically retry failed actions, requests or evaluations.

## Evaluate a model

First qualify the local framework and the chosen runner as described in [runner setup](docs/runners.md). Qualification records are generated locally and bind the source, task inputs, images and retained evidence.

For OpenCode through OpenRouter, supply the provider key through the environment, then choose an explicit model identifier:

```sh
read -rs -p 'OpenRouter API key: ' OPENROUTER_API_KEY; echo
export OPENROUTER_API_KEY
python scripts/bench.py run \
  --task web/webarena-399-profile-bio \
  --arm test_ui \
  --model openrouter/<provider>/<model> \
  --opencode-variant high
unset OPENROUTER_API_KEY
```

`--opencode-variant high` selects the client's `high` model variant, the setting used for every configuration in the paper. `--timeout <seconds>` changes the agent-session limit from its 3,600-second default.

Replace angle-bracket values before running. Keep credentials out of scripts, task files and committed configuration. The inference relay holds the selected credential; evaluated tools do not receive it.

Codex, Cursor and Claude Code use dedicated credentials and their own pinned, restricted clients. Their exact model, account and tool boundaries are checked separately. See [runner setup](docs/runners.md) for build and qualification commands.

## Grade artifacts from another harness

Judgment format:

```json
{"verdict": "PASS", "reason": "The expected behavior is visible."}
```

Grade one judgment against one variant:

```sh
python scripts/bench.py verify \
  --submission judgment.json \
  --labels tasks/web/webarena-399-profile-bio/private/labels.json \
  --variant correct \
  --output runs/external-judgment
```

Grade a Python oracle or complete test on both versions (five fresh runs of each):

```sh
python scripts/bench.py verify-oracle \
  --task web/webarena-399-profile-bio --arm oracle_ui \
  --submission oracle.py --output runs/external-oracle

python scripts/bench.py verify-test \
  --task web/webarena-399-profile-bio --arm test_ui \
  --submission test.py --output runs/external-test
```

Programs using `page.expect_image(...)` also need `--references <directory>` with the named reference captures and manifest produced during permitted authoring. The reference bundle is sealed with the submission. Use a new output directory for each verification.

The external harness must enforce the same arm information barriers. Do not give it the task's `private/`, variants, known solutions or evaluation results. [Public artifact APIs](configs/oracle-api.md) and [complete-test APIs](configs/test-api.md) specify the permitted operations.

## Add your own task

Create a runnable package from an example, then edit its goal, paired fixture and task-local reference programs:

```sh
python scripts/tasks.py new web/my-behavior --from web/webarena-399-profile-bio
python scripts/tasks.py seal web/my-behavior
python scripts/tasks.py validate web/my-behavior
python scripts/tasks.py plan web/my-behavior --output jobs/my-behavior-reference.json
```

Tasks are discovered from their folders. No central registry, runner or viewer edit is needed. An existing app reuses its fixture and image. Every Android task explicitly declares a task-local fixture and APK pin; its variant settings are interpreted by that fixture. The [authoring guide](docs/task-authoring.md) covers each file, app integration, reference solutions and qualification of a new task by itself.

## Run AURA as an application

```sh
python runtime/aura/app/server.py --port 8080
```

Open [http://localhost:8080](http://localhost:8080). AURA includes offline media, local fonts, profiles, a media library, keyboard/D-pad navigation and settings. Its user library stays under `runtime/aura/app/data/`, which is ignored by Git. This standalone application server is separate from the benchmark fixture server. See [AURA usage](docs/aura.md).

## Documentation

- [Installation and native Android setup](docs/setup.md)
- [Running, evaluating and inspecting results](docs/running.md)
- [Runner configuration and local qualification](docs/runners.md)
- [Writing and integrating a task](docs/task-authoring.md)
- [Architecture, scoring and information barriers](docs/architecture.md)
- [AURA application](docs/aura.md)
- [Command reference](docs/commands.md)

## Repository map

| Path | Purpose |
| --- | --- |
| `src/gui_agent_bench/` | Controller, tool brokers, adapters, runners, grading and viewer |
| `runtime/` | Container definitions, pinned driver dependencies and AURA app |
| `configs/` | Arm policies, runner profiles, protocol schemas and public tool contracts |
| `tasks/` | Three complete example packages |
| `jobs/` | Example run plans |
| `runs/` | Four sample model runs of the example tasks; new runs are written here and ignored by Git |
| `templates/task/` | Starting point for a new task |
| `scripts/` | Setup, command entry points, qualification and audits |
| `tests/` | Framework and viewer regression tests |
| `docs/` | Setup, usage, architecture and authoring documentation |

New runs (apart from the four samples), local qualification evidence, credentials, SDKs, emulator state and user libraries are ignored. [Contributing](CONTRIBUTING.md) describes the development checks.

## Citation

If you use GUIAgentBench, please cite:

```bibtex
@misc{azimi2026guiagentbench,
  title  = {{GUIAgentBench}: A Cross-Platform Benchmark for {GUI} Test Judgment and Generation},
  author = {Azimi, Mohammad Yusaf and Yilmaz, Cemal},
  year   = {2026},
  note   = {Execution and evaluation framework, viewer and AURA: \url{https://github.com/azimi6508/guiagentbench}}
}
```

## License

The framework is licensed under [Apache 2.0](LICENSE). AURA retains its [MIT license](runtime/aura/app/LICENSE). Third-party code, fonts and media retain the notices listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
