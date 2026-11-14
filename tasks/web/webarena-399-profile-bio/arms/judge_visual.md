Inspect the ordered screenshots and steps supplied under `/workspace`. The
evidence index is `/workspace/evidence/manifest.json`; its image paths are
relative to `/workspace/evidence`. There is no live app in this arm.

Write `/workspace/output/judgment.json` as a JSON object with `verdict` equal to
`PASS` or `FAIL` and an optional short `reason` string.
