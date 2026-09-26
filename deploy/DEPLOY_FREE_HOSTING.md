# คู่มือย้าย pariyat-search ขึ้นโฮสต์ฟรีถาวร (Oracle Cloud Always Free / Docker)

> ปรับปรุง: 26 ก.ย. 2026 · ใช้กับโปรเจค `D:\pariyat-search-project`
> ไฟล์ชุด deploy ที่เพิ่มให้: `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitattributes`,
> `deploy/gunicorn.conf.py`, `deploy/docker-entrypoint.sh`, `deploy/pariyat-search.service`,
> `deploy/nginx-pariyat-search.conf`, `deploy/pariyat-search.env.example`,
> `deploy/bootstrap-vps.sh`, `deploy/update-vps.sh`, `deploy/seed_data.sh`,
> `deploy/required_data_files.txt`, `scripts/pack_data_for_deploy.ps1`

## 0) ก่อนเริ่ม

### 0.1 รู้ก่อนว่าทำไมเว็บล่ม
บริการเดิมบน Render (`https://pariyat-search.onrender.com`) **ถูกระงับ (suspended)** ไม่ใช่โค้ดพัง:

```
HTTP/1.1 503 Service Unavailable
x-render-routing: suspend
<title>Service Suspended</title>
```

โค้ดยังสมบูรณ์ — ทดสอบในเครื่องแล้ว: `/health` = 200, `/` = 200, `/get_data_info?year=2568` = 3254 รายการ, `/search?q=...` คืนผลจริง

### 0.2 กู้ความลับจาก Render (สำคัญมาก — ทำก่อนลบ service)
1. เข้า https://dashboard.render.com → service `pariyat-search` (ตัวที่ suspended) → แท็บ **Environment**
2. จดค่าต่อไปนี้เก็บไว้ใน password manager:
   - `PARIYAT_API_USER`, `PARIYAT_API_PASS` (รหัส API ต้นทางข้อมูล — **ไม่มีอยู่ในเครื่อง PC เลย**)
   - `PARIYAT_CERT_API_USER`, `PARIYAT_CERT_API_PASS` (ถ้ามี)
   - `FLASK_SECRET_KEY`, `STAFF_USERNAME`, `STAFF_PASSWORD_HASH`
3. ดูเมนู **Disks** ว่ามีดิสก์ผูกอยู่ไหม และ mount path คืออะไร (เช่น `/var/data`)
4. **อย่าเพิ่งลบ service/database** จนกว่าจะคัดลอกครบและเว็บใหม่ใช้งานได้

### 0.3 แพ็กข้อมูลจากเครื่อง PC
```powershell
cd D:\pariyat-search-project
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\pack_data_for_deploy.ps1
```
ได้ไฟล์ `dist\pariyat-data-<วันเวลา>.zip` (~2 MB, 19 ไฟล์) — ตรวจแล้วว่าคัดลอก `api_snapshot_2568/2569`, `exam_results_*`, `certificate_snapshot_*`, `staff_accounts.json`, `analytics.sqlite3` ครบ
(ถ้าต้องการแนบ `.env` ในซิปด้วย ให้เพิ่ม `-IncludeEnv` — ระวังเพราะมีความลับ)

### 0.4 push ไฟล์ชุด deploy ขึ้น GitHub
```powershell
cd D:\pariyat-search-project
git add Dockerfile docker-compose.yml .dockerignore .gitattributes deploy scripts/pack_data_for_deploy.ps1
git commit -m "Add deployment kit for free-forever hosting (Docker + systemd + nginx + data seeding)"
git push origin main
```
> ถ้าไม่สะดวก push บน VPS ใช้วิธีคัดลอกทั้งโฟลเดอร์แทนได้:
> `scp -r D:\pariyat-search-project ubuntu@<VPS_IP>:/tmp/` แล้ว `sudo mv /tmp/pariyat-search-project /opt/pariyat-search`
> (ให้ลบ `.venv`, `data`, `logs`, `backups`, `dist` ออกก่อนคัดลอก เพื่อลดขนาด)

### 0.5 สรุปคำสั่งแบบเร็ว (TL;DR)
```powershell
# ── บนเครื่อง PC ────────────────────────────────────────────────
cd D:\pariyat-search-project
powershell -ExecutionPolicy Bypass -File scripts\pack_data_for_deploy.ps1   # 1. แพ็กข้อมูล
git add Dockerfile docker-compose.yml .dockerignore .gitattributes deploy scripts/pack_data_for_deploy.ps1
git commit -m "Add deployment kit"                                          # 2. commit
git push origin main                                                        # 3. push
```
```bash
# ── บน VPS (Oracle Cloud Always Free) ───────────────────────────
sudo apt-get update -y && sudo apt-get install -y git
sudo git clone https://github.com/Kanjin22/pariyat-search-project.git /opt/pariyat-search
sudo DOMAIN=search.example.com bash /opt/pariyat-search/deploy/bootstrap-vps.sh   # 4. ติดตั้ง+รัน
sudo nano /etc/pariyat-search/pariyat-search.env                                  # 5. ใส่ค่าลับ + API
sudo bash /opt/pariyat-search/deploy/seed_data.sh /home/ubuntu/pariyat-data-XXXX.zip  # 6. ย้ายข้อมูล
```
> ก่อนข้อ 6 ต้องอัปโหลดซิปขึ้น VPS ก่อน: `scp D:\pariyat-search-project\dist\pariyat-data-*.zip ubuntu@<VPS_IP>:/home/ubuntu/`
> ไฟล์ซิปถูกสร้างให้เข้ากับ `unzip` บน Linux แล้ว (entry name เป็น `data/...` ทดสอบผ่าน)

## 1) ภาพรวมหลังย้าย

```
ผู้ใช้ → https://your-domain  →  Nginx (80/443)
                                   ↓ proxy 127.0.0.1:8000
                              Gunicorn (2 workers × 4 threads)
                                   ↓
                              Flask  app.app:app
                                   ↓
                    /var/lib/pariyat-search/data  ← ข้อมูลถาวร (อยู่นอก repo)
```

| path บน VPS | หน้าที่ |
|---|---|
| `/opt/pariyat-search` | โค้ด (git clone) + `deploy/` |
| `/opt/pariyat-search/.venv` | Python virtualenv |
| `/etc/pariyat-search/pariyat-search.env` | ค่าลับ/ตั้งค่าทั้งหมด (chmod 600) |
| `/var/lib/pariyat-search/data` | `RESULTS_DATA_DIR` — ข้อมูลผู้สมัคร/ผลสอบ/บัญชีเจ้าหน้าที่ |
| `/var/lib/pariyat-search/backups` | `BACKUPS_DIR` — ไฟล์สำรองอัตโนมัติของระบบ |
| `/var/lib/pariyat-search/logs` | `LOGS_DIR` — `staff_activity.log` |
| `/etc/systemd/system/pariyat-search.service` | systemd unit (รัน gunicorn) |
| `/etc/nginx/sites-available/pariyat-search` | nginx vhost |

ทำไมต้องแยก `data/` ออก: ในโฟลเดอร์ repo ข้อมูลจะหายทุกครั้งที่ deploy ใหม่
ตัวแอปอ่าน path จาก `RESULTS_DATA_DIR`, `BACKUPS_DIR`, `LOGS_DIR` (ดู `app/app.py` บรรทัด 23, 38, 86)

## 2) ทางหลัก: Oracle Cloud Always Free (ฟรีถาวร — แนะนำที่สุด)

Always Free ให้: ARM Ampere A1 รวม 4 OCPU / 24 GB RAM, block storage 200 GB, egress 10 TB/เดือน, ไม่มีค่ารายเดือน
ใช้เป็น VM ธรรมดา (ไม่ใช่ serverless) จึงมี **ดิสก์ถาวรจริง** และรัน gunicorn ได้เหมือน Render

### 2.1 สมัครและเลือก Home Region
- https://www.oracle.com/th/cloud/free/ → **Start for free**
- ต้องมีบัตรเครดิต/เดบิตยืนยันตัวตน (ตัดประมาณ 1 USD แล้วคืนเป็นเครดิต)
- **Home Region เลือกแล้วเปลี่ยนไม่ได้** — เลือกใกล้ไทย เช่น Singapore (`ap-singapore-1`) หรือ Tokyo/Osaka
- อัปเกรดเป็น Pay-As-You-Go ทีหลังได้ (ยังใช้ Always Free ได้) และมักช่วยให้สร้าง ARM instance สำเร็จง่ายขึ้น

### 2.2 สร้าง VM
Compute → Instances → **Create instance**
- **Name**: `pariyat-search`
- **Image**: Ubuntu **22.04** หรือ 24.04 (Canonical)
- **Shape**: Ampere → `VM.Standard.A1.Flex` → **2 OCPU / 12 GB** (อยู่ในโควตาฟรี)
  - ถ้าขึ้น *Out of host capacity* → เปลี่ยน Availability Domain, ลอง 1 OCPU/6 GB, หรือลองซ้ำอีกครั้ง
  - ทางเลือกแรมต่ำ: `VM.Standard.E2.1.Micro` (1 OCPU/1 GB) → ต้องทำ swap (ข้อ 2.9) และลด worker
- **Networking**: ติ๊ก ✅ *Assign a public IPv4 address*
- **SSH keys**: ให้ Oracle generate แล้ว **ดาวน์โหลด private key ทันที** (โหลดได้ครั้งเดียว)
- **Boot volume**: 100 GB ก็พอ

### 2.3 เปิดพอร์ต 80/443 (พลาดข้อนี้ = เข้าเว็บจากข้างนอกไม่ได้)
**ก) ที่ฝั่ง Oracle (Cloud Firewall)**
Networking → **Virtual Cloud Networks** → VCN ของคุณ → Subnet → **Security Lists** → Default Security List → Add Ingress Rules:

| Source CIDR | IP Protocol | Destination Port Range |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

**ข) ที่ฝั่งเครื่อง (Oracle Ubuntu image มี iptables บล็อกไว้ก่อน)**
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
# ถ้าไม่พบคำสั่ง netfilter-persistent:
#   sudo apt-get install -y iptables-persistent   (ตอนติดตั้งจะมีคำถาม ให้ตอบ Yes)
```
> Oracle Linux image ใช้ firewalld: `sudo firewall-cmd --permanent --add-service=http --add-service=https && sudo firewall-cmd --reload`

### 2.4 เข้าเครื่องด้วย SSH (จาก Windows PowerShell)
```powershell
# แก้สิทธิ์ไฟล์ key ครั้งเดียว (ถ้า SSH เตือน UNPROTECTED PRIVATE KEY)
icacls "$env:USERPROFILE\Downloads\ssh-key-2026-09-26.key" /inheritance:r /grant:r "$($env:USERNAME):R"

ssh -i "$env:USERPROFILE\Downloads\ssh-key-2026-09-26.key" ubuntu@<VPS_IP>
```

### 2.5 ติดตั้งระบบทั้งหมด (คำสั่งเดียว)
```bash
sudo apt-get update -y && sudo apt-get install -y git
sudo git clone https://github.com/Kanjin22/pariyat-search-project.git /opt/pariyat-search
sudo DOMAIN=search.example.com bash /opt/pariyat-search/deploy/bootstrap-vps.sh
```
- ถ้ารันแบบไม่ใส่ `DOMAIN` จะตั้ง `server_name _;` ไว้ก่อน (เปิดด้วยไอพีได้)
- สคริปต์ทำงาน 8 ขั้น: ติดตั้งแพ็กเกจ → เตรียมโฟลเดอร์ → clone/อัปเดตโค้ด → สร้าง venv + pip install →
  สร้าง `/etc/pariyat-search/pariyat-search.env` (พร้อมสุ่ม `FLASK_SECRET_KEY`) → ติดตั้ง systemd → ตั้ง nginx → ตรวจ `/health`
- รันซ้ำได้ (idempotent) ไม่ทับไฟล์ env เดิม
- ปรับค่าด้วยตัวแปรได้ เช่น `RUN_USER=ubuntu APP_DIR=/opt/pariyat-search DATA_ROOT=/var/lib/pariyat-search`, `SERVICE_NAME=pariyat-search`, `BRANCH=main`, `REPO_URL=...`
- ถ้าไม่ใช้ git ให้คัดลอกโค้ดเอง (ข้อ 0.4) แล้วรันสคริปต์ที่ path ที่คัดลอกไป:
  `sudo APP_DIR=/opt/pariyat-search bash /opt/pariyat-search/deploy/bootstrap-vps.sh`
  (ถ้าโฟลเดอร์มีไฟล์อยู่แล้วและไม่ใช่ git repo สคริปต์จะข้ามการ clone ให้อัตโนมัติ)

### 2.6 เติมค่าลับใน env
```bash
sudo nano /etc/pariyat-search/pariyat-search.env
```
- `STAFF_USERNAME` / `STAFF_PASSWORD_HASH` — สร้าง hash ของรหัสผ่านใหม่:
  ```bash
  /opt/pariyat-search/.venv/bin/python /opt/pariyat-search/scripts/generate_password_hash.py "รหัสผ่านที่ต้องการ"
  ```
- `PARIYAT_API_USER` / `PARIYAT_API_PASS` = ค่าที่คัดลอกจาก Render (ข้อ 0.2) — ถ้าไม่มีก็ปล่อยว่างได้
  เว็บจะใช้ข้อมูลจาก snapshot ในเครื่องแทน (อ่านได้ แต่กด "ดึงข้อมูลจาก API" ไม่ได้)
- `API_SNAPSHOT_LOCK_MAX_YEAR=` เว้นว่าง (ให้ระบบล็อกอัตโนมัติถึงปีก่อนหน้า)
```bash
sudo chmod 600 /etc/pariyat-search/pariyat-search.env
sudo systemctl restart pariyat-search
systemctl status pariyat-search --no-pager | head -20
```

### 2.7 ย้ายข้อมูลขึ้น VPS (ขั้นที่ทำให้เว็บ "มีข้อมูล")
บน PC (PowerShell) — ใช้ไฟล์ที่แพ็กไว้ในข้อ 0.3:
```powershell
scp "D:\pariyat-search-project\dist\pariyat-data-20260926-222528.zip" ubuntu@<VPS_IP>:/home/ubuntu/
```
บน VPS:
```bash
sudo bash /opt/pariyat-search/deploy/seed_data.sh /home/ubuntu/pariyat-data-20260926-222528.zip
curl -s http://127.0.0.1:8000/get_data_info?year=2568    # ต้องได้ count > 0
curl -s http://127.0.0.1:8000/get_data_info?year=2569
```
- `seed_data.sh` จะ: แตกซิป → สำรองข้อมูลเดิมเป็น `backups/data_before_seed_<เวลา>.tar.gz` →
  คัดลอกเฉพาะไฟล์ที่ยังไม่มี (ไม่ทับของเจ้าหน้าที่) → ตั้งสิทธิ์ → restart service → ตรวจ `/health`
- ถ้าต้องการทับของเดิมทั้งหมด: `sudo FORCE=1 bash /opt/pariyat-search/deploy/seed_data.sh <zip>`

### 2.8 ผูกโดเมน + ติดตั้ง SSL
1. ที่ผู้ให้บริการโดเมน เพิ่ม DNS record: `A` → `search` → `<VPS_IP>` (หรือ `A` → `@`)
2. รอ DNS ทำงาน: `nslookup search.example.com` (บน PC)
3. บน VPS:
```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d search.example.com
```
4. ทดสอบ `https://search.example.com/health` → ต้องได้ JSON `"status":"healthy"`
> ยังไม่มีโดเมน? ใช้ไอพี (`http://<VPS_IP>/`) ทดสอบได้ก่อน แล้วค่อยผูกโดเมน + certbot ทีหลัง
> ถ้าอยู่หลัง Cloudflare: ตั้ง SSL/TLS mode = **Full (strict)** และอย่าเปิด Proxy ระหว่างรอ certbot

### 2.9 เครื่องแรมน้อย (1 GB) ต้องมี swap
```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```
พร้อมลดจำนวน worker ใน `/etc/pariyat-search/pariyat-search.env`:
`WEB_CONCURRENCY=1`, `GUNICORN_THREADS=2` แล้ว `sudo systemctl restart pariyat-search`

### 2.10 เช็กลิสต์ตรวจรับงาน
- [ ] `systemctl status pariyat-search` → active (running)
- [ ] `curl -s http://127.0.0.1:8000/health` → `"status":"healthy"`
- [ ] `curl -s http://127.0.0.1/get_data_info?year=2568` (ผ่าน nginx) → count > 0
- [ ] เปิดโดเมนจากมือถือ/เน็ตนอกบ้าน → เห็นหน้าเว็บ + ค้นชื่อเจอ
- [ ] `/staff/login` เข้าได้ด้วยบัญชีเจ้าหน้าที่
- [ ] `/pass-list`, `/certificates`, `/statistics` เปิดได้ไม่มี error
- [ ] ตั้ง backup อัตโนมัติ (ข้อ 4.3)

## 3) ทางเลือก: โฮสต์ฟรีแบบ Docker (Koyeb / Hugging Face Spaces / ฯลฯ)

ใช้ `Dockerfile` ที่เตรียมไว้ได้เลย — image เดียวกันรันได้ทุกที่

```bash
# ทดสอบในเครื่องก่อน (ต้องมี Docker Desktop)
docker build -t pariyat-search:latest .
docker run --rm -p 8000:8000 -v pariyat-data:/var/lib/pariyat-search \
  --env-file .env pariyat-search:latest
# หรือ: docker compose up -d --build   (ใช้ docker-compose.yml ที่เตรียมไว้)
```
บนโฮสต์ Docker ให้ตั้ง environment variables:
`FLASK_SECRET_KEY`, `STAFF_USERNAME`, `STAFF_PASSWORD_HASH`, `PARIYAT_API_*`,
`RESULTS_DATA_DIR=/var/lib/pariyat-search/data`, `BACKUPS_DIR=/var/lib/pariyat-search/backups`, `LOGS_DIR=/var/lib/pariyat-search/logs`
(ค่าเหล่านี้มีอยู่ใน `Dockerfile` แล้ว ยกเว้นตัวความลับ)
healthcheck ที่ควรตั้งกับโฮสต์: **path `/health`, port 8000**

**ข้อจำกัดที่ต้องรู้ก่อนเลือก** (นโยบายผู้ให้บริการเปลี่ยนได้ ควรเช็กราคาปัจจุบันอีกครั้ง):

| โฮสต์ | ฟรี | ดิสก์ถาวร | ข้อควรระวัง |
|---|---|---|---|
| Oracle Cloud Always Free | ✅ ฟรีถาวร | ✅ (block volume) | ตั้งค่าเอง (ข้อ 2) — **แนะนำ** |
| Koyeb | ✅ free tier (แรมน้อย) | ❌ (ต้องใช้ volume แบบเสียเงิน) | ข้อมูลหายเมื่อ redeploy → ต้อง seed ซ้ำ |
| Hugging Face Spaces (Docker) | ✅ CPU basic | ❌ (เพดาน อัปใหม่ = รีเซ็ต) | Space เป็น public (ฟรี) + sleep เมื่อไม่มีคนใช้ |
| Render (free) | ✅ | ❌ | sleep 15 นาที, แรม 512 MB — โหลด snapshot ก้อนใหญ่จะตึง |
| Railway / Fly.io | เครดิตแรก / จ่ายตามใช้ | ✅ (volume) | เหมาะถ้ายอมจ่ายเดือนละไม่กี่สิบ-ร้อยบาท |

> ถ้าเลือกโฮสต์ที่ไม่มีดิสก์ถาวร: ต้องให้ข้อมูลติดไปกับ image โดย **แตกไฟล์แพ็กข้อมูล (ข้อ 0.3) ลงในโฟลเดอร์ `data/` ของโปรเจคก่อน build/ก่อน push ขึ้นโฮสต์**
> แล้วข้อมูลผู้สมัคร/ใบประกาศจะยังใช้ได้หลังรีสตาร์ต (`Dockerfile` copy `data/*.json` เข้า image ให้อยู่แล้ว)
> แต่ **บัญชีเจ้าหน้าที่กับผลสอบที่กรอกใหม่จะหายเมื่อ redeploy** → ทางออกคือใช้ Oracle VM (ข้อ 2) หรือเช่า volume ของโฮสต์นั้น

## 4) งานประจำหลังย้ายเสร็จ

### 4.1 อัปเดตโค้ด (บน VPS)
```bash
sudo bash /opt/pariyat-search/deploy/update-vps.sh
```
(ทำ `git push` จากเครื่อง PC ก่อน แล้วคำสั่งนี้จะ pull + pip install + restart + ตรวจ `/health`)

### 4.2 อัปเดตข้อมูลผู้สมัคร/ผลสอบ
- **ทางเว็บ**: เข้า `/staff/data-source` (ต้องล็อกอิน) แล้วกด refresh snapshot ของปีที่ต้องการ
  → ต้องมี `PARIYAT_API_USER/PASS` ใน env จึงจะดึงจาก API ได้
- **ทาง PC แล้วย้ายขึ้น**: นำไฟล์ใหม่ไปวางใน `data/` บนเครื่อง PC → รัน `scripts\pack_data_for_deploy.ps1` →
  `scp` ขึ้น VPS → `sudo FORCE=1 bash /opt/pariyat-search/deploy/seed_data.sh <zip>`
- **นำเข้าผลสอบจาก Excel**: ใช้หน้า `/manage-results/import-excel` บนเว็บได้เลย (ไฟล์ไปเก็บใน `RESULTS_DATA_DIR` เอง)

### 4.3 สำรองข้อมูล (แนะนำให้ตั้ง cron ทุกวัน)
```bash
sudo crontab -e
# เพิ่มบรรทัดนี้ (สำรองทุกวัน 02:30 เก็บ 14 วัน)
30 2 * * * tar -czf /var/lib/pariyat-search/backups/daily_$(date +\%F).tar.gz -C /var/lib/pariyat-search/data . && find /var/lib/pariyat-search/backups -name 'daily_*.tar.gz' -mtime +14 -delete
```
ดึงไฟล์สำรองกลับมาเก็บที่ PC:
```powershell
scp ubuntu@<VPS_IP>:/var/lib/pariyat-search/backups/daily_2026-09-27.tar.gz D:\pariyat-search-project\backups\
```

## 5) แก้ปัญหาที่เจอบ่อย

| อาการ | สาเหตุ / วิธีแก้ |
|---|---|
| 502 Bad Gateway | gunicorn ไม่ขึ้น → `sudo journalctl -u pariyat-search -n 100 --no-pager` |
| เปิดจากนอกบ้านไม่ได้ แต่ `curl 127.0.0.1` ได้ | ยังไม่เปิด Security List (ข้อ 2.3ก) หรือ iptables (2.3ข) หรือ ufw |
| หน้าเว็บขึ้นแต่ค้นหาไม่เจอ / count = 0 | ยังไม่ได้ seed ข้อมูล (ข้อ 2.7) → `ls -lh /var/lib/pariyat-search/data` |
| `Permission denied` ตอนบันทึกผลสอบ | `sudo chown -R ubuntu:ubuntu /var/lib/pariyat-search && sudo systemctl restart pariyat-search` |
| process ถูกฆ่า / เว็บช้าแล้วล่ม (RAM) | ทำ swap (2.9) + ลด `WEB_CONCURRENCY=1`, `GUNICORN_THREADS=2` |
| `nginx: [emerg] unknown directive` | ไฟล์ vhost เสีย → `sudo nginx -t` แล้วแก้, อย่าลืม `sudo systemctl reload nginx` |
| รัน .sh แล้วเจอ `$'\r': command not found` | ไฟล์เป็น CRLF → `sudo apt-get install -y dos2unix && sudo dos2unix /opt/pariyat-search/deploy/*.sh` |
| ลืมรหัสเจ้าหน้าที่ | `/opt/pariyat-search/.venv/bin/python /opt/pariyat-search/scripts/generate_password_hash.py "รหัสใหม่"` แล้วแก้ env + `systemctl restart pariyat-search` |
| certbot ล้มเหลว | โดเมนต้องชี้ A record มาที่ VPS และพอร์ต 80 ต้องเปิดจากข้างนอกได้ก่อน |
| อยากดู log แอปแบบละเอียด | `sudo journalctl -u pariyat-search -f` หรือ `/var/lib/pariyat-search/logs/staff_activity.log` |

## 6) ภาคผนวก: ถ้าจะกลับไปใช้ Render และทำให้ "ข้อมูลไม่หาย"

`render.yaml` ปัจจุบันไม่มี `disk` และไม่มี `RESULTS_DATA_DIR` → ข้อมูลใน `data/` หายทุกครั้งที่ deploy
ถ้าจะใช้ Render (แผน Starter ~ 7 USD/เดือน) ให้แก้เป็นแบบนี้:

```yaml
services:
  - type: web
    name: pariyat-search
    runtime: python
    region: singapore
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn --config deploy/gunicorn.conf.py app.app:app
    healthCheckPath: /health
    disk:
      name: pariyat-data
      mountPath: /var/data
      sizeGB: 5
    envVars:
      - key: PYTHON_VERSION
        value: 3.10.14
      - key: RESULTS_DATA_DIR
        value: /var/data
      - key: BACKUPS_DIR
        value: /var/data/backups
      - key: LOGS_DIR
        value: /var/data/logs
      - key: FLASK_SECRET_KEY
        generateValue: true
      - key: STAFF_USERNAME
        sync: false
      - key: STAFF_PASSWORD_HASH
        sync: false
      - key: PARIYAT_API_USER
        sync: false
      - key: PARIYAT_API_PASS
        sync: false
```
> `sync: false` = ตั้งค่าผ่าน Dashboard (ไม่เก็บในไฟล์) — แล้วนำข้อมูลไปไว้ที่ `/var/data` ผ่าน Render Shell
> (`cd /var/data && unzip`) หรือใช้ `deploy/seed_data.sh` ดัดแปลง path

**ถ้าเลิกใช้ Render แล้ว**: ลบ service ได้หลังคัดลอก env vars ครบ และตรวจว่าเว็บใหม่ใช้งานได้ปกติแล้ว

## 7) สรุปคำสั่งที่ต้องใช้บ่อย

| งาน | คำสั่ง |
|---|---|
| ดูสถานะเว็บ (VPS) | `sudo systemctl status pariyat-search` |
| ดู log สด | `sudo journalctl -u pariyat-search -f` |
| restart | `sudo systemctl restart pariyat-search` |
| reload nginx | `sudo nginx -t && sudo systemctl reload nginx` |
| อัปเดตโค้ด | `sudo bash /opt/pariyat-search/deploy/update-vps.sh` |
| seed ข้อมูล | `sudo bash /opt/pariyat-search/deploy/seed_data.sh <zip>` |
| แพ็กข้อมูล (PC) | `powershell -ExecutionPolicy Bypass -File scripts\pack_data_for_deploy.ps1` |
| ทดสอบในเครื่อง | `cd D:\pariyat-search-project; python app/app.py` แล้วเปิด http://127.0.0.1:5000 |




