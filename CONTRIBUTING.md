# Contributing

Use a new Python environment, install `.[visual,codex]`, and run the checks in the README. Keep changes focused and add regression coverage for behavior changes. Python sources are formatted with Black (`python -m pip install -e '.[dev]'`, then `python -m black src scripts tests runtime`); the configuration is in `pyproject.toml`. The framework records one attempt per planned evaluation; preserve explicit failure causes and complete evidence.

A task package belongs in `tasks/<domain>/<id>/`. Follow [task authoring](docs/task-authoring.md) to define its public goal, separate private verifier, reproducible variants, provenance and arm eligibility. Validate both states with the privileged reference runner and exercise the information barriers before evaluating a model.

Do not commit credentials, downloaded SDKs, personal device data, generated runs, local qualification records or AURA user libraries. Review the actual staged file list before publishing.
