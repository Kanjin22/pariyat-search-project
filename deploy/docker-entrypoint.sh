#!/usr/bin/env sh
# entrypoint สำหรับ Docker image ของ pariyat-search
# หน้าที่:
#   1) เตรียมโฟลเดอร์ข้อมูลถาวร (data / logs / backups)
#   2) ถ้า volume ยังว่าง ให้ seed ข้อมูลตั้งต้นจาก /app/data ที่อยู่ใน image
set -e

DATA_DIR="${RESULTS_DATA_DIR:-/var/lib/pariyat-search/data}"
BACKUPS_DIR="${BACKUPS_DIR:-/var/lib/pariyat-search/backups}"
LOGS_DIR="${LOGS_DIR:-/var/lib/pariyat-search/logs}"

mkdir -p "$DATA_DIR" "$BACKUPS_DIR" "$LOGS_DIR"

seed_from_image() {
  [ -d /app/data ] || return 0
  for src in /app/data/*.json; do
    [ -e "$src" ] || continue
    name=$(basename "$src")
    if [ ! -e "$DATA_DIR/$name" ]; then
      echo "[entrypoint] seed: $name"
      cp "$src" "$DATA_DIR/$name"
    fi
  done
}

seed_from_image

echo "[entrypoint] RESULTS_DATA_DIR=$DATA_DIR"
echo "[entrypoint] BACKUPS_DIR=$BACKUPS_DIR"
echo "[entrypoint] LOGS_DIR=$LOGS_DIR"
echo "[entrypoint] start: $*"

exec "$@"
