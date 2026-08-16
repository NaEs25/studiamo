#!/usr/bin/env bash
set -euo pipefail

echo "==> Copying systemd service files to /etc/systemd/system/..."
cp /home/naes/studiamo/scripts/systemd/studiamo.service /etc/systemd/system/
cp /home/naes/studiamo/scripts/systemd/studiamo-staging.service /etc/systemd/system/

echo "==> Reloading systemd daemon..."
systemctl daemon-reload

echo "==> Restarting studiamo.service (prod) and studiamo-staging.service (staging)..."
systemctl restart studiamo.service studiamo-staging.service

echo "==> Done! Checking status:"
systemctl status studiamo.service --no-pager -n 5
systemctl status studiamo-staging.service --no-pager -n 5
