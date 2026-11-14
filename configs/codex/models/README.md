# Codex model catalogs (supplied locally)

The Codex runner can pin a model's metadata with a Codex model-catalog file
named `<model>.json` in this folder, for example `gpt-6.1-sol.json`. When the
file exists, the runner mounts it as `model_catalog_json` for that model.

Catalog files are provider metadata, including the provider's own prompts, so
they are not distributed with this repository and are ignored by git. Supply
your own copy. The runner accepts a catalog only if it contains exactly one
model whose `slug` matches the file name and that model keeps the benchmark's
tool restriction:

| Field | Required value |
| --- | --- |
| `tool_mode` | `"direct"` |
| `multi_agent_version` | `null` |
| `apply_patch_tool_type` | `null` |
| `supports_search_tool` | `false` |
| `use_responses_lite` | `false` |
| `experimental_supported_tools` | `[]` |

The SHA-256 of each catalog used is recorded in the run's resolved plan
(`model_catalogs`). `scripts/qualify_codex.py --install-boundary-certificate`
requires a catalog for the qualified model. Without a catalog, Codex uses its
own model metadata.

OpenCode, the harness used for the paper's results, does not use these files.
