# Setup and operations

## Requirements

- Docker Engine 24+ and Docker Compose v2 (`docker compose version`).
- 4 GB RAM minimum. 8 GB+ is recommended for local tile generation or Tessera.
- Disk: 5 GB for the base stack, plus OSM extract/tile size, plus Tessera cache.
- Open ports 80/443 on the host if you want LAN or public access. No database
  port is published.

## Fresh install

```bash
git clone https://github.com/ja927cam/strata strata
cd strata
cp .env.example .env
```

Edit `.env`:

```dotenv
SECRET_KEY=<openssl rand -hex 32>
POSTGRES_PASSWORD=<a URL-safe random password>
DATABASE_URL=postgresql+asyncpg://nasmap:<the same password>@db:5432/nasmap
SITE_ADDRESS=http://localhost
SITE_URL=http://localhost
FRONTEND_URL=http://localhost
```

Start:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f api worker
```

Wait for all healthchecks to become healthy. Open the site, register the first
account (it becomes admin), and import a sample file.

## Environment reference

| Variable | Default | Notes |
| --- | --- | --- |
| `SITE_ADDRESS` | `http://localhost` | Caddy listen address. A hostname enables ACME HTTPS. |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Host ports. |
| `SECRET_KEY` | dev value | JWT signing + fallback token encryption. Rotate before exposure. |
| `OSM_TOKEN_ENCRYPTION_KEY` | empty | Optional Fernet key for OSM tokens. |
| `POSTGRES_DB/USER/PASSWORD` | `nasmap` | Database bootstrap. |
| `DATABASE_URL` | derived | Must match the Postgres values. |
| `REDIS_URL` | `redis://redis:6379/0` | Queue and rate limiting. |
| `SITE_URL` / `FRONTEND_URL` | `http://localhost` | Used for OAuth redirects and CORS. |
| `CORS_ORIGINS` | empty | Comma-separated extra origins. |
| `UPLOAD_DIR` | `/data/uploads` | Docker volume in the default stack. |
| `TESSERA_CACHE_DIR` | `/data/tessera` | Tessera tile cache volume. |
| `TILES_DIR` | `/data/tiles` | Local tile volume. |
| `MAX_UPLOAD_MB` | 512 | Per-file upload cap. |
| `MAX_PHOTO_MB` | 100 | Per-photo cap for EXIF imports. |
| `MAX_ATTACHMENT_MB` | 250 | Per-file cap for non-image media. |
| `MAX_URL_IMPORT_MB` | 1024 | Remote download cap. |
| `URL_FETCH_TIMEOUT_SECONDS` | 90 | Per-request timeout. |
| `ALLOW_PRIVATE_URL_IMPORTS` | false | Opt-in SSRF exception for LAN services. |
| `PUID` / `PGID` | 1000 | Container user; match NAS share ownership. |
| `INGEST_PATH` | `./data/ingest` | Host/NAS folder mounted read-only at `/ingest`. |
| `INGEST_ROOTS` | `/ingest` | Comma-separated container paths available to the ingest UI. |
| `INGEST_ENABLED` | true | Enables/disables server-side folder imports. |
| `INGEST_MAX_SCAN_FILES` | 1000 | Preview scan cap. |
| `INGEST_MAX_FILES_PER_JOB` | 5000 | Files accepted in one ingest job. |
| `ACCESS_TOKEN_TTL_MINUTES` | 30 | JWT lifetime. |
| `REFRESH_TOKEN_TTL_DAYS` | 30 | Refresh-cookie lifetime. |
| `COOKIE_SECURE` | false | Set true for HTTPS. |
| `FIRST_USER_IS_ADMIN` | true | Bootstrap behaviour. |
| `REGISTRATION_ENABLED` | true | First account can always be created. |
| `AUTH_RATE_LIMIT` | 10 / 60s | Login/register per IP. |
| `UPLOAD_RATE_LIMIT` | 30 / hour | Upload + URL import per IP. |
| `BASEMAP_MODE` | `remote_osm` | `local` after generating tiles. |
| `OSM_TILE_URL` | tile.openstreetmap.org | Remote raster template. |
| `OSM_TILE_ATTRIBUTION` | © OSM contributors | Displayed by MapLibre. |
| `OSM_TILE_PROXY` | true | On-demand cached tile proxy. |
| `OSM_TILE_CACHE_TTL_DAYS` | 7 | Remote tile cache lifetime. |
| `OSM_OAUTH_ENABLED` | false | Requires client id/secret. |
| `OSM_API_BASE_URL` | api.openstreetmap.org | Use dev server for testing. |
| `OSM_SIGNIN_AUTO_CREATE` | false | Create viewer accounts on first OSM sign-in. |
| `TESSERA_ENABLED` | true | Disable to hide the UI. |
| `TESSERA_VERSION` | v1.1 | GeoTessera dataset version. |
| `TESSERA_MAX_TILES` | 64 | Per-job tile cap. |
| `JSON_LOGS` | true | Structured logs to stdout. |

## Importing files already on the NAS

The stack mounts one host folder read-only into the API and worker at `/ingest`.
Set `INGEST_PATH` to the NAS share and recreate the services:

```dotenv
INGEST_PATH=/volume1/photo
INGEST_ENABLED=true
INGEST_ROOTS=/ingest
```

```bash
docker compose up -d
```

On Synology use `/volume1/...`, QNAP `/share/...`, Unraid `/mnt/user/...`, and
TrueNAS `/mnt/<pool>/...`. The Docker container user defaults to uid/gid
`1000`. If your share is owned by a different NAS user, set `PUID` and `PGID`
to match that owner:

```dotenv
PUID=1026
PGID=100
```

The share must be readable by that user (or by “everyone”). The mount is
read-only: Strata never writes to the NAS folder.

Multiple roots are possible with a Compose override that mounts each folder and
lists them comma-separated, for example `INGEST_ROOTS=/ingest,/archive`, as long
as both paths exist inside the API and worker containers.

Then use **Map → Add layer → Server / NAS**, scan a subfolder, and start a
background job. Photos are referenced in place; geodata files are read and
imported into PostGIS/uploads. Keep the NAS folder mounted for photo originals
to remain available.

## Production with HTTPS

1. Point DNS at the host.
2. Set:
   ```dotenv
   SITE_ADDRESS=maps.example.com
   SITE_URL=https://maps.example.com
   FRONTEND_URL=https://maps.example.com
   COOKIE_SECURE=true
   OSM_REDIRECT_URI=https://maps.example.com/api/v1/osm/callback
   ```
3. `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
4. Open `https://maps.example.com`. Caddy stores certificates in
   `caddy_data`.

Caddy forwards `/api/*`, `/docs`, `/openapi.json` to the API, `/tiles/*` to
TileServer GL (prefix stripped), and everything else to the static web build.

## Tests

```bash
make test     # starts an isolated PostGIS container (profile "test")
make lint
```

`make test` never points at the production database. It uses the `db-test`
service with database/user/password `nasmap_test`/`nasmap`/`nasmap`. The API
image includes pytest and Ruff for this purpose. Stop the test database with
`docker compose --profile test stop db-test`.

## Local development

Backend:

```bash
docker compose up -d db redis
python3 -m venv .venv && . .venv/bin/activate
pip install -e "./api[dev]"
export DATABASE_URL=postgresql+asyncpg://nasmap:<password>@localhost:5432/nasmap
python -m app.migrate          # from api/ or set PYTHONPATH=api
cd api && uvicorn app.main:app --reload --port 8000
```

Worker:

```bash
cd api && python -m app.workers.runner
```

Frontend:

```bash
cd web
npm install
npm run dev   # http://localhost:5173, proxies /api and /tiles
```

To run the database on the host instead of Docker, set `DATABASE_URL`
accordingly and create the PostGIS extensions manually; the SQL files in
`db/init` are the source of truth.

## Migrations

```bash
make migrate                 # docker compose exec api python -m app.migrate
```

SQL files are idempotent and applied in filename order. `app.schema_migrations`
records what has run. To add a migration, drop a new numbered SQL file into
`db/init/` and run `make migrate`. New columns for existing deployments should
use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.

## Health and logs

- `GET /api/v1/health` returns 200 only when Postgres and Redis are reachable,
  otherwise 503 with `{"status":"degraded"}`.
- `docker compose ps` shows health for db, redis, api, worker, web, tileserver.
- Logs are JSON on stdout by default:
  ```bash
  docker compose logs -f api | jq .
  ```
- The worker writes a heartbeat file inside its container every 10 seconds; the
  container healthcheck fails if it is older than two minutes.

## Backups and restore

```bash
make backup                    # ./backups/<UTC timestamp>/
make restore FILE=backups/20260101T000000Z
```

`backup.sh` takes a custom-format `pg_dump` and tars the `nasmap_uploads` and
`nasmap_tessera_cache` volumes. Generated tiles are not backed up. Restore
stops API/worker, runs `pg_restore --clean --if-exists`, restores volumes, and
starts the stack. Test a restore on a non-production instance.

## Upgrades

```bash
git pull
docker compose build --pull
docker compose up -d
```

The API entrypoint applies pending SQL migrations before starting. Review
`docs/architecture.md` and the changelog before major upgrades. Take a backup
before upgrading the database image.

## Troubleshooting

- **API restarts / “database not ready”**: the entrypoint retries for two
  minutes. Check `docker compose logs db`; on slow NAS disks increase the db
  healthcheck `start_period`.
- **Registration fails after setup**: set `REGISTRATION_ENABLED=true`, or create
  users as an admin through the admin page. The first user is always allowed.
- **Login works but requests 401**: the refresh cookie is scoped to
  `/api/v1/auth` and `SameSite=Lax`; make sure the browser is using the same
  hostname and scheme as `SITE_URL`, and set `COOKIE_SECURE=true` only on HTTPS.
- **Remote import rejected**: private/loopback/link-local URLs are blocked by
  default. For an internal WMS, set `ALLOW_PRIVATE_URL_IMPORTS=true` only on a
  trusted network.
- **Tessera unavailable**: check `TESSERA_ENABLED`, outbound network access to the
  registry, and `docker compose logs worker`. The API image must include the
  `tessera` extra (the provided Dockerfile does).
- **Local basemap blank**: run `make generate-tiles`, confirm
  `tiles/config.json` contains a `nasmap` data entry, restart `tileserver`, and
  set `BASEMAP_MODE=local`.
