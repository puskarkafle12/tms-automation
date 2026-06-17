#!/usr/bin/env bash
set -eu

# Blocked window: Mon-Fri (1-5) 10:00-15:29 Nepal Time (Asia/Kathmandu)
readonly DAY=$(TZ='Asia/Kathmandu' date '+%u')          # 1=Mon .. 7=Sun
readonly TIME=$(TZ='Asia/Kathmandu' date '+%H%M')       # 24-hour

if [ "$DAY" -ge 1 ] && [ "$DAY" -le 5 ] && [ "$TIME" -ge 1000 ] && [ "$TIME" -lt 1530 ]; then
    echo "$(date): Skipped — Mon-Fri 10:00-15:29 NPT block window"
    exit 0
fi

exec "$(dirname "$0")/run_latest_commit_docker.sh" --pull-git
