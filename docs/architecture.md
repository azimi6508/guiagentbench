# Architecture and contracts

The host controller owns task registration, provisioning, run membership, evidence persistence and grading. Evaluated agents receive a purpose-built workspace and an allowlisted tool interface. The application container, agent, inference relay, browser broker and generated-code executor have separate responsibilities.

## Task domain and execution platform

A task's domain determines its folder and viewer grouping. Its execution platform selects the driver, tool policy and runtime checks. `metadata.domain` defaults to `metadata.platform` when omitted. AURA declares domain `tv` and platform `web`, so it remains a six-arm browser-rendered TV application. Remote-only tasks using the `tv` execution platform retain their remote-key contract. The controller, preflight and audits use the declared execution platform rather than inferring tool capabilities from the folder name.

## Execution flow

1. Parse the task and arm policy and reserve the planned evaluation cells.
2. Check runtime inputs, images, credentials and local qualification.
3. Provision the selected application state on an isolated network.
4. Capture the arm's public inputs or prepare its supplied journey.
5. Materialize only allowlisted workspace files and expose the arm's tools.
6. Run the selected agent and retain the trajectory and tool ledger.
7. Seal the submitted artifact and any chosen image references.
8. Grade judgments, or execute generated code five times on fresh correct and faulty states.
9. Write rewards, diagnostics and summaries; inspect them in the viewer.

## Information barriers

The six arm IDs are fixed in `src/gui_agent_bench/arms.py`. The policies in `configs/arms/` declare each arm's readable files, writable output paths, tools and environment allowlists. Workspace materialization copies explicit public files; it never mounts the repository or canonical task tree into the agent.

`private/`, fault definitions, labels, known solutions, verifier logs and prior results stay outside evaluated workspaces. The trusted controller may read these files to provision and grade a trial. The evaluated model cannot.

Visual workflows receive screenshots and coordinate actions. UI workflows are a superset: they retain coordinate actions, screenshots and reference-image assertions while adding permitted DOM/accessibility structure and role/name operations. Native hover remains unavailable. Judge-test agents can inspect the public test source and interact with the application but cannot execute that test or the private grader.

Process and network boundaries enforce the contract alongside file allowlists and tool validation. The inference relay holds the selected provider credential. Generated code runs under a separate executor without provider credentials, private labels or writable verifier logs. Browser execution is mediated by the broker rather than unrestricted browser evaluation.

## Artifact contracts

Judgments are bounded JSON objects with an uppercase `PASS` or `FAIL` verdict and an optional reason. The submitted file is `output/judgment.json`.

An oracle exports `check(page)` from `output/oracle.py`. A complete test exports `test(page)` from `output/test.py`. Both use the restricted page API. Oracles are read-only during grading because the trusted supplied journey already reaches the endpoint. Complete tests perform their own actions from a fresh initial state.

A generated program must establish a positive precondition before behavioral assertions. A precondition authored by the model is still an assertion by the model; its failure alone does not establish an environment defect. Complete tests must perform their own journey. Execution-operation failures prevent credit even if submitted code catches the exception.

[Oracle API](../configs/oracle-api.md), [test API](../configs/test-api.md), [UI API](../configs/ui-api.md), [visual API](../configs/visual-api.md) and [native API](../configs/mobile-api.md) contain the exact operations and argument contracts.

## Image assertions

The author chooses named screenshots and comparison parameters through permitted tools. Reference captures are frozen before paired grading; the executor cannot learn or replace a baseline. Parameters such as regions, masks and thresholds belong to the sealed artifact. The verifier records captures, comparison results and difference images.

## Scoring and errors

Judge accuracy compares each prediction with its private variant label. A paired result requires both predictions to be correct. A sealed oracle or complete test is executed five times on each version, each time on a fresh application state, with correct and faulty runs interleaved. It earns paired credit only when all five correct-version runs pass, all five faulty-version runs fail behaviorally, and every run records the same assertion definitions (and, for complete tests, the same action and assertion trace). An unusable run or a disagreement between runs of the same version earns zero (`unstable_execution`). A crash, malformed program or failed environment operation is not a successful fault detection.

## Budgets

| Responsibility | Agent steps | Agent session | Evaluation limit |
| --- | --- | --- | --- |
| Judgment (`judge_*`) | 100 | 3,600 s | 5 s per verdict check |
| Oracle generation (`oracle_*`) | 150 | 3,600 s | 60 s per execution |
| Complete-test generation (`test_*`) | 200 | 3,600 s | 360 s per execution |

One paired attempt (environment preparation, every agent session and the evaluation of its artifact) is limited to 7,200 s of wall-clock time; later sessions and executions receive only the remaining time. The values live in `src/gui_agent_bench/budgets.py`; `--timeout` sets the agent-session limit for a run (1 to 7,200 s; default 3,600 s).

Planned denominators remain fixed. Missing, invalid, abstaining, interrupted and failed evaluations contribute zero credit. A sweep continues after an individual evaluation error while retaining that cell and its evidence. There are no automatic trial retries.

Run status separates completion from correctness. `complete` means execution finished without unresolved operational errors; individual model outcomes can still earn zero. `completed_with_errors` needs inspection. `interrupted` records a stopped run, and `preflight_failed` records setup failure before execution.

Versioned diagnostics record cause, phase, operation and safe evidence locations. Unknown causes remain unknown. Raw exceptions, credentials, private UI text and hidden task labels are not added to public tool error replies.

## Native operation

The Android adapter targets a dedicated emulator with pinned system image, APK, viewport, locale, driver dependencies and host interpreter. Native trials run sequentially. Capability-scoped relays keep Android access out of evaluated processes. Device identity and scope checks guard each operation. Reset restores the declared application state without replaying a failed action.

The native platform and task environment have separate contracts. The platform verifies Android and automation dependencies, clears common device/app state, mediates GUI operations and enforces package scope. Each task declares its APK pin and a task-local `Application` fixture for setup, launch, restart, fault behavior and optional private checking. Variant JSON is passed unchanged to that fixture's constructor; its keys have no meaning to the platform driver.

Only the trusted host fixture receives this configuration. The native relay transports operations and has no task/configuration mounts. Task discovery and validation read fixture source as data; execution loads reviewed fixture code only after the task manifest and installed application are verified. Generated agent submissions never enter this loading path.

## Readiness and recovery

Preparation checks initial landmarks and bounded loading prerequisites, separately from behavioral assertions. Observations stay available during animation or loading. The framework does not infer success from global pixel stability or network quiet.

If trusted native scope diagnostics report that authoring left the admitted app, the recovery contract permits one reset for that interruption, at most three per authoring session, within the existing budget. It never repeats the failed action. Unknown failures, failed recovery and security/evidence failures remain fatal. See [failure API](../configs/failure-api.md).

## Reference and scripted controls

`reference/solution` is privileged known-solution validation. It bypasses model inference and uses normal grading and isolated paired execution. It is always kept separate from model scores.

`fixture/scripted` drives the real OpenCode integration path with programmed responses. Its judges emit a constant verdict, while generated-artifact controls exercise their hand-written journeys. Forbidden-access probes test file, tool and network denials. These controls check the framework's behavior; they do not measure a model.
