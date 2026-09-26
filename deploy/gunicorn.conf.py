"""ค่า config ของ Gunicorn ที่ใช้ร่วมกันทั้ง systemd และ Docker

เรียกใช้: gunicorn --config deploy/gunicorn.conf.py app.app:app
ปรับค่าได้ผ่าน environment variable โดยไม่ต้องแก้ไฟล์
"""
import os


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, '') or '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ค่าจาก Render/Koyeb/Hugging Face จะส่ง PORT มาให้ ถ้าไม่มีให้ใช้ 8000
_default_bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
bind = str(os.getenv('GUNICORN_BIND', '') or '').strip() or _default_bind

workers = _env_int('WEB_CONCURRENCY', 2)
threads = _env_int('GUNICORN_THREADS', 4)
# งาน import Excel / โหลด snapshot ก้อนใหญ่ใช้เวลานาน จึงตั้ง timeout สูง
timeout = _env_int('GUNICORN_TIMEOUT', 300)
graceful_timeout = _env_int('GUNICORN_GRACEFUL_TIMEOUT', 60)
keepalive = _env_int('GUNICORN_KEEPALIVE', 5)

# preload = import แอปครั้งเดียวก่อน fork worker (ประหยัด RAM และเริ่มเร็ว)
preload_app = True

# ให้ nginx ที่ proxy มาส่ง X-Forwarded-* ได้
forwarded_allow_ips = '*'

# ค่าเริ่มต้นส่ง log ออก stdout/stderr (systemd -> journalctl, Docker -> docker logs)
accesslog = str(os.getenv('GUNICORN_ACCESS_LOG', '-') or '-')
errorlog = str(os.getenv('GUNICORN_ERROR_LOG', '-') or '-')
loglevel = str(os.getenv('GUNICORN_LOG_LEVEL', 'info') or 'info')
capture_output = True
