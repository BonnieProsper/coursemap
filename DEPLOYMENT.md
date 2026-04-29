# Deploying coursemap

coursemap is a self-contained FastAPI app + static UI bundled into a single Docker
image. Pick the deployment path that suits you.

---

## Option A - Fly.io (recommended, free tier)

Fly.io's free tier gives you 3 VMs and enough RAM to run coursemap permanently.
Cold-start time is ~3s; with `min_machines_running = 1` it's instant.

```bash
# 1. Install the Fly CLI
curl -L https://fly.io/install.sh | sh

# 2. Sign up / log in
fly auth signup   # or: fly auth login

# 3. Launch (one-time setup - reads fly.toml)
fly launch --no-deploy

# 4. Set your domain in ALLOWED_ORIGINS (optional but recommended)
fly secrets set ALLOWED_ORIGINS="https://your-app-name.fly.dev"

# 5. Deploy
fly deploy

# Your app is now live at https://your-app-name.fly.dev
```

To update after code or dataset changes:
```bash
fly deploy
```

To view logs:
```bash
fly logs
```

---

## Option B - Docker Compose (self-hosted VPS)

Requires a VPS with Docker installed (DigitalOcean, Hetzner, etc.).

```bash
# 1. Clone the repo on your server
git clone https://github.com/yourname/coursemap.git
cd coursemap

# 2. (Optional) create a .env file to override defaults
echo "ALLOWED_ORIGINS=https://coursemap.yourdomain.com" > .env
echo "WORKERS=4" >> .env

# 3. Build and start
docker compose up --build -d

# App runs on port 8080. Put Nginx/Caddy in front for HTTPS.
```

### Nginx reverse proxy (minimal config)
```nginx
server {
    server_name coursemap.yourdomain.com;
    location / {
        proxy_pass         http://127.0.0.1:8080;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
    }
}
```
Then run `certbot --nginx -d coursemap.yourdomain.com` for free HTTPS.

---

## Option C - Local (development / personal use)

```bash
pip install -e ".[api]"
coursemap serve
# Open http://localhost:8000
```

---

## Keeping datasets fresh

The bundled `datasets/` are scraped from Massey's website. They go stale as
Massey updates courses, prerequisites, and offerings (typically at the start of
each academic year).

**Automated refresh (GitHub Actions):**
The workflow at `.github/workflows/refresh-datasets.yml` runs on the 1st of each
month, re-scrapes all data, and opens a pull request with the diff.
Enable it by pushing to a GitHub repo - no extra setup needed.

**Manual refresh:**
```bash
# Re-scrape all 2766 course prerequisites (~1 min at 20 workers)
python -m coursemap.ingestion.refresh_prerequisites --concurrency 20

# Check data quality after
coursemap data-quality

# Run tests to confirm nothing broke
pytest tests/ -q
```

**After updating datasets on a live deployment:**
```bash
# Fly.io - redeploy with new datasets baked into image
fly deploy

# Docker Compose - datasets are bind-mounted, so just restart:
docker compose restart coursemap
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins. Set to your domain in production. |
| `WORKERS` | `2` | Number of uvicorn workers. Increase for higher traffic. |
| `PORT` | `8080` | Port to listen on (Docker Compose only). |

---

## Resource requirements

| | Minimum | Recommended |
|---|---|---|
| RAM | 256 MB | 512 MB |
| CPU | 0.5 vCPU | 1 vCPU |
| Disk | 50 MB | 100 MB |
| Network | any | any |

The app is stateless - no database, no file writes at runtime. All state is in
`datasets/` (read-only) and in client-side `localStorage`.

---

## Security checklist for production

- [ ] Set `ALLOWED_ORIGINS` to your domain (not `*`)
- [ ] Run behind HTTPS (Fly.io does this automatically; use Caddy/Nginx + certbot for VPS)
- [ ] The app runs as a non-root user (`uid 1000`) inside Docker
- [ ] Rate limiting is enabled by default (30 req/min for `/api/plan`, 200/min for `/api/majors`)
- [ ] No user data is stored server-side - plans live in client `localStorage`
