#!/bin/sh
# Runs every minute on the VPS (systemd timer legacy-real-update). Pulls main from GitHub and restarts the
# app when there's a new commit -- but never while a job is running (a restart would kill it); it retries
# on the next tick instead.
cd /root/maps-leads || exit 0
git fetch -q origin main || exit 0
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] && exit 0
if grep -ls '"status": "running"' jobs/*.json >/dev/null 2>&1; then
    echo "update waiting: a job is running"
    exit 0
fi
git reset -q --hard origin/main
systemctl restart maps-chat
echo "updated to $(git log --oneline -1)"
