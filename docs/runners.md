# Runners and local qualification

The controller selects one runner from an explicit model identifier. Each evaluated session stays bound to that model and its recorded tool profile. Automatic model fallback, request replay and trial retries are disabled.

| Identifier | Execution path | Credential source |
| --- | --- | --- |
| `reference/solution` | Privileged known solution through normal grading | None |
| `fixture/scripted` | Real OpenCode client with programmed provider replies | None |
| `openrouter/<provider>/<model>` | OpenCode behind an inference relay | `OPENROUTER_API_KEY` environment variable |
| `codex/<model>` | Restricted Codex app-server and guarded MCP bridge | Dedicated external saved ChatGPT login |
| `cursor/<account-model-slug>` | Pinned Cursor CLI, inference relay and MCP bridge | Dedicated Cursor CLI login or `CURSOR_API_KEY` |
| `claude/<anthropic-model-id>` | Pinned Claude Code CLI, credential-injecting relay and MCP bridge | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` environment variable |

The Codex, Cursor and Claude Code runners drive each vendor's own client with your account. Check that your plan and the provider's terms allow automated use before evaluating with a subscription login; an API key is the unambiguous choice where the runner supports one.

## Local framework qualification

Build the three application images and shared runtime, prepare/start the Android example, and run:

```sh
python scripts/qualify_framework.py --install
```

The qualifier runs the structure/unit/viewer checks, known-solution pairs, scripted agent probes and forbidden execution controls. It performs no model inference. Every control runs once and keeps its evidence. A failed control stops qualification; no certificate is installed.

The default output is `.local/qualification/<id>/`. A passing installation writes one certificate per task under `runtime/qualification/`, binding source identities, relevant image IDs, that task package and complete evidence trees. Use `--task web/my-behavior` to qualify only a new task; repeat `--task` to select several. These generated local files are ignored by Git. Keep the evidence in place for the certificate to remain valid.

A source, policy, task or runtime-image change requires fresh qualification. `scripts/pin_sources.py` updates source identities after an intentional edit; it does not install a certificate or make a failed control pass.

## OpenCode and OpenRouter

Build the default images. The OpenCode version and provider transport are pinned by the agent Docker recipe. Supply `OPENROUTER_API_KEY` only through the environment. The relay receives the selected credential and model; evaluated tool processes do not.

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio --arm test_ui \
  --model openrouter/<provider>/<model> --timeout 600
```

`--opencode-variant low|medium|high` selects the pinned client's model variant, as the paper's evaluation did with `high`. The client then sends the OpenAI-compatible `reasoning_effort` field on every agent turn; the relay forwards it and rejects an agent turn that does not carry the selected value, and the evidence audit checks the same. The provider maps the field to its own reasoning control, so the same label does not imply the same computation across providers. Without the option no variant is requested and the provider's default applies.

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio --arm test_ui \
  --model openrouter/<provider>/<model> --opencode-variant high
```

Use the exact provider/model slug you intend to evaluate. Confirm your account's billing settings before a paid run. The framework does not enable account top-ups or change account spending limits.

## Restricted Codex

Build the optional images:

```sh
python scripts/bench.py build --runner codex --task web/webarena-399-profile-bio
```

The runtime pins Codex, protocol schemas and hooks. Model metadata is supplied locally: put a Codex model-catalog file for each model you evaluate at `configs/codex/models/<model>.json`. Catalogs are not distributed, and the runner rejects one that does not keep the restricted tool fields listed in [that folder's README](../configs/codex/models/README.md). The bridge exposes only the selected arm's tool catalog. Its hooks veto forbidden tools and compaction. The agent has a separate network boundary and credential handling.

Use a dedicated external directory owned by your user, with directory mode `0700` and the saved-login `auth.json` mode `0600`. Do not put it inside this checkout, a task package, an image or a run. Sign in with the official Codex CLI 0.162.0 using file credential storage:

```sh
install -d -m 700 /absolute/path/to/dedicated-login
CODEX_HOME=/absolute/path/to/dedicated-login \
  codex -c 'cli_auth_credentials_store="file"' login
chmod 600 /absolute/path/to/dedicated-login/auth.json
```

The runner stages only the allowed login file and exports native refresh changes atomically.

Linux nested sandboxing uses the pinned agent-only security policy under `runtime/codex/security/`. A host administrator loads the named AppArmor profile explicitly:

```sh
sudo apparmor_parser -r runtime/codex/security/apparmor.profile
```

The profile is not persistent; load it again after a reboot. The runner verifies the policy and fails if it is missing; it does not fall back to a privileged or unconfined container. See [the policy description](../runtime/codex/security/README.md).

Qualify a model that has a local catalog with synthetic provider responses and dedicated-login startup:

```sh
python scripts/qualify_codex.py \
  --output .local/codex-boundary \
  --fixture-model <model-with-local-catalog> \
  --codex-auth-dir /absolute/path/to/dedicated-login \
  --reasoning-effort medium \
  --platforms web mobile \
  --install-boundary-certificate
```

Every qualification command needs a new `--output` directory; choose another name when you qualify again. A certificate covers one model and one effort, so pass the `--reasoning-effort` you will evaluate.

To add another exact model, add its restricted catalog to `configs/codex/models/` and validate it through these controls. Do not reuse a certificate for another model, effort, platform or tool profile.

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio --arm test_ui \
  --model codex/<model-with-local-catalog> \
  --codex-auth-dir /absolute/path/to/dedicated-login \
  --codex-reasoning-effort medium --timeout 600
```

## Cursor

```sh
python scripts/bench.py build --runner cursor --task web/webarena-399-profile-bio
```

For a dedicated saved login, use an external directory selected with `--cursor-auth-dir`. The startup helper downloads the pinned Cursor CLI into the ignored `.cursor-build/` directory. Create the dedicated login context first, then list the account's models with a second call:

```sh
python scripts/check_cursor_startup.py \
  --cursor-auth-dir /absolute/path/to/dedicated-cursor-login --login
python scripts/check_cursor_startup.py \
  --cursor-auth-dir /absolute/path/to/dedicated-cursor-login
```

Alternatively, set `CURSOR_API_KEY` through the environment. Use the explicit account model slug shown by model inventory. `Auto` and implicit default selection are rejected.

```sh
python scripts/qualify_cursor.py \
  --output .local/cursor-boundary \
  --model <explicit-account-model-slug> \
  --cursor-auth-dir /absolute/path/to/dedicated-cursor-login \
  --platforms web mobile \
  --install-boundary-certificate
```

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio --arm test_ui \
  --model cursor/<explicit-account-model-slug> \
  --cursor-auth-dir /absolute/path/to/dedicated-cursor-login \
  --timeout 600
```

## Claude Code

The runner pins Claude Code 2.1.323 (the native `linux-x64` build from the npm registry, checked by SHA-256). Build its three images:

```sh
python scripts/bench.py build --runner claude --task web/webarena-399-profile-bio
```

Supply exactly one credential through the environment. `ANTHROPIC_API_KEY` bills the API account; `CLAUDE_CODE_OAUTH_TOKEN` (created with `claude setup-token`) uses a Claude subscription. Setting both is rejected so the billing mode is always explicit.

```sh
read -rs -p 'Anthropic API key: ' ANTHROPIC_API_KEY; echo
export ANTHROPIC_API_KEY
```

Qualify the boundary for an explicit model ID and effort. The controls run the real client against the production relay and a scripted upstream with a synthetic credential; with `--model`, a single `GET /v1/models` request checks that the ID resolves to itself. No inference starts.

```sh
python scripts/qualify_claude.py \
  --output .local/claude-boundary \
  --model claude-sonnet-5-5 --effort medium \
  --platforms web mobile \
  --install-boundary-certificate
```

```sh
python scripts/bench.py run \
  --task web/webarena-399-profile-bio --arm test_ui \
  --model claude/claude-sonnet-5-5 --claude-effort medium \
  --timeout 600
unset ANTHROPIC_API_KEY
```

How the boundary is enforced:

- **Credential.** The agent container holds only a placeholder. A separate relay on the trial's internal network replaces it with the real credential, which never appears in configuration, evidence or container inspect records.
- **Tools.** Built-in tools are disabled (`--tools ""`), settings and project files are ignored, permission mode is `dontAsk` with an allowlist of `mcp__bench__*` tools, and a `PreToolUse` hook denies anything else. The relay independently rejects any request that offers the model a tool outside the trial's bench catalog, a server tool, another model or effort, or a context edit other than keeping thinking.
- **No retries or replay.** `CLAUDE_CODE_MAX_RETRIES=0`, no fallback model, and the relay refuses every request after any rejection or upstream failure. Compaction is disabled; a compaction event is a `context_overflow`.
- **Budgets.** Model requests are capped at the arm's step budget plus a small allowance. Subscription overage (`isUsingOverage`) is not admitted and ends the trial as `budget_exhausted`.
- **Evidence.** `logs/agent/claude.ndjson` holds the full stream-json trajectory, `logs/agent/mcp.ndjson` every MCP frame, and `logs/claude-provider.ndjson` one content-free record per model request with token usage and the effort the client attached (`effort`, or `null` when the client sent none for that model). The audit replays all three against the bridge ledger.

Claude Code's own default system prompt is kept. The client's `total_cost_usd` estimate is recorded as `client_estimated_cost_usd`; `provider_cost_usd` stays unknown.

Account inventory and synthetic boundary checks remain separate from model evaluations. Preserve the exact runner's credential, model, transport and budget contracts when comparing runs. A reconnecting-client event is a transport interruption, not successful completion or permission to replay a request.
