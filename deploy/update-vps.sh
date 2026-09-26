#!/usr/bin/env bash
# อัปเดตเว็บบน VPS ให้เป็นโค้ดล่าสุดจาก git (ใช้ทุกครั้งหลัง push จากเครื่อง PC)
# วิธีใช้: sudo bash /opt/pariyat-search/deploy/update-vps.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/pariyat-search}"
SERVICE_NAME="${SERVICE_NAME:-pariyat-search}"
BRANCH="${BRANCH:-main}"

log() { printf '\n=== %s ===\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "ต้องรันด้วย sudo" >&2
  exit 1
fi

git config --global --add safe.directory "$APP_DIR" || true

log "1/4 ดึงโค้ดล่าสุด"
git -C "$APP_DIR" fetch --all --prune
git -C "$APP_DIR" checkout "$BRANCH"
git -C "$APP_DIR" pull --ff-only

log "2/4 อัปเดตไลบรารี (ถ้ามีการแก้ requirements.txt)"
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

log "3/4 restart service"
systemctl restart "$SERVICE_NAME"
sleep 6
systemctl --no-pager --lines=20 status "$SERVICE_NAME" || true

log "4/4 ตรวจสุขภาพ"
curl -fsS http://127.0.0.1:8000/health && echo || {
  echo "คำเตือน: /health ไม่ตอบ - ดู log ด้วย: journalctl -u $SERVICE_NAME -n 100 --no-pager" >&2
  exit 1
}
echo "อัปเดตเสร็จเรียบร้อย"
