# Project Context

Read this file first before opening other files. Keep future work targeted.

## Shape
- Backend: FastAPI app in `main.py`.
- Frontend: React/TypeScript app in `frontend/src`.
- Database: PostgreSQL via SQLAlchemy models in `models/`, session/config in `database.py` and `config/db_config.py`.
- Schemas: request/response Pydantic models in `schemas/schemas.py`.
- TMS logic: broker login/session/order helpers in `utils/tms.py`, `utils/base_functions.py`, `utils/monitor_order.py`, and `utils/tms_user_loader.py`.

## Important Backend Areas
- API routes: mostly in `main.py`.
- Models:
  - `models/user.py`: saved TMS accounts.
  - `models/frontend_user.py`: frontend login users.
  - `models/logged_in_user.py`: cached TMS login/session state.
  - `models/scheduled_order.py`: scheduled orders.
  - `models/order_log.py`, `models/order_status_log.py`: monitoring/order logs.
  - `models/tms_password_backup.py`: rotated password backups.
- Database startup/indexes: `database.py`.

## Important Frontend Areas
- App entry/routes: `frontend/src/index.tsx`, `frontend/src/App.tsx`, `frontend/src/routes/`.
- TMS account UI: `frontend/src/pages/control_pannel/Login.tsx`, `Login.css`.
- DP holdings UI: `frontend/src/pages/control_pannel/DpHolding.tsx`, `DpHolding.css`.
- Scheduled orders/order logs: `ScheduleOrder.tsx`, `OrderLogs.tsx`.
- API helpers: `frontend/src/api/`, shared helpers in `frontend/src/utils/`.
- Shared components: `frontend/src/components/`.

## Docker And Scripts
- Main Docker setup: `Dockerfile`, `docker-compose.yml`, `docker-entrypoint-all-in-one.sh`.
- Run/rebuild scripts: `scripts/run_latest_commit_docker.py`, `.sh`, `.cmd`.
- Local DB init: `scripts/init_local_db.py`.
- Persistent DB volume: `tms-automation_tms_postgres_data` mounted at `/var/lib/postgresql/data`.
- Do not remove Docker volumes or reset database data.

## Tests
- Python unit tests: `unit_tests/`.
- Frontend build/test scripts: `frontend/package.json`.
- Target tests to changed area only.

## Common Commands
- Frontend build: `cd frontend && npm run build`.
- Backend syntax check: `python3 -m py_compile main.py`.
- Docker run/rebuild: `scripts/run_latest_commit_docker.sh` or `scripts\run_latest_commit_docker.cmd` on Windows.
