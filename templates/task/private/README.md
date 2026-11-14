# Private evaluator material

Never mount or copy this directory into an agent environment or generated-code
sandbox. A trusted controller stages it exclusively for grading.

- `labels.json`: `{"correct": "PASS", "faulty": "FAIL"}` once the reference
  journey has been validated on both variants.
- `test_source.py`: the reference journey with `checkpoint(...)` calls and the
  behavioral assertions; `judge_test` receives a copy of this file.
- `gold_test.py`: runs `test_source.py` through `gui_agent_bench.capture`
  (copy it from an example package).
- `reference.json`: journey, regions and reference programs for the
  generation arms.

The placeholders fail explicitly until they are implemented.
