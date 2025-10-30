import os
import subprocess
import sys
from flask import Flask, render_template, Response, request

app = Flask(__name__)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRAPER_SCRIPT = os.path.join(PROJECT_ROOT, 'scraper', 'scraper.py')
SCRAPER_DIR = os.path.join(PROJECT_ROOT, 'scraper')

def stream_command_output(command, working_dir):
    """ฟังก์ชันกลางสำหรับรันคำสั่งและ Stream ผลลัพธ์กลับไป"""
    try:
        process = subprocess.Popen(
            command, cwd=working_dir, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            encoding=sys.stdout.encoding or 'utf-8', errors='ignore', bufsize=1
        )
        for line in process.stdout:
            yield f"data: {line.strip()}\n\n"
        process.wait()
        return process.returncode
    except Exception as e:
        yield f"data: ❌ เกิดข้อผิดพลาดร้ายแรง: {str(e)}\n\n"
        return -1

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/run-scraper-stream')
def run_scraper_stream():
    def generate():
        command = [sys.executable, SCRAPER_SCRIPT]
        returncode = yield from stream_command_output(command, SCRAPER_DIR)
        if returncode == 0:
            yield "data: \n\n"
            yield "data: ✅ ดึงข้อมูลสำเร็จ! คุณสามารถไปขั้นตอนที่ 2 ได้\n\n"
        else:
            yield "data: \n\n"
            yield f"data: ❌ เกิดข้อผิดพลาด! โปรแกรมจบการทำงานด้วยรหัส: {returncode}\n\n"
    return Response(generate(), mimetype='text/event-stream')

# --- API ใหม่: สำหรับการ Push to GitHub แบบ Stream ---
@app.route('/git-push-stream', methods=['POST'])
def git_push_stream():
    commit_message = request.json.get('message', 'Automated update via Dashboard')
    
    def generate():
        # 1. Git Add
        yield "data: --- [1/3] กำลังรัน git add . ---\n\n"
        returncode = yield from stream_command_output(['git', 'add', '.'], PROJECT_ROOT)
        if returncode != 0:
            yield f"data: ❌ git add ล้มเหลว (รหัส: {returncode})\n\n"
            return

        # 2. Git Commit
        yield "data: \n--- [2/3] กำลังรัน git commit ---\n\n"
        returncode = yield from stream_command_output(['git', 'commit', '-m', f'"{commit_message}"'], PROJECT_ROOT)
        # Git commit อาจจะจบด้วยรหัส 1 ถ้าไม่มีอะไรให้ commit ซึ่งไม่ถือว่าเป็น Error
        if returncode > 1:
            yield f"data: ❌ git commit ล้มเหลว (รหัส: {returncode})\n\n"
            return
        
        # 3. Git Push
        yield "data: \n--- [3/3] กำลังรัน git push ---\n\n"
        returncode = yield from stream_command_output(['git', 'push', 'origin', 'main'], PROJECT_ROOT)
        if returncode != 0:
            yield f"data: ❌ git push ล้มเหลว (รหัส: {returncode})\n\n"
            yield "data:    อาจจะต้องยืนยันตัวตนในเบราว์เซอร์ หรือใช้ GitHub Desktop แทน\n\n"
            return
            
        yield "data: \n✅ All Git commands executed successfully! Render should start deploying shortly.\n\n"
        
    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    print("Dashboard is running on http://127.0.0.1:5001")
    app.run(port=5001, debug=True)