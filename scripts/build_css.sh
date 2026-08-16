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
TAILWIND_BIN="bin/tailwindcss"

if [ ! -x "$TAILWIND_BIN" ]; then
    mkdir -p bin
    curl -sL -o "$TAILWIND_BIN" \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64"
    chmod +x "$TAILWIND_BIN"
fi

"$TAILWIND_BIN" -c tailwind.config.js -i app/static/css/tailwind-input.css \
    -o app/static/css/tailwind-built.css --minify
