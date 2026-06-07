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

The Docker image builds the React frontend, starts Nginx, runs FastAPI, starts bundled PostgreSQL, creates tables, seeds the app login, and starts Cloudflare Tunnel inside one container. Docker publishes Nginx on host port `3000`.

By default Docker starts a temporary Cloudflare Quick Tunnel. Get the public URL with:

```bash
docker logs tms-automation | grep -Eo 'https://[-a-z0-9]+\.trycloudflare\.com' | tail -1
```

For the same public URL every time, create a Cloudflare named tunnel and set `CLOUDFLARED_TOKEN` before starting Docker.

**Default app login:** `admin` / `admin`  
Change `FRONTEND_SEED_USER` and `FRONTEND_SEED_PASSWORD` in `docker-compose.yml` before first run if you want different credentials.
**TMS login:** Dashboard → Login tab (use your own broker credentials)
