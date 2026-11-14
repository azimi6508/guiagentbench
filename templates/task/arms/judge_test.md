# judge_test

Policy: `configs/arms/judge_test.toml` (controller reference only).

Predict whether the provided test source would pass on the available application state. You may inspect the source and interact with the application through the available tools. Do not execute the provided test, a copied or reconstructed version, or any grading routine. Return a JSON object with `verdict` equal to `PASS` or `FAIL` and an optional short `reason` string.

Discover the permitted task material under `/workspace`. Write your submission
to `/workspace/output/judgment.json`. The materializer supplies the task intent
and the platform API description when this template becomes a runnable task.

Template: implement the task behavior and select the platform API before execution.
