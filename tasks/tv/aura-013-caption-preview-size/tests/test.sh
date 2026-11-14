#!/bin/sh
set -eu
# Standard judgment verifier. Only the isolated verifier receives /private and the variant.
exec python -m gui_agent_bench verify --submission /artifact/judgment.json \
  --labels /private/labels.json --variant "$1" --output /logs/verifier
