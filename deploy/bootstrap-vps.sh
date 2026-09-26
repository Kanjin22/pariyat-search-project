#!/usr/bin/env bash
# ติดตั้ง pariyat-search บน VPS Ubuntu 22.04 / 24.04 (เช่น Oracle Cloud Always Free)
# วิธีใช้:
#   sudo REPO_URL=https://github.com/Kanjin22/pariyat-search-project.git DOMAIN=search.example.com bash deploy/bootstrap-vps.sh
# ตัวแปรที่ปรับได้: REPO_URL, BRANCH, APP_DIR, DATA_ROOT, ENV_DIR, SERVICE_NAME, RUN_USER, DOMAIN
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Kanjin22/pariyat-search-project.git}"
BRANCH="${BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/pariyat-search}"
DATA_ROOT="${DATA_ROOT:-/var/lib/pariyat-search}"
ENV_DIR="${ENV_DIR:-/etc/pariyat-search}"
SERVICE_NAME="${SERVICE_NAME:-pariyat-search}"
RUN_USER="${RUN_USER:-${SUDO_USER:-ubuntu}}"
DOMAIN="${DOMAIN:-}"

log() { printf '\n=== %s ===\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "ต้องรันด้วย sudo (ตัวอย่าง: sudo DOMAIN=search.example.com bash deploy/bootstrap-vps.sh)" >&2
  exit 1
fi

log "1/8 ติดตั้งแพ็กเกจที่จำเป็น"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y python3 python3-venv python3-pip git nginx curl unzip ca-certificates

log "2/8 เตรียมโฟลเดอร์"
mkdir -p "$APP_DIR" "$DATA_ROOT/data" "$DATA_ROOT/logs" "$DATA_ROOT/backups" "$ENV_DIR"

log "3/8 ดึงโค้ดจาก $REPO_URL (branch: $BRANCH)"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only
elif [ -z "$(ls -A "$APP_DIR" 2>/dev/null || true)" ]; then
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
  echo "โฟลเดอร์ $APP_DIR มีไฟล์อยู่แล้วและไม่ใช่ git repo - ใช้โค้ดที่มีอยู่ (ข้ามการ clone)"
fi
git config --global --add safe.directory "$APP_DIR" || true

log "4/8 สร้าง virtualenv และติดตั้งไลบรารี"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

log "5/8 สร้างไฟล์ environment: $ENV_DIR/$SERVICE_NAME.env"
if [ ! -f "$ENV_DIR/$SERVICE_NAME.env" ]; then
  SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  sed "s|^FLASK_SECRET_KEY=.*|FLASK_SECRET_KEY=$SECRET|" \
    "$APP_DIR/deploy/pariyat-search.env.example" > "$ENV_DIR/$SERVICE_NAME.env"
  chmod 600 "$ENV_DIR/$SERVICE_NAME.env"
  echo "สร้างไฟล์ env ใหม่แล้ว (ต้องเติม STAFF_USERNAME / STAFF_PASSWORD_HASH / PARIYAT_API_* เอง)"
else
  echo "มีไฟล์ env อยู่แล้ว - ไม่ทับของเดิม"
fi

log "6/8 ติดตั้ง systemd service ($SERVICE_NAME)"
install -m 644 "$APP_DIR/deploy/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
if [ "$RUN_USER" != "ubuntu" ]; then
  sed -i "s|^User=.*|User=$RUN_USER|; s|^Group=.*|Group=$RUN_USER|" "/etc/systemd/system/$SERVICE_NAME.service"
fi
chown -R "$RUN_USER:$RUN_USER" "$APP_DIR" "$DATA_ROOT"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

log "7/8 ตั้งค่า nginx"
SERVER_NAME="${DOMAIN:-_}"
sed "s|server_name .*;|server_name $SERVER_NAME;|" \
  "$APP_DIR/deploy/nginx-pariyat-search.conf" > "/etc/nginx/sites-available/$SERVICE_NAME"
ln -sf "/etc/nginx/sites-available/$SERVICE_NAME" "/etc/nginx/sites-enabled/$SERVICE_NAME"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

log "8/8 ตรวจสุขภาพระบบ"
sleep 6
systemctl --no-pager --lines=20 status "$SERVICE_NAME" || true
echo "--- /health ผ่าน gunicorn ---"
curl -fsS http://127.0.0.1:8000/health || echo "(ยังไม่ตอบ - ดู log: journalctl -u $SERVICE_NAME -n 80 --no-pager)"
echo "--- /health ผ่าน nginx (พอร์ต 80) ---"
curl -fsS "http://127.0.0.1/health" -H "Host: ${DOMAIN:-localhost}" || true

cat <<EOF

============================================================
ขั้นถัดไปที่ต้องทำเอง
1) เติมค่าในไฟล์ env:
   sudo nano $ENV_DIR/$SERVICE_NAME.env
   (STAFF_USERNAME, STAFF_PASSWORD_HASH, PARIYAT_API_USER, PARIYAT_API_PASS)
   แล้ว: sudo systemctl restart $SERVICE_NAME

2) อัปโหลดข้อมูลจากเครื่อง PC เข้า VPS (จากฝั่ง PC Windows):
   scp dist\\pariyat-data-*.zip ubuntu@<VPS_IP>:/home/ubuntu/
   แล้วบน VPS: sudo DATA_DIR=$DATA_ROOT/data bash $APP_DIR/deploy/seed_data.sh /home/ubuntu/pariyat-data-XXXX.zip

3) เปิด firewall ถ้ายังไม่ได้เปิดพอร์ต 80/443:
   sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw --force enable
   (Oracle Cloud ต้องเปิด ingress 80/443 ใน Security List ด้วย)

4) ออกใบรับรอง SSL (ต้องมีโดเมนชี้มาที่ VPS แล้ว):
   sudo apt-get install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d ${DOMAIN:-your-domain.com}
============================================================
EOF
