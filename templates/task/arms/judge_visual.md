# judge_visual

Policy: `configs/arms/judge_visual.toml` (controller reference only).

Assess whether the intended behavior is satisfied in the recorded interaction. You may inspect the ordered screenshots and any available step list. Return a JSON object with `verdict` equal to `PASS` or `FAIL` and an optional short `reason` string.

Discover the permitted task material under `/workspace`. Write your submission
to `/workspace/output/judgment.json`. The materializer supplies the task intent
and the platform API description when this template becomes a runnable task.

Template: implement the task behavior and select the platform API before execution.
