# TMS Automation — Setup Guide (From Scratch)

This guide walks you through running the full project locally. The recommended path is Docker, which packages Nginx, PostgreSQL, FastAPI, the React build, and database initialization into one container.

---

## What This Project Does

- **App** (`http://localhost:3000`) — React dashboard served through Nginx
- **Backend API** (`http://localhost:3000/docs`) — FastAPI API that talks to NEPSE TMS and the database
- **Bundled PostgreSQL** — stores app users, TMS sessions/tokens, orders, and logs inside the Docker container volume

You need **two separate logins**:

| Login | Where | Purpose |
|-------|-------|---------|
| App login | `http://localhost:3000` | Opens the dashboard |
| TMS login | Dashboard → **Login** tab | Connects your broker TMS account |

---

## Recommended: Run Everything in One Docker Container

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

The container:

- builds the React frontend
- starts Nginx on port `80` inside the container
- starts PostgreSQL inside the same container
- creates the database/user if missing
- runs `scripts/init_local_db.py`
- starts FastAPI privately on port `8000` inside the container
- starts Cloudflare Tunnel inside the same container

Docker maps host port `3000` to Nginx inside the container, so other machines on the same LAN can open `http://YOUR_COMPUTER_LAN_IP:3000`.

By default, Docker starts a temporary Cloudflare Quick Tunnel. Get the public URL with:

```bash
docker logs tms-automation | grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' | tail -1
```

For the same public URL every time, create a Cloudflare named tunnel in Cloudflare Zero Trust, set `CLOUDFLARED_TOKEN`, and run Docker again:

```bash
CLOUDFLARED_TOKEN="your-token" docker compose up -d --build
```

Default app login:

```text
username: admin
password: admin
```

To change the seeded login, edit `FRONTEND_SEED_USER` and `FRONTEND_SEED_PASSWORD` in `docker-compose.yml` before the first run. PostgreSQL data is stored in the `tms_postgres_data` Docker volume.

---

## Manual Local Development

## Prerequisites

Install these before you start:

| Tool | Version | Check |
|------|---------|-------|
| **Git** | any recent | `git --version` |
| **Python** | 3.11+ recommended | `python3 --version` |
| **Node.js** | 18+ recommended | `node --version` |
| **npm** | comes with Node | `npm --version` |
| **Docker Desktop** | latest | `docker --version` |

> **macOS tip:** If you use Homebrew: `brew install python node docker`

---

## 1. Clone the Repository

```bash
git clone https://github.com/puskarkafle12/tms-automation.git
cd tms-automation
```

---

## 2. Start PostgreSQL (Docker)

The project uses PostgreSQL for all data storage.

```bash
docker run --name tms-postgres \
  -e POSTGRES_USER=pk \
  -e POSTGRES_PASSWORD=pk \
  -e POSTGRES_DB=stock \
  -p 5432:5432 \
  -d postgres:16-alpine
```

This starts a container named `tms-postgres` with:

| Setting | Value |
|---------|-------|
| Host | `localhost` |
| Port | `5432` |
| User | `pk` |
| Password | `pk` |
| Database | `stock` |

Verify it is running:

```bash
docker ps
```

You should see `tms-postgres` in the list. If you use the recommended all-in-one Docker setup above, skip the rest of the manual setup.

---

## 3. Create Environment File

Create a `.env` file in the project root:

```bash
cat > .env <<'EOF'
DB_USER=pk
DB_PASSWORD=pk
DB_HOST=localhost
DB_NAME=stock
FRONTEND_SEED_USER=admin
FRONTEND_SEED_PASSWORD=admin
EOF
```

Change `FRONTEND_SEED_USER` and `FRONTEND_SEED_PASSWORD` to your own local app login values.

> The backend loads this file automatically via `config/db_config.py`.

---

## 4. Backend Setup (Python)

### 4.1 Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### 4.2 Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **First-time note:** `easyocr` downloads ML models on first use (captcha solving). This can take a few minutes and needs internet access.

### 4.3 Initialize the database

Creates all tables and seeds the default **app login** user:

```bash
python scripts/init_local_db.py
```

Expected output:

```
Seeded frontend user: <username>
Database tables are ready.
```

The script prints the default app username and password it created. Use those for the first dashboard login. To use custom credentials, set `FRONTEND_SEED_USER` and `FRONTEND_SEED_PASSWORD` in `.env` before running the script.

### 4.4 Start the backend server

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Or:

```bash
python main.py
```

Verify the API is up:

```bash
curl http://localhost:8000/
```

Expected: `{"message":"Hello, FastAPI"}`

API docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## 5. Frontend Setup (React)

Open a **new terminal** (keep the backend running).

```bash
cd frontend
npm install
npm start
```

The app opens at [http://localhost:3000](http://localhost:3000).

The frontend defaults the API URL to the same origin it was opened from. In manual development from `http://localhost:3000`, set **Settings → Backend API URL** to `http://localhost:8000` if needed.

---

## 6. Log In and Use the App

### Step A — App login (dashboard access)

1. Open [http://localhost:3000](http://localhost:3000)
2. Log in with the app username and password from `init_local_db.py` output
3. You are redirected to the dashboard

### Step B — TMS login (broker account)

1. In the dashboard, open the **Login** tab
2. Enter your TMS credentials:
   - **Broker Number** — your broker code (e.g. `35`)
   - **Client ID** — your TMS client ID
   - **Password** — your **plain TMS password** (not base64)

The backend encodes the password to the TMS format automatically.

#### Expired TMS password

If your TMS password is expired, the backend will:

1. Log in (TMS may return status `210` for expired passwords)
2. Change to a new valid password variant (7–14 chars, caps + digit + special)
3. Show the new password in the success message and auto-fill the field

> Save the new password shown after login — TMS will not email it to you in plain text.

---

## 7. Running Everything (Quick Reference)

Use **3 terminals**:

**Terminal 1 — Database**

```bash
docker compose up -d
```

**Terminal 2 — Backend**

```bash
cd tms-automation
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 3 — Frontend**

```bash
cd tms-automation/frontend
npm start
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| PostgreSQL | localhost:5432 |

---

## 8. Useful Scripts

| Script | Purpose |
|--------|---------|
| `scripts/init_local_db.py` | Create tables + seed app user |
| `scripts/find_tms_password.py` | Test password candidates against TMS (recovery) |
| `scripts/test_captcha_login_response.py` | Debug captcha OCR vs TMS |

Example — find working TMS password after rotation:

```bash
source .venv/bin/activate
python scripts/find_tms_password.py --username YOUR_CLIENT_ID --password 'your-previous-password'
```

Or set `TMS_USERNAME` and `TMS_PASSWORD` in `.env` (do not commit `.env`).

---

## 9. Troubleshooting

### Database connection failed

- Check Docker: `docker ps` — is `tms-postgres` running?
- Check `.env` values match `docker-compose.yml` (`pk` / `pk` / `stock`)
- Restart DB: `docker compose down && docker compose up -d`

### Frontend login returns 404

- Backend must be running on port `8000`
- Hard refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`)
- Confirm API URL in browser console / Settings is `http://localhost:8000`

### TMS login fails with captcha error

- Captcha OCR is ~50% accurate per attempt; the backend retries up to 5 times
- Try logging in again
- Run `python scripts/test_captcha_login_response.py` to test OCR

### `'generator' object has no attribute 'rollback'`

- Fixed in current code — use `get_db_session()` for direct DB access
- Pull latest: `git pull origin main`

### Password rotation / "already been used"

- TMS blocks reusing old passwords
- The app picks a new unused variant and shows it in the login success message
- Use `scripts/find_tms_password.py` if you lost the new password

### Port already in use

```bash
# Find what is using port 8000 or 3000
lsof -i :8000
lsof -i :3000
```

Stop the other process or use a different port.

---

## 10. Project Structure

```
tms-automation/
├── main.py                 # FastAPI entry point
├── database.py             # SQLAlchemy engine + sessions
├── config/db_config.py     # DB URL from .env
├── models/                 # Database models
├── utils/tms.py            # TMS login, orders, password rotation
├── utils/tms_captcha_solver/  # Captcha OCR (EasyOCR)
├── frontend/               # React dashboard
├── scripts/                # DB init + helper scripts
├── docker-compose.yml      # Local PostgreSQL
├── requirements.txt        # Python dependencies
└── .env                    # Local config (create this yourself)
```

---

## 11. Stopping the Project

```bash
# Stop frontend: Ctrl+C in frontend terminal
# Stop backend:  Ctrl+C in backend terminal

# Stop database
docker compose down

# Deactivate Python venv
deactivate
```

To wipe the database completely (destructive):

```bash
docker compose down -v
docker compose up -d
python scripts/init_local_db.py
```

---

## 12. Production Notes

This guide is for **local development only**. For production:

- Change `SECRET_KEY` in `main.py`
- Use strong database credentials
- Do not commit `.env` to git
- Put the frontend behind HTTPS and point it to your production API URL
- Review Dependabot security alerts on GitHub

---

## Need Help?

1. Check backend terminal logs for TMS error details
2. Check browser dev tools → Network tab for API `detail` messages
3. Open an issue: https://github.com/puskarkafle12/tms-automation/issues
