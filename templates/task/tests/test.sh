#!/bin/sh
# This placeholder must never award credit or masquerade as a real verifier.
set -eu
mkdir -p /logs/verifier
printf '0\n' > /logs/verifier/reward.txt
printf '{"reward":0}\n' > /logs/verifier/reward.json
printf '{"status":"not_implemented","reason":"Task template has no verifier"}\n' > /logs/verifier/metrics.json
printf '%s\n' 'Task template: verifier is not implemented' >&2
exit 2
