#!/usr/bin/env python3
# control_panel.py
from flask import Flask, request, redirect, url_for, render_template_string
import subprocess, threading, os, time, sys, re, json
import discord
from discord import SyncWebhook
import asyncio

APP_HOST = "0.0.0.0"
APP_PORT = int(os.environ.get("CONTROL_PORT", 8080))
MAIN_PY = "main.py"
DATA_FILE = "1345476135487672350.json"
LOG_FILE = "bot_stdout.log"

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
    <h2>Guild selection / Log target</h2>
    <form method="get" action="/">
      <label>Choose guild:</label><br>
      <select name="guild_id" onchange="this.form.submit()">
        {% for gid, label in guild_options %}
          <option value="{{ gid }}" {% if gid == selected_guild %}selected{% endif %}>{{ label }}</option>
        {% endfor %}
      </select>
      <noscript><button type="submit">Select</button></noscript>
    </form>

    <p>Current log target for <strong>{{ selected_guild }}</strong> : <code>{{ current_log_display }}</code></p>
    <form method="post" action="/set_log_channel">
      <input type="hidden" name="guild_id" value="{{ selected_guild }}">
      <label>Choose channel:</label><br>
      <select name="log_channel" style="width:420px">
        <option value="">Select a channel</option>
        {% for channel_id, channel_name in channel_options %}
          <option value="{{ channel_id }}" {% if channel_id == current_log_value %}selected{% endif %}>{{ channel_name }}</option>
        {% endfor %}
      </select>
      <button type="submit">Save Log Target & Restart Bot</button>
    </form>

    <hr>
    <h2>Logs (last ~200 chars)</h2>
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
        logfile = open(LOG_FILE, "ab")
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
        return "(none)"
    text = open(MAIN_PY, "r", encoding="utf-8").read()
    m = re.search(r'TOKEN\s*=\s*["\'](.+?)["\']', text)
    if not m:
        return "(none)"
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

def load_datafile():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_datafile(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, DATA_FILE)

def read_logs():
    if not os.path.exists(LOG_FILE):
        return ""
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            read_size = min(pos, 8192)
            f.seek(max(0, pos - read_size))
            data = f.read().decode(errors="replace")
            return data[-200:]
    except Exception:
        return ""

async def get_channels(guild_id, token):
    client = discord.Client(intents=discord.Intents.default())
    try:
        await client.login(token)
        guild = await client.fetch_guild(guild_id)
        channels = await guild.fetch_channels()
        text_channels = [(str(channel.id), channel.name) for channel in channels if isinstance(channel, discord.TextChannel)]
        return sorted(text_channels, key=lambda x: x[1])
    except Exception:
        return []
    finally:
        await client.close()

def run_async_get_channels(guild_id, token):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(get_channels(guild_id, token))
    finally:
        loop.close()

@app.route("/", methods=["GET"])
def index():
    data = load_datafile()
    guild_ids = list(data.keys())
    guild_options = [(gid, gid) for gid in guild_ids]

    selected_guild = request.args.get("guild_id")
    if not selected_guild and guild_ids:
        selected_guild = guild_ids[0]
    if not selected_guild:
        selected_guild = ""

    current_log_display = "(none)"
    current_log_value = ""
    channel_options = []
    if selected_guild and selected_guild in data:
        cfg = data[selected_guild]
        if "log_webhook" in cfg:
            current_log_display = cfg["log_webhook"]
            current_log_value = cfg["log_webhook"]
        elif "log_channel" in cfg:
            current_log_display = str(cfg["log_channel"])
            current_log_value = str(cfg["log_channel"])

        token = read_masked_token()
        if token != "(none)" and not token.endswith("*"):
            channel_options = run_async_get_channels(selected_guild, token)
        else:
            channel_options = []

    return render_template_string(
        HTML,
        status=get_status(),
        token_mask=read_masked_token(),
        guild_options=guild_options,
        selected_guild=selected_guild,
        current_log_display=current_log_display,
        current_log_value=current_log_value,
        channel_options=channel_options,
        logs=read_logs(),
        port=APP_PORT
    )

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
    guild_id = request.form.get("guild_id", "").strip()
    target = request.form.get("log_channel", "").strip()

    if not guild_id or not target:
        return redirect(url_for("index"))

    data = load_datafile()
    cfg = data.setdefault(guild_id, {})

    if target.startswith("http"):
        cfg["log_webhook"] = target
        cfg.pop("log_channel", None)
    else:
        cfg["log_channel"] = int(target)
        cfg.pop("log_webhook", None)

    data[guild_id] = cfg
    try:
        save_datafile(data)
    except Exception:
        pass

    start_process()
    return redirect(url_for("index"))

if __name__ == "__main__":
    try:
        start_process()
    except Exception:
        pass
    print(f"Starting control panel on {APP_HOST}:{APP_PORT} ...")
    app.run(host=APP_HOST, port=APP_PORT, threaded=True)
