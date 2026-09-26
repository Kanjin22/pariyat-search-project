#!/usr/bin/env bash
# Smoke test สำหรับตรวจ deploy/seed_data.sh บนเครื่อง Windows (git-bash) ก่อนขึ้น VPS
# วิธีใช้ (Windows):  & 'C:\Program Files\Git\bin\bash.exe' -lc 'bash deploy/smoke_test_seed_windows.sh'
#
# เหตุผลที่ต้องมี:
#   - git-bash 'unzip' บน Windows มี path quirk -> ใช้ shim ที่จำลอง unzip ของ Linux
#   - ไม่มี systemctl/curl จริง -> ใช้ shim แทน (ผลสุดท้ายจะ exit=1 เพราะไม่มีเซิร์ฟเวอร์ในเครื่อง ถือว่าปกติ)
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SEED_SCRIPT="$REPO_ROOT/deploy/seed_data.sh"
ZIP_PATH="$(ls "$REPO_ROOT"/dist/pariyat-data-*.zip 2>/dev/null | head -1)"

if [ -z "$ZIP_PATH" ]; then
  echo "ยังไม่มีไฟล์แพ็กข้อมูล - รันก่อน: powershell -ExecutionPolicy Bypass -File scripts/pack_data_for_deploy.ps1" >&2
  exit 1
fi

T=/tmp/pariyat-seed-smoke
rm -rf "$T"
mkdir -p "$T/shim"

cat > "$T/shim/systemctl" <<'EOF'
#!/bin/sh
echo "[shim] systemctl $*"
EOF

cat > "$T/shim/unzip" <<'EOF'
#!/bin/sh
set -e
ZIP=""
DEST="."
while [ $# -gt 0 ]; do
  case "$1" in
    -o|-q) shift ;;
    -d) DEST="$2"; shift 2 ;;
    *) ZIP="$1"; shift ;;
  esac
done
python -c "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$ZIP" "$DEST"
EOF

chmod +x "$T/shim/systemctl" "$T/shim/unzip"
echo "ZIP = $ZIP_PATH"

echo
echo "=== รันครั้งที่ 1 (ไม่ทับไฟล์เดิม) ==="
PATH="$T/shim:$PATH" ALLOW_NONROOT=1 DATA_DIR="$T/data" BACKUPS_DIR="$T/backups" \
  bash "$SEED_SCRIPT" "$ZIP_PATH" || echo "(exit=$? - ปกติ เพราะไม่มีเซิร์ฟเวอร์ในเครื่อง)"
echo "ไฟล์ใน data: $(ls -1 "$T/data" | wc -l)"
echo "ตัวอย่าง: $(ls -1 "$T/data" | head -3 | tr '\n' ' ')"
echo "backups: $(ls -1 "$T/backups" | tr '\n' ' ')"

echo
echo "=== รันครั้งที่ 2 (FORCE=1 ต้องสำรองของเดิมก่อน) ==="
PATH="$T/shim:$PATH" ALLOW_NONROOT=1 FORCE=1 DATA_DIR="$T/data" BACKUPS_DIR="$T/backups" \
  bash "$SEED_SCRIPT" "$ZIP_PATH" || echo "(exit=$? - ปกติ)"
echo "backups: $(ls -1 "$T/backups" | tr '\n' ' ')"

echo
echo "=== ตรวจว่าไฟล์ที่ seed อ่านได้จริง ==="
head -c 60 "$T/data/api_snapshot_2568.json"; echo
echo "รวมทั้งหมด: $(ls -1 "$T/data" | wc -l) ไฟล์"
