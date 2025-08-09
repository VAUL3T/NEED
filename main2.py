#!/usr/bin/env python3
# control_panel.py
from flask import Flask, request, redirect, url_for, render_template_string
import subprocess, threading, os, signal, time, sys, re

APP_HOST = "0.0.0.0"
APP_PORT = int(os.environ.get("CONTROL_PORT", 80))  # default 80
MAIN_PY = "main.py"

app = Flask(__name__)

_child = None
_enabled = True
_child_lock = threading.Lock()

HTML = """<!doctype html>
<html>
  <head><title>Bot Control</title></head>
  <body>
    <h1>Bot Control Panel</h1>
    <p>Status: <strong>{{ status }}</strong></p>

    <form method="post" action="/action">
      <button name="cmd" value="shutdown">Shutdown</button>
      <button name="cmd" value="restart">Restart</button>
      <button name="cmd" value="enable">Enable</button>
    </form>

    <hr>
    <h2>Set Token</h2>
    <p>Current token: <code>{{ token_mask }}</code></p>
    <form method="post" action="/set_token">
      <label>Token (paste full token to replace):</label><br>
      <input name="token" style="width:420px" autocomplete="off" required>
      <button type="submit">Save Token & Restart Bot</button>
    </form>

    <hr>
    <h2>Set Log Channel ID</h2>
    <p>Current log channel: <code>{{ log_channel }}</code></p>
    <form method="post" action="/set_log_channel">
      <label>Channel ID:</label><br>
      <input name="log_channel" style="width:200px" autocomplete="off" required>
      <button type="submit">Save Channel & Restart Bot</button>
    </form>

    <hr>
    <h2>Logs (last 200 chars)</h2>
    <pre style="white-space:pre-wrap; max-height:300px; overflow:auto;">{{ logs }}</pre>

    <hr>
    <p>Accessible at http://&lt;droplet-ip&gt; (port {{ port }})</p>
  </body>
</html>
"""

def start_process():
    global _child, _enabled
    with _child_lock:
        if not _enabled:
            return False, "Disabled"
        if _child and _child.poll() is None:
            return True, "Already running"
        if not os.path.exists(MAIN_PY):
            return False, f"{MAIN_PY} not found"
        logfile = open("bot_stdout.log", "ab")
        proc = subprocess.Popen([sys.executable, MAIN_PY], stdout=logfile, stderr=subprocess.STDOUT)
        _child = proc
        return True, f"Started PID {_child.pid}"

def stop_process(timeout=5):
    global _child
    with _child_lock:
        if not _child or _child.poll() is not None:
            _child = None
            return False, "Not running"
        try:
            _child.terminate()
        except Exception:
            pass
        try:
            _child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                _child.kill()
            except Exception:
                pass
        finally:
            rc = _child.poll()
            _child = None
            return True, f"Stopped (rc={rc})"

def restart_process():
    stop_process()
    time.sleep(0.3)
    return start_process()

def get_status():
    global _child, _enabled
    with _child_lock:
        if not _enabled:
            return "Disabled"
        if _child and _child.poll() is None:
            return f"Running (PID {_child.pid})"
        return "Stopped"

def read_masked_token():
    if not os.path.exists(MAIN_PY):
        return ""
    text = open(MAIN_PY, "r", encoding="utf-8").read()
    m = re.search(r'TOKEN\s*=\s*["\'](.+?)["\']', text)
    if not m:
        return ""
    token = m.group(1)
    if len(token) <= 5:
        return token
    return token[:5] + "*" * (len(token)-5)

def replace_token_in_main(new_token):
    if not os.path.exists(MAIN_PY):
        with open(MAIN_PY, "w", encoding="utf-8") as f:
            f.write(f'TOKEN = "{new_token}"\n')
        return True
    text = open(MAIN_PY, "r", encoding="utf-8").read()
    if re.search(r'TOKEN\s*=\s*["\'](.+?)["\']', text):
        new_text = re.sub(r'TOKEN\s*=\s*["\'](.+?)["\']', f'TOKEN = "{new_token}"', text, count=1)
    else:
        new_text = f'TOKEN = "{new_token}"\n' + text
    with open(MAIN_PY, "w", encoding="utf-8") as f:
        f.write(new_text)
    return True

def read_log_channel():
    if not os.path.exists(MAIN_PY):
        return "(none)"
    text = open(MAIN_PY, "r", encoding="utf-8").read()
    m = re.search(r'LOG_CHANNEL_ID\s*=\s*(\d+)', text)
    if not m:
        return "(none)"
    return m.group(1)

def replace_log_channel(new_id):
    if not os.path.exists(MAIN_PY):
        with open(MAIN_PY, "w", encoding="utf-8") as f:
            f.write(f'LOG_CHANNEL_ID = {new_id}\n')
        return True
    text = open(MAIN_PY, "r", encoding="utf-8").read()
    if re.search(r'LOG_CHANNEL_ID\s*=\s*(\d+)', text):
        new_text = re.sub(r'LOG_CHANNEL_ID\s*=\s*(\d+)', f'LOG_CHANNEL_ID = {new_id}', text, count=1)
    else:
        new_text = f'LOG_CHANNEL_ID = {new_id}\n' + text
    with open(MAIN_PY, "w", encoding="utf-8") as f:
        f.write(new_text)
    return True

def read_logs():
    if not os.path.exists("bot_stdout.log"):
        return ""
    try:
        with open("bot_stdout.log", "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            read_size = min(pos, 8192)
            f.seek(pos - read_size)
            data = f.read().decode(errors="replace")
            return data[-200:]
    except Exception:
        return ""

@app.route("/", methods=["GET"])
def index():
    token_mask = read_masked_token()
    log_channel = read_log_channel()
    return render_template_string(HTML, status=get_status(),
                                  token_mask=token_mask or "(none)",
                                  log_channel=log_channel,
                                  logs=read_logs(), port=APP_PORT)

@app.route("/action", methods=["POST"])
def action():
    global _enabled
    cmd = request.form.get("cmd", "")
    if cmd == "shutdown":
        stop_process()
        _enabled = False
        return redirect(url_for("index"))
    if cmd == "restart":
        if not _enabled:
            _enabled = True
        start_process()
        return redirect(url_for("index"))
    if cmd == "enable":
        _enabled = True
        start_process()
        return redirect(url_for("index"))
    return redirect(url_for("index"))

@app.route("/set_token", methods=["POST"])
def set_token():
    token = request.form.get("token", "").strip()
    if not token:
        return redirect(url_for("index"))
    replace_token_in_main(token)
    start_process()
    return redirect(url_for("index"))

@app.route("/set_log_channel", methods=["POST"])
def set_log_channel():
    channel_id = request.form.get("log_channel", "").strip()
    if not channel_id.isdigit():
        return redirect(url_for("index"))
    replace_log_channel(channel_id)
    start_process()
    return redirect(url_for("index"))

if __name__ == "__main__":
    try:
        start_process()
    except Exception:
        pass
    print(f"Starting control panel on {APP_HOST}:{APP_PORT} ...")
    app.run(host=APP_HOST, port=APP_PORT, threaded=True)
