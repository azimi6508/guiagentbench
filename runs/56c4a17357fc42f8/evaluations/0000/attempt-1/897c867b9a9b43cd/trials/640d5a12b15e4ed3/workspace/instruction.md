Evaluation arm: judge_visual. Produce a PASS/FAIL judgment JSON file.
Required artifact: /workspace/output/judgment.json. Save it before finishing.
Read the complete contract below. A final chat message does not submit an artifact.

The native Markor editor has an empty note named `atlas.txt` open. Put exactly
`Bring the blue notebook.` in the note. Its text must still be visible and saved
after closing and reopening the application.


Inspect any of the three ordered screenshots and steps supplied in /workspace.
Predict whether the requested note persistence behavior passes. Save
/workspace/output/judgment.json with {"verdict":"PASS"} or {"verdict":"FAIL"}
and an optional reason. There is no live application in this arm.


Judgment output contract: write a JSON object to /workspace/output/judgment.json.
Use exactly {"verdict":"PASS"} or {"verdict":"FAIL"}, with uppercase verdict values.
An optional "reason" string may contain at most 2000 characters. No other keys,
Markdown fences or surrounding text are permitted; the file must not exceed 16384 bytes.
