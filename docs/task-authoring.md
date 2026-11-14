# Authoring and integrating a task

A task is a folder under `tasks/<domain>/<id>/`. The controller discovers these folders on each invocation. Adding a behavior does not require editing a task registry, runner, broker, grader or viewer. Its reference programs, preparation journey, fixture configuration and provenance live together in the package.

Use an existing example as a runnable starting point. Reusing the same application also reuses its image and reset adapter. A new application needs a fixture that implements the documented reset/session protocol; Android applications additionally supply a trusted setup hook. This is application setup work, done once and reused across its tasks.

## Create a runnable starting point

From the repository root, with the host environment activated:

```sh
python scripts/tasks.py list
python scripts/tasks.py new web/my-behavior --from web/webarena-399-profile-bio
python scripts/tasks.py validate web/my-behavior
```

The command copies only the source package's verified files, assigns the new identity and creates a fresh file manifest. It refuses to overwrite an existing task. At this point the new package still tests the original example behavior. Change the files below to define your own behavior.

For AURA, use `python scripts/tasks.py new tv/my-behavior --from tv/aura-013-caption-preview-size`. For another Markor behavior, use `--from mobile/markor-note-persistence`. Task IDs use lowercase letters, digits and hyphens, prefixed by `web/`, `mobile/` or `tv/`.

## Add an already authored package

Place the complete package at `tasks/web/<id>/`, `tasks/mobile/<id>/` or `tasks/tv/<id>/`. AURA belongs to the TV domain under `tasks/tv/`. The `domain` and `task_id` in `task.toml` match the folder; `platform` selects the execution driver. If `domain` is omitted, it defaults to `platform`. The AURA example declares `domain = "tv"` and `platform = "web"`, retaining browser-based screenshot, coordinate and structured UI tools across all six arms. Include the package manifest, variant settings, public journey, private verifier and reference programs described below.

The next command discovers the folder automatically. Build its declared application image and prepare the platform dependencies, then select the new ID:

```sh
python scripts/tasks.py validate web/my-behavior
python scripts/bench.py build --task web/my-behavior --app-only
python scripts/bench.py run --task web/my-behavior --arm test_ui --model reference/solution
```

Use `seal` after reviewing intentional package edits. Shared runtime images are built once as described below. For a batch, generate a plan containing the new ID with `tasks.py plan`. Existing plans keep their explicit membership; adding a folder does not change them. A new application supplies its task-local fixture or Android setup hook, while the framework, runner and viewer stay shared.

## What to edit

| File | Purpose and changes |
| --- | --- |
| `instruction.md` | Public user goal, observable expected behavior and normal initial conditions |
| `task.toml` | Domain, execution platform, identity, eligible arms, provenance, image, viewport and integration settings. The `[agent]`, `[verifier]` and `[environment]` tables are descriptive; the controller reads `[metadata.runtime]` and `[integration]`, and the budgets come from `src/gui_agent_bench/budgets.py` |
| `variants/correct/settings.json` | Reproducible correct application state |
| `variants/faulty/settings.json` | Same public setup with one explicit faulty behavior |
| `environment/` | Task-local application fixture and build recipe, when needed |
| `private/test_source.py` | Public journey source used by judge-test and oracle workflows; oracle setup stops before the behavioral checkpoint |
| `private/gold_test.py` | Trusted capture/journey and behavioral verification entry point |
| `private/labels.json` | Exactly `{"correct":"PASS","faulty":"FAIL"}` |
| `private/reference.json` | Trusted reference journey, image regions and paths to reference programs |
| `solution/oracle_visual.py`, `solution/oracle_ui.py` | Known-solution programs exporting `check(page)` |
| `solution/test_visual.py`, `solution/test_ui.py` | Known-solution complete tests exporting `test(page)` |
| `arms/judge_visual.md`, `arms/judge_test.md` | Task-specific public judge instructions |
| `lineage/` | Source hashes, upstream notices, adaptation notes and package manifest |
| `tests/test.sh` | Isolated judge verifier entry point (normally reusable unchanged) |

The supplied journey in `private/test_source.py` exports `test_behavior(page, checkpoint)`. Call `checkpoint(description)` for each declared screenshot, then use ordinary `assert` statements for the expected behavior. A normal return means PASS; returning `False` does not fail a Python test. An assertion mismatch means FAIL only after every checkpoint has been captured. Setup, navigation and missing-frame errors remain errors. The default is three checkpoints. For another count, set the source's `CHECKPOINTS` constant and `metadata.checkpoints` to the same number.

Shared oracle/test instructions come from `configs/`; their capability boundaries stay the same for new tasks. Keep task-specific assertions in the package. The reference runner reads trusted solutions as data and submits them to the isolated verifier. It never executes generated submissions in the controller.

Record source, upstream ID, URL, revision, license and transformation notes in `[metadata]`. For original tasks, identify your own source repository/revision and license. Preserve third-party notices. Avoid private accounts, personal data and network-dependent seed data.

`status = "example"` is runnable. `status = "candidate"` requires `--allow-candidate` for review runs. `research_core` is provenance metadata and does not produce a model performance claim.

## Browser application contract

The application serves `http://app:8000/` on an internal network. The controller mounts the selected variant at `/settings.json`, read-only. The container runs as a non-root user with a read-only root filesystem; use `/tmp` for temporary state. An application with a database or other on-disk state can set `app_writable_root = true` under `[metadata.runtime]`: each trial then gets its own disposable writable container layer, and every other restriction still applies. The WebArena forum example does this. Do not expose host ports or require external services.

The browser adapter creates a fresh context and session for each reset. Implement the session handshake and stale-session rejection shown in `tasks/web/webarena-399-profile-bio/environment/app.py` or `runtime/aura/server.py`. The server must acknowledge reset before interaction and reject requests from an earlier session. Both variants must provide identical public setup, viewport and initial affordances. Read [the environment contract](../configs/environment-api.md) alongside the example server.

Default task-local builds use `environment/Dockerfile` with `environment/` as context. Declare a tagged image under `[metadata.runtime]`:

```toml
[metadata.runtime]
app_image = "my-gui-app:1"
app_memory_mb = 256
reference_timeout_sec = 60
viewport_width = 1280
viewport_height = 720
timezone = "UTC"
app_writable_root = false

[integration.web]
ready = [{ role = "button", name = "Settings" }]
fixed_clock = "2026-10-12T18:00:00+00:00"
wait_for_fonts = true
reset_timeout_sec = 30
```

Use a distinct image tag if you change application code. A new behavior using the same application image can keep its existing tag.

Browser preparation is declared by the task, never registered in the framework. Every field of `[integration.web]` is optional:

| Field | Meaning |
| --- | --- |
| `ready` | Up to eight landmarks that must be visible before the initial page counts as ready. Each is `{ role, name }` (exact accessible name) or `{ test_id }`. |
| `fixed_clock` | ISO 8601 time with UTC offset; pins the browser wall clock while timers stay real. |
| `wait_for_fonts` | Wait for the initial web-font load within the readiness deadline. |
| `reset_timeout_sec` | Bound for the application's `POST /reset` (1–300, default 30). Raise it for apps that restore large snapshots. |

Without the table, the controller performs a normal reset and bounded readiness. Readiness applies to the initial page only; put behavior-specific journey waits and positive initial preconditions in your task's tests. The two browser examples show both forms: the WebArena forum declares two landmarks and a longer reset window for its database startup; AURA declares a landmark, a fixed clock and font loading.

A shared app can declare `build_context = "checkout"` and `dockerfile = "runtime/aura/Dockerfile"` in `[integration]`. This is metadata, not a change to `docker.py`. The AURA task uses this arrangement. Its variants each embed the same `spec` object (`id`, `seed`, `mutation`) with only `fault` differing. Define the seed state and fault in those task-owned settings. `private/spec.json` records the behavior's explanatory source. New AURA tasks using the fixture's supported settings/mutations need no shared app image changes.

Record where the application and the behavior come from in `lineage/` and `task.toml`: upstream URLs, revisions or image digests, and the license notices of anything you copy. The WebArena example keeps the selected upstream task definition, the controller before and after its fault hook, and both upstream licenses. Redact credentials from copied upstream files. `tasks.py seal` records a hash of every package file, and validation fails if any file changes afterwards.

## Reference control format

`private/reference.json` names the programs and the visual journey used by trusted validation:

```json
{
  "schema": "task-reference-v1",
  "platform": "web",
  "viewport": [1280, 720],
  "journey": [{"action": "click", "x": 100, "y": 100}],
  "regions": {
    "false": [[0, 0, 80, 40], [0, 0, 80, 40], [100, 100, 200, 200]],
    "true": [[0, 0, 80, 40], [0, 0, 80, 40], [100, 100, 200, 200]]
  },
  "programs": {
    "oracle_visual": "solution/oracle_visual.py",
    "oracle_ui": "solution/oracle_ui.py",
    "test_visual": "solution/test_visual.py",
    "test_ui": "solution/test_ui.py"
  }
}
```

Replace illustrative coordinates with regions verified against your app. Each region is `[left, top, right, bottom]`. The `false` key means oracle preparation; `true` means complete-test preparation. Each set contains initial precondition, final precondition and behavioral region. These keys do not identify application variants.

Optional `initial_delay` and `action_delay` are bounded seconds for scripted controls; `capture_ui: true` lets a UI reference choose image captures. Visual reference actions use the public coordinate/key vocabulary, never hidden selectors. Remote-only TV packages use the supported remote keys and four non-UI arms.

Capture reference images during authoring, then freeze them before paired execution. Keep comparison regions, tolerances and masks explicit in the submitted program. Do not learn a baseline during grading. See [visual assertions](../configs/visual-api.md), [oracle API](../configs/oracle-api.md), and [complete-test API](../configs/test-api.md).

Private reference files go only to the privileged reference helper or scripted fixture provider. Real evaluated models receive the arm's positive workspace allowlist. The task directory, variants, reference programs, gold verifier and labels are never mounted into the evaluated agent.

## Remote-only TV applications

A TV-domain browser application can use `domain = "tv"` and `platform = "web"`, as AURA does, with all six arms. Use `platform = "tv"` for a remote-only interface: `judge_visual`, `judge_test`, `oracle_visual` and `test_visual`. The remote interface exposes screenshots and the eight keys in [the TV API](../configs/tv-api.md).

For a task-owned remote application, use `environment_profile = "tv"` and package its server, screen assets and any transition model in its application image. The framework mounts only that task's selected `/settings.json`; it has no shared recording catalog or model pin. The app runs as a non-root user on the isolated network and serves `POST /call` on port 8000. Requests are `{"operation": "ready", "arguments": {}}`; successful responses are `{"value": ...}`.

| Operation | Arguments | Returned value |
| --- | --- | --- |
| `ready` | `{}` | `true` when initial assets are verified |
| `reset` | `{}` | `null`, after the initial state is restored |
| `screenshot` | `{}` | Base64-encoded PNG at the declared viewport |
| `step` | `{"action":"press","key":"ok"}` | `null`, after one permitted key action |

`reference_check` is an optional trusted-gold operation returning a boolean. It is absent from evaluated tools. Keep goal checks and faulty behavior inside the task's environment and private verifier. Reference journeys and image regions use the same task-local `private/reference.json` format with `"platform": "tv"`. Add, seal, build and qualify the package with the same task commands; no framework registry or corpus directory is needed.

## Android: task-owned fixtures

Every Android task declares its application fixture and APK pin. The shared platform owns the SDK, emulator, UI transport, device cleanup, foreground scope and evidence. Application setup, seed data, restart behavior, fault injection and private behavioral checks belong to the task package.

```toml
[integration]
environment_profile = "mobile"
native_application = "environment/application.py"
native_package = "org.example.app"
native_apk_sha256 = "<64 lowercase hex characters>"
native_apk_url = "https://example.org/releases/application.apk"
```

`native_apk_url` is optional when the operator supplies an APK file or the declared app is already installed with the correct pin. Use a credential-free HTTPS URL. The platform lock covers the Android system and automation dependencies; the task separately pins the installed application. Platform preparation and startup do not download or install a default application.

Copy `templates/task/environment/native-application.py.example` into the package. Its interface is:

| Method | Owner and responsibility |
| --- | --- |
| `Application(settings)` | Validate and interpret this task's configuration |
| `reset(device, adb)` | Set up permissions/onboarding, seed data and open the initial screen after common app/device state has been cleared |
| `launch(device, adb)` | Open the declared application's task entry point |
| `reload(device, adb)` | Perform its save/close/reopen flow and any explicitly authored faulty transformation |
| `check(device, adb)` | Optional private boolean check invoked by trusted gold code through `page.check_fixture()` |

The framework passes `settings.json` only to the fixture constructor. Its contents are opaque to the shared driver. Both variants use the same fixture source; the task defines their configuration schema and differences. The example's `lose_note_on_restart` flag is interpreted in `tasks/mobile/markor-note-persistence/environment/application.py`. Note paths, expected text, onboarding and truncation are defined there and in its task files.

Another task on the same app can reuse or adapt that fixture within its package. A new app supplies its own fixture; it does not add branches or app identifiers to the platform driver. The shared driver calls lifecycle methods, enforces the declared package scope and exposes the same permitted GUI operations. A fixture does not add evaluated tools.

Fixture code is reviewed, trusted environment code running in the dedicated host driver. It is distinct from generated submissions, which remain untrusted and run only in the separate executor. Discovery and static validation never import the fixture. Before loading it, the controller verifies the package manifest and installed APK. Runtime evidence binds its source, selected settings and application pin. The relay container has no task files or variant settings mounted, and evaluated agents receive neither fixture code nor configuration. Private callbacks are absent from evaluated tool catalogs.

Prepare/start the Android platform from [setup](setup.md#android), then explicitly install the task's app:

```sh
python scripts/mobile_setup.py install-app --task mobile/my-behavior
```

This downloads the task-declared URL into an ignored cache and checks its SHA256. To use an existing APK file instead:

```sh
python scripts/mobile_setup.py install-app \
  --task mobile/my-behavior --apk /absolute/path/to/app.apk
python scripts/mobile_setup.py check --task mobile/my-behavior
```

Preflight and every native driver startup verify the installed application against the task's pin. Keep native trials sequential on the dedicated emulator. Record APK source, revision, license and redistribution notices in the task's provenance.

## Seal, validate, build and run

After editing, review your files and refresh their manifest:

```sh
python scripts/tasks.py seal web/my-behavior
python scripts/tasks.py validate web/my-behavior
python scripts/tasks.py plan web/my-behavior --output jobs/my-behavior-reference.json
python scripts/bench.py build --task web/my-behavior --app-only
python scripts/bench.py run --plan jobs/my-behavior-reference.json --check-plan
python scripts/bench.py run --plan jobs/my-behavior-reference.json --preflight-only
python scripts/bench.py run --plan jobs/my-behavior-reference.json
```

Build the shared runtime once first with `python scripts/bench.py build --task web/my-behavior`; use `--app-only` for later application rebuilds. If only variant settings, a journey or reference programs change, shared images need no rebuild. Task-local inputs are staged afresh per attempt.

`seal` hashes files; it does not prove correctness. Validate every eligible arm, inspect both correct/faulty executions and their screenshots, and check that the observed fault matches the public goal. Investigate reset failures, unexpected positives and ambiguous outcomes before using the task.

Qualify just the new package without requiring unrelated Android tasks:

```sh
python scripts/qualify_framework.py --task web/my-behavior --install
```

This performs static/unit/viewer checks, every declared reference arm, real scripted-agent boundary probes and forbidden execution controls. It performs no paid model inference. Evidence stays in `.local/qualification/`, with a separate source/image/task/evidence-bound certificate per package under `runtime/qualification/`. New task folders do not invalidate another task's certificate. Changes to that task, shared sources or relevant images require fresh qualification.

Each included package also provides `solution/solve.sh`. For example, `sh tasks/tv/aura-013-caption-preview-size/solution/solve.sh test_ui` runs that package's trusted reference. The shortcut derives the task ID from its own folder, so cloned packages use their new identity. Extra run options can follow the arm, such as `--output /absolute/path/to/output`.

A generated plan defaults to `reference/solution`. To evaluate a model, create another plan with `--model openrouter/<provider>/<model>` or use the single-task command in [running](running.md). Complete the chosen runner's qualification as described in [runners](runners.md).

```sh
python scripts/view.py runs/<run-id> --no-open
python scripts/check_leakage.py --run <evaluation-directory>
```

The viewer discovers evaluations from their run records; adding a task needs no viewer registration. Audit each evaluation, not only the parent plan directory. Use `--require-probes` for scripted probe runs. Keep all failures and fixed denominators; authoring or setup errors earn no credit and do not become model failures by assumption.
