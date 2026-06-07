# TMS Automation

Automated trading tools for NEPSE TMS: stock grabber, order scheduling, order monitoring, and a React dashboard.

## Quick Start

**Full setup from scratch:** see **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**

### Docker quick start

```bash
docker compose up --build
```

| Service | URL |
|---------|-----|
| App + API | http://localhost:3000 |
| API docs | http://localhost:3000/docs |

The Docker image builds the React frontend, starts Nginx, runs FastAPI, starts bundled PostgreSQL, creates tables, seeds the app login, and starts **ngrok** with a permanent public URL. Docker publishes Nginx on host port `3000`.

```bash
docker compose up -d --build
./scripts/show-public-url.sh
```

| URL | Address |
|-----|---------|
| Local | http://localhost:3000 |
| Public (fixed) | `https://untrained-pleading-unmarked.ngrok-free.dev` |

**Default app login:** `admin` / `admin`  
Change `FRONTEND_SEED_USER` and `FRONTEND_SEED_PASSWORD` in `docker-compose.yml` before first run if you want different credentials.
**TMS login:** Dashboard → Login tab (use your own broker credentials)
