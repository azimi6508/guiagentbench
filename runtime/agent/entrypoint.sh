#!/bin/sh
set -eu
if [ "${1-}" = run ]; then
  set -- node /usr/local/lib/bench-run-ready.cjs "$@"
else
  set -- opencode "$@"
fi
# Never inherit provider secrets, host configuration, or image environment flags.
exec env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp/home LANG=C.UTF-8 \
  TMPDIR=/tmp XDG_CONFIG_HOME=/tmp/home/config XDG_DATA_HOME=/tmp/home/data \
  XDG_CACHE_HOME=/tmp/home/cache OPENCODE_CONFIG=/config/opencode.json \
  OPENCODE_DISABLE_DEFAULT_PLUGINS=true OPENCODE_DISABLE_MODELS_FETCH=true \
  OPENCODE_DISABLE_CLAUDE_CODE=true OPENCODE_DISABLE_AUTOUPDATE=true \
  "$@"
