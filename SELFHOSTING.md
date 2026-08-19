# Self-Hosting Studiamo

Run your own copy of Studiamo on your own hardware: your data, your Postgres database, and
your own Gemini API key. This mode has no billing, no subscription, and no dependency on
Studiamo Cloud at all.

## Prerequisites

- **Docker & Docker Compose**:
  - **Windows & macOS**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop/). Make sure Docker Desktop is open and running before executing compose commands.
  - **Linux (Ubuntu/Debian)**: Install Docker Engine and the Compose plugin via [Docker's official guide](https://docs.docker.com/engine/install/) or via:
    ```bash
    sudo apt update && sudo apt install docker.io docker-compose-v2
    ```
- **A free Google Gemini API key**: Get one at [Google AI Studio](https://aistudio.google.com/apikey). Optional at the infrastructure level (each user can also bring their own key in Settings), but you will want at least one key configured before importing your first video or PDF.

## Quickstart

```bash
git clone https://github.com/NaEs25/studiamo.git
cd studiamo
cp .env.selfhosted.example .env
```

Open `.env` and set two things before starting:

- `YB_SECRET_KEY`: generate one with `openssl rand -hex 32` and paste it in. This signs
  session cookies. If you leave it blank the app still starts, but it generates a random key
  on every process start, which logs every signed-in user out on every container restart.
- `GEMINI_API_KEY` (optional): a system-wide default key from Google AI Studio. Users can
  also set their own key individually in Settings, this is just the fallback for anyone who
  hasn't.

Then bring the stack up:

```bash
docker compose up -d
```

This starts two containers: `studiamo-postgres` (Postgres 16) and `studiamo-web` (the app).
`studiamo-web` pulls the prebuilt image from `ghcr.io/naes25/studiamo` rather than
compiling anything locally, so this step takes seconds, not minutes. `studiamo-web` waits
for Postgres to report healthy before starting, and applies the database schema itself on
first boot (`app/schema.py`'s `ensure_schema_up_to_date()`, which runs from the app's own
startup lifecycle), there is no separate migration command to run.

If you'd rather build the image from source than run the prebuilt one, use
`docker compose up -d --build` instead, both here and in every command below.

Check that both containers are healthy:

```bash
docker compose ps
```

Once `studiamo-web` shows `healthy`, open `http://localhost:5004` (or your server's address)
and create your first account from the login page. It's a local username and password,
selfhosted mode has no Google SSO.

## Network, port, and firewall

The app listens on port `5004` inside the container, mapped to the same port on the host by
default (`PORT` in `.env` controls the host side of that mapping). By default that's only
reachable on your local network, which is the recommended way to run it.

If you want access away from home, **we recommend a VPN/mesh overlay (Tailscale, WireGuard) or
a tunnel (Cloudflare Tunnel) over port-forwarding.** Those get you remote access without putting
the app's login page on the public internet at all. This project is a small self-hosted app, not
a hardened multi-tenant service: it rate-limits login attempts per IP but has no account lockout,
no CAPTCHA, and no intrusion-banning, so a login form reachable from anywhere is a form anyone
on the internet can throw a password-guessing script at indefinitely.

Opening a port and putting a reverse proxy in front is possible, and workable if you understand
the exposure, but it's not what we'd recommend as the default path. If you do it anyway:

- Open port `5004` (or whichever port you mapped it to) in your firewall/router.
- Put a reverse proxy (Caddy, nginx, Traefik) in front of it for TLS. The app itself serves
  plain HTTP, don't expose port 5004 directly to the public internet without HTTPS in front
  of it, session cookies and API keys would otherwise travel in the clear.
- Update `YB_ALLOWED_ORIGINS` in `.env` to match the public origin you're serving from
  (defaults to `http://localhost:5004`).
- Use a strong, unique password for every account exposed this way.

## Gemini API key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
2. Sign in with a Google account and create an API key. The free tier is enough to get
   started, video/PDF analysis and quiz generation stay within it for light use.
3. Either paste it into `.env` as `GEMINI_API_KEY` (system-wide default for every user), or
   have each user paste their own key into Settings (BYOK, takes priority over the system
   default when set).

## YouTube recommendations (optional)

Goal and daily recommendations need a YouTube Data API v3 key, separate from the Gemini key
above. Without one, the app doesn't error, it shows a message in the UI pointing back to this
section, everything else (video import, quizzes, SRS) works fine without it.

Unlike the Gemini key, this one is admin-only: there is no per-user BYOK option in Settings
for it, it can only be set in `.env`. One shared key covers every user on the instance.

1. Go to [console.cloud.google.com](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
   and enable "YouTube Data API v3" on a project.
2. Create an API key for that project.
3. Paste it into `.env` as `YOUTUBE_API_KEY` and restart (`docker compose up -d`).

## Telegram notifications (optional)

Selfhosted mode has no managed bot, each instance brings its own:

1. Message [@BotFather](https://t.me/BotFather) on Telegram, run `/newbot`, and follow the
   prompts to get a bot token.
2. In Studiamo, go to Settings → Notifications, paste the bot token, and follow the in-app
   instructions to link your Telegram chat ID.
3. Toggle on the notification categories you want (quizzes, streaks, inactivity reminders).

## Storage & upload limits (optional)

By default, self-hosted mode has no disk quotas or file upload caps (uncapped). If you want to prevent users from filling up host disk space, you can set optional limits in `.env`:

- `MAX_USER_STORAGE_GB`: maximum total disk usage allowed per user directory in gigabytes (e.g. `2` for 2 GB), or use `MAX_USER_STORAGE_MB` (e.g. `2048`).
- `MAX_FILE_UPLOAD_MB`: maximum allowed file size per single document/video upload in megabytes (e.g. `50` for 50 MB).

If left unset or set to `0`, uploads and storage remain uncapped.

## Running without Docker

If you'd rather run the app directly on the host and only containerize Postgres:

```bash
docker compose up -d postgres
cp .env.selfhosted.example .env  # already points DATABASE_URL at localhost:5432
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./scripts/build_css.sh
uvicorn app.main:app --port 5004
```

`localhost:5432` works here because Postgres's container port is published to the host. The
full `docker compose up -d` path above overrides this to the internal Docker network's
service name instead, since the app itself is also containerized there.

## Backups

Three named Docker volumes hold everything that matters:

- `studiamo_pgdata`: the Postgres database (accounts, videos, quizzes, goals, everything
  structured).
- `studiamo_users`: uploaded files and generated per-user content on disk.
- `studiamo_vapid`: the push-notification signing key. Losing this invalidates every
  browser's push subscription, not catastrophic, but everyone has to re-enable push after.

Back up the database with `pg_dump` through the running container:

```bash
docker compose exec postgres pg_dump -U studiamo studiamo > backup-$(date +%F).sql
```

Back up the other two volumes with a throwaway container that mounts them read-only:

```bash
docker run --rm -v studiamo_users:/data:ro -v "$PWD":/backup alpine \
  tar czf /backup/studiamo-users-$(date +%F).tar.gz -C /data .
```

## Updating

```bash
docker compose pull
docker compose up -d
```

This pulls the latest published image and restarts the container, no local build required.
The schema sync runs again automatically on the new container's startup and only ever adds,
it never drops or rewrites your existing data.

Building from source instead:

```bash
git pull
docker compose up -d --build
```

## Uninstalling

```bash
docker compose down
```

This stops and removes the containers but leaves the named volumes (and therefore your data)
intact. Add `-v` to also delete the volumes and everything in them, if you're sure.

## Troubleshooting

- **`docker compose up -d` fails with `unknown shorthand flag: 'd' in -d`**: your `docker`
  CLI doesn't have the Compose plugin, `compose` isn't being recognized as a subcommand at
  all, so `up -d` gets parsed as top-level `docker` flags instead and chokes on `-d`. Usually
  means Docker was installed CLI-only (e.g. `brew install docker` on macOS, which gets you
  the client binary but no daemon and no Compose plugin) rather than the actual Docker
  Desktop app. On macOS: `brew uninstall docker && brew install --cask docker`, then launch
  Docker Desktop from Applications before retrying.
- **Build fails with `failed to xattr .../._.env: operation not permitted`**: only happens
  when building locally (`--build`); the plain `docker compose up -d` path pulls the image
  and never touches your project folder as a build context. The project folder is on an
  external/USB or network-mounted volume. macOS creates hidden `._filename` metadata
  sidecar files there, and Docker's build can't read/write extended attributes on them.
  Copy the folder onto the machine's actual internal disk first, then build from there.
- **`studiamo-web` never turns healthy**: `docker compose logs studiamo-web` first. A schema
  sync failure logs loudly at startup rather than failing silently.
- **Can't reach the app after `docker compose up -d`**: confirm `docker compose ps` shows
  both containers running, then check the port mapping matches what you're browsing to.
- **Sessions keep logging out**: you skipped setting `YB_SECRET_KEY`, see the Quickstart
  section above.
- **"No new recommendations available" never goes away**: goal/daily recommendations need a
  `YOUTUBE_API_KEY`, separate from the Gemini key, see the YouTube recommendations section
  above. Everything else works without it.
