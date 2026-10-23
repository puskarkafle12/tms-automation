#!/usr/bin/env sh
set -eu

# Cron commonly starts with a reduced PATH. Include standard Linux paths plus
# the common macOS Docker/Homebrew paths without discarding caller additions.
PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin${PATH:+:$PATH}"
export PATH

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
cd "$SCRIPT_DIR/.."

PRIMARY_BRANCH=${TMS_PRIMARY_BRANCH:-codex/backtesting}
CURRENT_BRANCH=$(git symbolic-ref --quiet --short HEAD 2>/dev/null || printf 'HEAD')

# Bootstrap branch selection here, before the Python runner is loaded. A
# server on main otherwise keeps executing main's old runner and can never
# download the newer runner from the configured primary branch.
if [ "$CURRENT_BRANCH" = "HEAD" ]; then
    echo "Cannot switch a detached HEAD to primary branch '$PRIMARY_BRANCH'." >&2
    exit 1
fi
if [ "$CURRENT_BRANCH" != "$PRIMARY_BRANCH" ]; then
    if [ -n "$(git status --porcelain)" ]; then
        echo "Cannot switch from '$CURRENT_BRANCH' to '$PRIMARY_BRANCH': the server working tree has local changes." >&2
        echo "Commit, stash, or move those server changes, then run this script again." >&2
        exit 1
    fi
    echo "Switching server branch: $CURRENT_BRANCH -> $PRIMARY_BRANCH"
    git fetch --prune origin
    if git show-ref --verify --quiet "refs/heads/$PRIMARY_BRANCH"; then
        git switch "$PRIMARY_BRANCH"
    elif git show-ref --verify --quiet "refs/remotes/origin/$PRIMARY_BRANCH"; then
        git switch --track -c "$PRIMARY_BRANCH" "origin/$PRIMARY_BRANCH"
    else
        echo "Primary branch '$PRIMARY_BRANCH' was not found on origin." >&2
        exit 1
    fi
else
    git switch "$PRIMARY_BRANCH" >/dev/null
    echo "Server already on primary branch: $PRIMARY_BRANCH"
fi

PYTHON_BIN=${PYTHON_BIN:-python3}
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python executable not found: $PYTHON_BIN" >&2
    exit 127
fi

exec "$PYTHON_BIN" scripts/run_latest_commit_docker.py --pull-git "$@"
