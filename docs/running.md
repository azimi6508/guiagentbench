# Running and inspecting evaluations

## One task and arm

Use the CLI from the repository root:

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio \
  --arm test_ui \
  --model reference/solution
```

`--variant pair` is the default. Generated oracle/test artifacts always execute five times on each state. Judge workflows can also select `--variant correct` or `--variant faulty` for a single-state inspection.

The controller prints the new evaluation directory, progress and a summary. `--output /path/to/output` changes the parent directory; each new evaluation receives its own neutral identifier. Existing run evidence is not overwritten.

`--timeout` controls the per-session agent wall-clock limit for model/scripted runs (default 3,600 s). Step, execution, tool-call and evidence limits, and the 7,200 s limit for a whole paired attempt, are defined in `src/gui_agent_bench/budgets.py` and summarized in [architecture](architecture.md#budgets). There is one attempt per planned cell, with no automatic retries or fallback.

## Plans and preflight

A plan declares models, tasks, arms, repeats and optional scripted controls:

```json
{
  "schema": "run-plan-v1",
  "name": "Web workflow",
  "models": ["reference/solution"],
  "tasks": [{
    "task": "web/webarena-399-profile-bio",
    "arms": ["judge_visual", "judge_test", "oracle_visual", "oracle_ui", "test_visual", "test_ui"],
    "repeats": 1,
    "fixture_program": "profile-bio"
  }]
}
```

```sh
python scripts/bench.py run --plan jobs/web-reference.json --check-plan
python scripts/bench.py run --plan jobs/web-reference.json --preflight-only
python scripts/bench.py run --plan jobs/web-reference.json
```

`--check-plan` validates membership and eligibility without starting an environment. `--preflight-only` checks selected runtime inputs and credentials without model inference. Execution reserves the full plan before attempting any cell and records failures without dropping cells from the denominator. Native evaluations remain sequential.

Reference validation cannot share a plan with evaluated models. A model plan uses identifiers such as `openrouter/<provider>/<model>`, `codex/<model>`, `cursor/<account-model-slug>` or `claude/<anthropic-model-id>`. Choose an explicit model and qualify its runner before execution.

## Result files

A plan run writes:

```text
runs/<run-id>/
  run.json
  resolved-plan.json           # account-runner configuration, when applicable
  evaluations/<cell>/attempt-1/<evaluation-id>/
    plan.json
    summary.json
    trials/<trial-id>/
      workspace-manifest.json
      logs/agent/
      logs/verifier/
      ...
```

A direct single-arm command starts at the evaluation directory rather than adding a parent plan. Exact trial files depend on the selected arm, platform and runner; the reference runner, for example, records no agent workspace or agent logs. The viewer discovers the recorded relationships instead of guessing them from folder names.

`run.json` preserves planned membership, attempts, aggregate status and setup diagnostics. `summary.json` records the evaluation outcome. Verifier directories contain `reward.txt` and richer `metrics.json`/reward records. Generated-artifact evaluations also retain sealed source, reference manifests, paired execution records and image-assertion evidence.

A correct model artifact earns credit through grading. An incorrect result earns zero. Setup, controller, provider and ambiguous failures remain errors needing inspection. An interrupted cell and unstarted cells remain visible. Read the diagnostic causes alongside the score.

## Viewer

```sh
python scripts/view.py runs --port 8080 --no-open
```

Open the printed loopback URL. You can point the viewer at a parent directory or a single run. It provides:

- An overview of runs, task-by-arm outcomes and planned membership.
- Task and evaluation navigation with explicit missing/interrupted entries.
- The agent's timeline, text, tool arguments, responses and screenshots.
- Sealed submissions, reference images, paired execution and image differences.
- Failure causes, source locations and raw evidence files allowed by the viewer's file policy.

The viewer polls for updates and can stay open during a run. It reads the evidence; it does not execute submissions, alter rewards or repair records. Keep its default loopback binding.

## Evidence audit

Audit an evaluation directory after execution:

```sh
python scripts/check_leakage.py --run runs/<evaluation-id>
```

When using `--fixture-probe`, also require the probe evidence:

```sh
python scripts/check_leakage.py --run runs/<evaluation-id> --require-probes
```

For a plan run, pass the run directory itself. Every evaluation is audited and a per-evaluation summary is printed; `--record` also writes the results to `audits.json` in the run directory, where the viewer picks them up as each evaluation's recorded boundary audit:

```sh
python scripts/check_leakage.py --run runs/<run-id> --record
```

The audit checks the recorded workspace, tools, container/network boundaries and evidence consistency for that arm and runner. It compares the recorded mount sources with the run's current location, so audit a run where it was produced, before moving or copying it.

## External submissions

Another harness can author artifacts and use this verifier. Preserve the arm's allowed evidence and tools during authoring, then submit only the sealed artifact and named image references.

A judge artifact is one bounded JSON object. `verify` grades it for the selected state. To evaluate both states externally, obtain independent predictions from the evidence for each state and grade each against its corresponding private label.

`verify-oracle` and `verify-test` execute one sealed Python program five times on each fresh state. UI programs can use structured assertions or visual assertions. Visual programs use coordinate actions and image assertions. If an artifact uses named images, supply the captured reference directory with `--references`; missing or inconsistent references fail validation.

```sh
python scripts/bench.py verify-test \
  --task web/webarena-399-profile-bio --arm test_ui \
  --submission /absolute/path/to/test.py \
  --output runs/external-test
```

The verifier must retain privileged access to the task package. Do not mount the task package, labels or this output directory into the external agent.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `Required Docker images are not built: ...` | Run the build command printed with the message. Images are built per task; `--runner all` adds the Codex, Cursor and Claude Code clients. |
| `Docker is not available` | Start Docker Engine and check that `docker info` works without `sudo` for your user. |
| `Unknown task ...` | `python scripts/tasks.py list` prints the task IDs found under `tasks/`. |
| The web example seems to hang at the start of a run | A fresh Postmill forum instance takes up to about 90 seconds to start, and each evaluation starts several. The run prints its progress per trial. |
| A preflight reports the Android emulator as unavailable | Start the dedicated emulator with `python scripts/mobile_setup.py start`, then `python scripts/mobile_setup.py check --task mobile/markor-note-persistence`. |
| A model run reports missing or stale qualification | A source, task or image changed since the last local qualification. Rebuild and repeat the steps in [runner setup](runners.md). |
| `Viewer could not start ... Address already in use` | Another process uses the port; pass `--port <free port>`. |
| Containers named `gab-...` remain after the controller was killed | The controller removes its containers and networks when a run ends or is interrupted with Ctrl+C. After a hard kill or power loss, remove the leftovers with `docker ps -aq --filter name=^gab- \| xargs -r docker rm -f` and `docker network ls -q --filter name=^gab- \| xargs -r docker network rm`. Do this only while no evaluation is running. |

Run directories are ordinary files owned by your user. Delete a run by deleting its folder; the viewer notices on its next refresh.
