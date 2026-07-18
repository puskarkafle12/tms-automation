#!/usr/bin/env sh
set -eu

# Cron commonly starts with a reduced PATH. Include standard Linux paths plus
# the common macOS Docker/Homebrew paths without discarding caller additions.
PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"
export PATH

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR/.."

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 127
fi

exec "$PYTHON_BIN" scripts/run_latest_commit_docker.py --pull-git "$@"
