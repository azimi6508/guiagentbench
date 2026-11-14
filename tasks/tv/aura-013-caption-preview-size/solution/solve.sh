#!/bin/sh
set -eu
# Run the trusted reference for this package, including after cloning it.
TASK_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ROOT=$(CDPATH= cd -- "$TASK_DIR/../../.." && pwd)
DOMAIN=$(basename -- "$(dirname -- "$TASK_DIR")")
TASK=$(basename -- "$TASK_DIR")
ARM=${1:-test_ui}
if [ "$#" -gt 0 ]; then shift; fi
exec python3 "$ROOT/scripts/bench.py" run --task "$DOMAIN/$TASK" --model reference/solution --arm "$ARM" "$@"
