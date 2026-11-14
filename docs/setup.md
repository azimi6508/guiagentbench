# Installation

Run these commands from the repository root. Use a dedicated workspace for evaluation so generated runs and application data remain local.

## Host environment

Browser execution uses Docker with Linux containers. Install Python 3.11 or newer and a Docker Engine that your user can access. Java 17 or newer (with `java` on `PATH`) and KVM are also required for the Android setup below. Node.js 22 runs the JavaScript regression checks.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[visual,codex]'
docker info
python scripts/check_structure.py
```

`visual` installs the pinned image comparison dependencies. `codex` installs the MCP dependency for the optional restricted runner. Browser automation lives in the Docker worker image; a host browser installation is not needed for ordinary evaluations.

Build an application and the shared runtimes:

```sh
python scripts/bench.py build --task web/webarena-399-profile-bio
python scripts/bench.py build --task tv/aura-013-caption-preview-size
```

The shared images contain the browser broker, generated-code executor and OpenCode client. The application image is separate. `--runner codex`, `--runner cursor` or `--runner claude` builds that runner's images instead of the OpenCode client; `--runner all` builds every client. Every model evaluation also checks the default images, so run the default build first or use `--runner all`.

Use editable installation when working from a checkout. For a non-editable package installation, pass `--root /absolute/path/to/checkout` before the command so the controller can find policies, tasks and runtime recipes.

## Android

The Android example uses a dedicated `GuiAgentBench` emulator at serial `emulator-5580`, with a 720 × 1280 viewport, density 240 and locale `en-US`. The Linux lock selects the API 36 Google Play x86_64 image, revision 7, emulator 36.2.12, Platform Tools 37.0.1 and Command-line Tools 19.0. Exact file hashes and download URLs are in `runtime/android/lock-linux-x86_64.json`.

Ensure your user can read and write `/dev/kvm`. Keep enough local disk space for Android archives, extracted images, writable emulator storage and Docker images. Start this dedicated emulator before any other emulator; the SDK's initial device configuration can use its own emulator selection.

Install the pinned SDK archives:

```sh
python scripts/mobile_sdk.py
```

The installer uses `.mobile/downloads/` and `.mobile/sdk/`, verifies archive and file hashes, and refuses to overwrite a differing SDK. It does not accept licenses. It always installs into `.mobile/sdk/`; if your shell exports `ANDROID_SDK_ROOT` or `ANDROID_HOME` for another SDK, unset them first, because the later setup commands would use that SDK instead.

Review and accept the applicable SDK terms yourself:

```sh
.mobile/sdk/cmdline-tools/latest/bin/sdkmanager \
  --sdk_root="$PWD/.mobile/sdk" --licenses
```

Provide a Python **3.11.9** interpreter for the native driver. It is independent of the main `.venv`. For example, if you use uv:

```sh
UV_PYTHON_INSTALL_DIR="$PWD/.mobile/python" uv python install 3.11.9
python scripts/mobile_setup.py prepare \
  --python "$PWD/.mobile/python/cpython-3.11.9-linux-x86_64-gnu/bin/python3.11"
```

Alternatively, pass the absolute path to an existing Python 3.11.9 interpreter. Preparation creates `.mobile/venv`, installs the pinned native dependencies and creates the dedicated AVD. Application APKs are declared by task packages and installed explicitly.

```sh
python scripts/mobile_setup.py start
python scripts/mobile_setup.py install-app --task mobile/markor-note-persistence
python scripts/mobile_setup.py check --task mobile/markor-note-persistence
python scripts/bench.py build --task mobile/markor-note-persistence
```

Check the installation with the Android example's known solution:

```sh
python scripts/bench.py run \
  --task mobile/markor-note-persistence --arm test_ui \
  --model reference/solution
```

`ANDROID_SDK_ROOT` or `ANDROID_HOME` may select an existing SDK, provided every lock entry matches. Without an override, Linux uses `.mobile/sdk/`. The native environment has its own Android/home directories and fixed project-local ADB key paths. Personal emulator profiles and provider credentials are not inherited.

Run one native evaluation at a time. A process-owned device lock rejects concurrent drivers or setup operations. The driver checks device identity, application scope and runtime pins before operating the app.

When finished:

```sh
python scripts/mobile_setup.py stop
```

Stop the dedicated emulator through this command, rather than closing unrelated device processes.

## Development checks

```sh
python scripts/check_structure.py
python -m unittest discover -s tests -v
node tests/viewer_frontend.cjs
```

Run AURA's independent application checks as well when changing its code:

```sh
cd runtime/aura/app
node --test tests/*.mjs
python -m unittest discover -s tests -p 'test_server.py'
```

The browser application tests use the dependencies in `runtime/aura/app/requirements-test.txt` and their own Playwright browser installation. Keep their screenshots and generated media outside version control.

## Source changes and qualification

After an intentional framework or policy change, refresh the source locks:

```sh
python scripts/pin_sources.py
```

This records source identities; it grants no runtime qualification. Rebuild the relevant images and run [local framework qualification](runners.md#local-framework-qualification). Image IDs, task inputs, source identities and retained evidence are bound to the resulting local certificate.

## Distribution check

Before distributing a wheel, verify that the built package includes every Python module, viewer asset and required license notice:

```sh
python -m pip wheel --no-deps --wheel-dir dist .
python scripts/check_wheel.py dist/gui_agent_bench-*.whl
```

Continuous integration runs this check as well as the source tests. Generated wheels remain in the ignored `dist/` directory.
