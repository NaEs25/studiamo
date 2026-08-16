# syntax=docker/dockerfile:1

# --- Stage 1: compile Tailwind CSS ---
# Uses the standalone Tailwind CLI (no Node/npm), matching scripts/build_css.sh so the
# containerized build produces the same output as a bare-metal deploy.
FROM python:3.12-slim AS css-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG TAILWIND_VERSION=v3.4.19
RUN curl -sL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss

# Only what tailwind.config.js's content globs scan, plus the input stylesheet, so this
# layer only invalidates when templates/JS/config actually change.
COPY tailwind.config.js ./
COPY app/templates ./app/templates
COPY app/static/js ./app/static/js
COPY app/static/css/tailwind-input.css ./app/static/css/tailwind-input.css

RUN tailwindcss -c tailwind.config.js \
        -i app/static/css/tailwind-input.css \
        -o app/static/css/tailwind-built.css --minify

# --- Stage 2: runtime image ---
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runs as an unprivileged user, the app also writes to users/<user_uuid>/items/ on a
# mounted volume, not just static file serving, so it needs a real home to write into.
RUN groupadd --gid 1000 studiamo && useradd --uid 1000 --gid studiamo --create-home studiamo

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY tailwind.config.js ./

# Compiled by stage 1, never shipped from a local build context, keeps the ~85MB
# platform-specific tailwindcss binary itself out of the final image entirely.
COPY --from=css-builder /build/app/static/css/tailwind-built.css ./app/static/css/tailwind-built.css

RUN mkdir -p users && chown -R studiamo:studiamo /app

USER studiamo

ENV PYTHONUNBUFFERED=1 \
    PORT=5004

EXPOSE 5004

# Plain urllib rather than curl/wget, keeps the runtime image free of extra packages.
# "/" is unauthenticated (serves the landing page) so this works without credentials.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5004/', timeout=3).status == 200 else 1)"

# The schema applies itself on startup (app/schema.py::ensure_schema_up_to_date, run from
# app/main.py's lifespan), so there is no separate migration step to run here.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5004"]
