# Contributing with coding agents

Read README.md and docs/architecture.md before making changes. Keep all six arm IDs and their enforced evidence and tool boundaries. Materialize workspaces from positive allowlists. Never expose private labels, variants, solutions, verifiers or results to evaluated agents. Execute generated programs only in the separate verifier sandbox. Preserve complete evidence, fixed planned denominators and explicit error causes. Do not add automatic action, request or trial retries.

Run `python scripts/check_structure.py`, `python -m unittest discover -s tests -v`, and `node tests/viewer_frontend.cjs`. For runtime changes, rebuild the relevant isolated images, run the scripted controls and forbidden-access probes, then audit their output with `python scripts/check_leakage.py --run <directory>`.
