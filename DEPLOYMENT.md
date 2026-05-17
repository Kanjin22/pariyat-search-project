# คู่มือการ Deploy

## การ Deploy ขึ้น Heroku

> หมายเหตุสำคัญ: Heroku เป็นไฟล์ระบบแบบชั่วคราว (ephemeral filesystem) โฟลเดอร์ `data/` จะหายเมื่อ dyno restart/redeploy
> ถ้าต้องการใช้ Heroku จริง แนะนำย้าย `data/` ไป storage ภายนอก (เช่น S3/DB) ก่อน

### 1. ติดตั้ง Heroku CLI
ดาวน์โหลดและติดตั้งจาก https://devcenter.heroku.com/articles/heroku-cli

### 2. Login เข้า Heroku
```bash
heroku login
```

### 3. สร้าง Git Repository
```bash
git init
git add .
git commit -m "Initial commit"
```

### 4. สร้าง App บน Heroku
```bash
heroku create your-app-name
```

### 5. ตั้งค่า Config Variables
ไปที่ Heroku Dashboard → Your App → Settings → Reveal Config Vars
เพิ่มค่าเหล่านี้:
- `FLASK_SECRET_KEY`: ใส่ค่า secret key ที่ยาวและสุ่ม
- `STAFF_USERNAME`: (ถ้าต้องการใช้ .env แบบเก่า)
- `STAFF_PASSWORD_HASH`: (hash ของรหัสผ่าน)
- `PARIYAT_API_URL`
- `PARIYAT_API_USER`
- `PARIYAT_API_PASS`
- `API_SNAPSHOT_MAX_AGE_HOURS`: (เช่น 24)

### 6. Deploy!
```bash
git push heroku main
```

---

## การ Deploy บน VPS (Ubuntu/Debian)

### 1. อัปเดตระบบและติดตั้ง dependencies
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx git -y
```

### 2. Clone project และตั้งค่า environment
```bash
cd /var/www
sudo git clone <your-repo-url> pariyat-search
cd pariyat-search
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. สร้างไฟล์ .env
```bash
nano .env
```
ใส่ค่าที่จำเป็น:
- `FLASK_SECRET_KEY`
- `STAFF_PASSWORD_HASH` (และ/หรือ STAFF_USERNAME)
- `PARIYAT_API_URL`, `PARIYAT_API_USER`, `PARIYAT_API_PASS`
- `API_SNAPSHOT_MAX_AGE_HOURS` (เช่น 24)

### 3.1 ย้ายข้อมูลโฟลเดอร์ data/
โฟลเดอร์ `data/` ใช้เก็บผลสอบ/รายการ manual/snapshot (สำคัญมาก) และไม่ได้ถูก commit ใน git
ให้คัดลอก `data/` จากเครื่องที่ทำงานไปไว้บน VPS ด้วย เช่น:
```bash
scp -r data/ user@your-server:/var/www/pariyat-search/
```

### 4. ตั้งค่า Gunicorn
```bash
sudo nano /etc/systemd/system/pariyat-search.service
```

ใส่เนื้อหา:
```ini
[Unit]
Description=Gunicorn instance to serve pariyat-search
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/pariyat-search
Environment="PATH=/var/www/pariyat-search/venv/bin"
ExecStart=/var/www/pariyat-search/venv/bin/gunicorn --workers 4 --bind 127.0.0.1:8000 app.app:app

[Install]
WantedBy=multi-user.target
```

### 5. เริ่มและเปิดใช้งาน service
```bash
sudo systemctl start pariyat-search
sudo systemctl enable pariyat-search
```

### 6. ตั้งค่า Nginx
```bash
sudo nano /etc/nginx/sites-available/pariyat-search
```

ใส่เนื้อหา:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 7. เปิดใช้งาน Nginx config
```bash
sudo ln -s /etc/nginx/sites-available/pariyat-search /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

### 8. ติดตั้ง SSL (ด้วย Let's Encrypt)
```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

---

## การ Deploy บน Render (render.com)

### 1. ตั้งค่า Web Service
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn --workers 4 --bind 0.0.0.0:$PORT app.app:app`

### 2. เปิด Persistent Disk (สำคัญมาก)
แนะนำสร้าง Disk แล้ว mount เช่น `/var/data`

จากนั้นตั้ง Environment Variable:
- `RESULTS_DATA_DIR=/var/data`

เพื่อให้โฟลเดอร์ `data/` (ผลสอบ + manual + snapshot + staff_accounts) อยู่ถาวร ไม่หายหลัง deploy/restart

### 3. ตั้งค่า Environment Variables
- `FLASK_SECRET_KEY`
- `STAFF_PASSWORD_HASH` (และ/หรือ `STAFF_USERNAME`)
- `PARIYAT_API_URL`, `PARIYAT_API_USER`, `PARIYAT_API_PASS`
- `API_SNAPSHOT_MAX_AGE_HOURS` (เช่น 24)

### 4. ย้ายข้อมูลจากเครื่องขึ้น Render
โปรเจกต์นี้ไม่ได้ commit โฟลเดอร์ `data/` ลง git (อยู่ใน .gitignore) ดังนั้นต้องคัดลอก `data/` ขึ้น Disk ด้วย
อย่างน้อยควรมีไฟล์:
- `exam_results_<ปี>.json`
- `manual_registrations_<ปี>.json`
- `exam_names_<ปี>.json` (ถ้ามี)
- `api_snapshot_<ปี>.json` (ถ้ามี)
