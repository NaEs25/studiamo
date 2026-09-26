#!/usr/bin/env bash
# Rebuilds app/static/css/tailwind-built.css from the current templates.
#
# tailwind-built.css is gitignored, not committed : both studiamo.service and
# studiamo-staging.service run this as ExecStartPre so the compiled CSS is
# always regenerated fresh from whatever's checked out, in either worktree,
# with no manual build-and-commit step and no risk of the two drifting.
set -euo pipefail
cd "$(dirname "$0")/.."

TAILWIND_VERSION="v3.4.19"
# SHA-256 of tailwindcss-linux-x64 for the version above, from the release's sha256sums.txt.
# Update both together when bumping the version (and in the Dockerfile).
TAILWIND_SHA256="4af3198c015616ea7d6617974ec3d70d987ecc00c1ca8463b0a30fd65cc7c06e"
TAILWIND_BIN="bin/tailwindcss"

if [ ! -x "$TAILWIND_BIN" ]; then
    mkdir -p bin
    TAILWIND_TMP="$(mktemp)"
    trap 'rm -f "$TAILWIND_TMP"' EXIT
    curl -sfL -o "$TAILWIND_TMP" \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64"
    echo "${TAILWIND_SHA256}  ${TAILWIND_TMP}" | sha256sum -c --quiet -
    install -m 755 "$TAILWIND_TMP" "$TAILWIND_BIN"
fi

"$TAILWIND_BIN" -c tailwind.config.js -i app/static/css/tailwind-input.css \
    -o app/static/css/tailwind-built.css --minify
