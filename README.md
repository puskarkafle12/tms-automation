# TMS Automation

Automated trading tools for NEPSE TMS: stock grabber, order scheduling, order monitoring, and a React dashboard.

## Quick Start

**Full setup from scratch:** see **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**

### Minimum steps

```bash
# 1. Database
docker compose up -d

# 2. Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# create .env — see SETUP_GUIDE.md
python scripts/init_local_db.py
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 3. Frontend (new terminal)
cd frontend && npm install && npm start
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend | http://localhost:8000 |

**App login:** use the credentials printed by `scripts/init_local_db.py`  
**TMS login:** Dashboard → Login tab (use your own broker credentials)
