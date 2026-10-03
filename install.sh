#!/bin/bash
# One-time setup. Run from the project folder:  sudo ./install.sh
# Installs packages, creates the venv, installs + starts the systemd timer, enables NTP.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo: sudo ./install.sh"; exit 1; }
DIR="$(cd "$(dirname "$0")" && pwd)"
USR="${SUDO_USER:?run with sudo from your normal user, not as root}"

echo "== packages"
apt-get install -y adb tesseract-ocr python3-venv unzip

echo "== python venv"
sudo -u "$USR" bash -c "cd '$DIR' && [ -x .venv/bin/python ] || python3 -m venv .venv; .venv/bin/pip install -q -r requirements.txt"

echo "== systemd units"
for f in adb-server.service android-cron.service android-cron.timer; do
  sed -e "s|__USER__|$USR|g" -e "s|__DIR__|$DIR|g" "$DIR/systemd/$f" > "/etc/systemd/system/$f"
done
sudo -u "$USR" adb kill-server 2>/dev/null || true   # the service takes over the adb server
systemctl daemon-reload
systemctl enable --now adb-server.service android-cron.timer

echo "== time sync"
timedatectl set-ntp true

echo; systemctl list-timers android-cron.timer --no-pager
echo; echo "done. logs: $DIR/logs/runner.log   status: $DIR/.venv/bin/python run.py --list"
