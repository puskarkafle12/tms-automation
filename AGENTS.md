# Agent Instructions

- First read `PROJECT_CONTEXT.md`.
- Only open files directly related to the task.
- Do not scan the entire repo unless absolutely required.
- Do not rewrite unrelated files.
- Make small targeted changes.
- Summarize the plan before editing.
- Run only necessary tests.
- For large logs/files/tool outputs, prefer Headroom compression before reading full output when practical (`/Users/puskarkafle/.cache/codex-headroom-venv/bin/headroom`).
- Do not delete Docker volumes, reset the database, drop tables, or remove user data.
- Keep responses concise.
- After finishing backend/frontend changes that should be verified in the running app, run `./scripts/run_latest_commit_docker.sh` to rebuild and start Docker (do not skip unless the user says not to).
