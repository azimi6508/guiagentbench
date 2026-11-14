Evaluation arm: judge_visual. Produce a PASS/FAIL judgment JSON file.
Required artifact: /workspace/output/judgment.json. Save it before finishing.
Read the complete contract below. A final chat message does not submit an artifact.

# A saved biography appears on the reopened profile

Change the forum biography of the signed-in user to exactly `I am a robot` and
save it. When the profile is opened again after saving, its biography must be
exactly `I am a robot`.

The local Postmill forum opens on the profile of `MarvelsGrantMan136`, who is
already signed in. The profile page and its biography editor are available;
other forum pages are outside this task.


Inspect the ordered screenshots and steps supplied under `/workspace`. The
evidence index is `/workspace/evidence/manifest.json`; its image paths are
relative to `/workspace/evidence`. There is no live app in this arm.

Write `/workspace/output/judgment.json` as a JSON object with `verdict` equal to
`PASS` or `FAIL` and an optional short `reason` string.


Judgment output contract: write a JSON object to /workspace/output/judgment.json.
Use exactly {"verdict":"PASS"} or {"verdict":"FAIL"}, with uppercase verdict values.
An optional "reason" string may contain at most 2000 characters. No other keys,
Markdown fences or surrounding text are permitted; the file must not exceed 16384 bytes.
