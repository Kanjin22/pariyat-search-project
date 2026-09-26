#!/usr/bin/env bash
# ย้ายข้อมูลจากไฟล์ zip (ที่สร้างด้วย scripts/pack_data_for_deploy.ps1 บนเครื่อง PC)
# เข้าโฟลเดอร์ข้อมูลถาวรของ VPS โดยสำรองของเดิมไว้ก่อน
#
# วิธีใช้: sudo bash deploy/seed_data.sh /home/ubuntu/pariyat-data-20260926-2230.zip
#          FORCE=1 เพื่อทับไฟล์เดิมทั้งหมด (ค่าเริ่มต้นจะไม่ทับไฟล์ที่มีอยู่แล้ว)
set -euo pipefail

ZIP_PATH="${1:-}"
DATA_DIR="${DATA_DIR:-/var/lib/pariyat-search/data}"
BACKUPS_DIR="${BACKUPS_DIR:-/var/lib/pariyat-search/backups}"
SERVICE_NAME="${SERVICE_NAME:-pariyat-search}"
FORCE="${FORCE:-0}"

if [ -z "$ZIP_PATH" ]; then
  echo "วิธีใช้: sudo bash $0 <path-to-zip>" >&2
  exit 1
fi
[ -f "$ZIP_PATH" ] || { echo "ไม่พบไฟล์: $ZIP_PATH" >&2; exit 1; }
if [ "$(id -u)" -ne 0 ] && [ "${ALLOW_NONROOT:-0}" != "1" ]; then
  echo "ต้องรันด้วย sudo (ถ้ารันใน container แบบไม่ใช่ root ให้ตั้ง ALLOW_NONROOT=1)" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

echo "=== 1/5 แตกไฟล์ zip ==="
unzip -o "$ZIP_PATH" -d "$WORK_DIR" >/dev/null
SRC_DIR="$WORK_DIR"
if [ -d "$WORK_DIR/data" ]; then
  SRC_DIR="$WORK_DIR/data"
fi
echo "ต้นทาง: $SRC_DIR"

echo "=== 2/5 สำรองข้อมูลเดิมใน $DATA_DIR ==="
mkdir -p "$BACKUPS_DIR" "$DATA_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
if [ -n "$(ls -A "$DATA_DIR" 2>/dev/null || true)" ]; then
  BACKUP_FILE="$BACKUPS_DIR/data_before_seed_$STAMP.tar.gz"
  tar -czf "$BACKUP_FILE" -C "$DATA_DIR" .
  echo "สำรองไว้ที่: $BACKUP_FILE"
else
  echo "โฟลเดอร์ข้อมูลว่าง - ไม่ต้องสำรอง"
fi

echo "=== 3/5 คัดลอกไฟล์ข้อมูล (FORCE=$FORCE) ==="
copy_count=0
skip_count=0
for src in "$SRC_DIR"/*.json "$SRC_DIR"/*.sqlite3; do
  [ -f "$src" ] || continue
  name="$(basename "$src")"
  if [ -e "$DATA_DIR/$name" ] && [ "$FORCE" != "1" ]; then
    skip_count=$((skip_count + 1))
    echo "  ข้าม (มีอยู่แล้ว): $name"
    continue
  fi
  cp -f "$src" "$DATA_DIR/$name"
  copy_count=$((copy_count + 1))
done
echo "คัดลอก $copy_count ไฟล์ / ข้าม $skip_count ไฟล์"

echo "=== 4/5 ตั้งสิทธิ์การเข้าถึง ==="
OWNER="$(stat -c '%U:%G' "$DATA_DIR")"
if [ "$(id -u)" -eq 0 ]; then
  chown -R "$OWNER" "$DATA_DIR"
  echo "เจ้าของไฟล์: $OWNER"
else
  echo "(ไม่ได้รันเป็น root - ข้ามการ chown)"
fi
find "$DATA_DIR" -type f -name '*.json' -exec chmod 640 {} +

echo "=== 5/5 restart service ==="
systemctl restart "$SERVICE_NAME"
sleep 6
curl -fsS http://127.0.0.1:8000/health && echo || {
  echo "คำเตือน: /health ไม่ตอบ - ดู log: journalctl -u $SERVICE_NAME -n 100 --no-pager" >&2
  exit 1
}
cat <<EOF

เสร็จแล้ว! ตรวจว่าข้อมูลขึ้นครบ (ตัวเลข count ต้องมากกว่า 0):
  curl -s http://127.0.0.1:8000/get_data_info?year=2568
  curl -s http://127.0.0.1:8000/get_data_info?year=2569

ถ้า count เป็น 0 ให้ตรวจว่าไฟล์ api_snapshot_<ปี>.json อยู่ใน $DATA_DIR จริง:
  ls -lh $DATA_DIR
EOF
