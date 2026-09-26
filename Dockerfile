# syntax=docker/dockerfile:1
# ใช้สำหรับ deploy บนโฮสต์ที่รองรับ Docker:
#   - VPS ที่ลง Docker (Oracle Cloud / DigitalOcean / Hetzner / ฯลฯ)
#   - Koyeb / Fly.io / Railway
#   - Hugging Face Spaces (Docker SDK)
# รายละเอียดวิธีใช้ทั้งหมดอยู่ใน deploy/DEPLOY_FREE_HOSTING.md
FROM python:3.10.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Bangkok \
    PORT=8000 \
    RESULTS_DATA_DIR=/var/lib/pariyat-search/data \
    BACKUPS_DIR=/var/lib/pariyat-search/backups \
    LOGS_DIR=/var/lib/pariyat-search/logs \
    GUNICORN_BIND=0.0.0.0:8000

WORKDIR /app

# tzdata = ให้ TZ=Asia/Bangkok ทำงานถูกต้อง / curl = ใช้ใน HEALTHCHECK
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/deploy/docker-entrypoint.sh /app/deploy/*.sh \
    && mkdir -p "$RESULTS_DATA_DIR" "$BACKUPS_DIR" "$LOGS_DIR"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["gunicorn", "--config", "deploy/gunicorn.conf.py", "app.app:app"]
