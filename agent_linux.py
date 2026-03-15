#!/usr/bin/env python3
"""
SyncBridge Linux Agent
Syncs clipboard, mirrors notifications, handles remote shell, file transfers.

Usage:
  export SYNCBRIDGE_SERVER=http://192.168.1.100:5000
  export SYNCBRIDGE_TOKEN=syncbridge-token-2024
  export SYNCBRIDGE_NAME=my-linux-box
  python3 agent_linux.py
"""

import os, sys, uuid, time, signal, platform, subprocess, threading, requests

# ─── Config ──────────────────────────────────────────────────────────────────
SERVER    = os.environ.get('SYNCBRIDGE_SERVER', 'http://localhost:5000')
TOKEN     = os.environ.get('SYNCBRIDGE_TOKEN',  'syncbridge-token-2024')
NAME      = os.environ.get('SYNCBRIDGE_NAME',   platform.node())
DEVICE_ID = os.environ.get('SYNCBRIDGE_ID',     str(uuid.uuid4()))
POLL      = int(os.environ.get('SYNCBRIDGE_POLL', 5))   # seconds

HEADERS = {'X-Auth-Token': TOKEN, 'Content-Type': 'application/json'}
running = True

# ─── Helpers ──────────────────────────────────────────────────────────────────
def api(method, path, **kw):
    try:
        r = getattr(requests, method)(f"{SERVER}{path}",
                                      headers=HEADERS, timeout=10, **kw)
        return r.json() if r.content else {}
    except Exception as e:
        log(f"API error: {e}")
        return {}

def log(msg):
    ts = time.strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

# ─── Registration & Heartbeat ─────────────────────────────────────────────────
def register():
    log(f"Registering as '{NAME}' ({DEVICE_ID})")
    res = api('post', '/api/register', json={
        'device_id': DEVICE_ID,
        'name':      NAME,
        'type':      'linux',
        'os':        platform.platform(),
    })
    log(f"Server: {res}")

def heartbeat_loop():
    while running:
        api('post', '/api/heartbeat', json={'device_id': DEVICE_ID})
        time.sleep(20)

# ─── Clipboard ────────────────────────────────────────────────────────────────
last_clip = ''

def _get_clip():
    for cmd in [['wl-paste', '--no-newline'],
                ['xclip', '-selection', 'clipboard', '-o'],
                ['xsel', '--clipboard', '--output']]:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=2)
            return out.decode('utf-8', errors='replace').strip()
        except: pass
    return ''

def _set_clip(text):
    for cmd, inp in [(['wl-copy'], text.encode()),
                     (['xclip', '-selection', 'clipboard'], text.encode()),
                     (['xsel', '--clipboard', '--input'], text.encode())]:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            p.communicate(input=inp)
            return True
        except: pass
    return False

def clipboard_loop():
    global last_clip
    while running:
        try:
            # Push local clipboard to server
            cur = _get_clip()
            if cur and cur != last_clip:
                last_clip = cur
                api('post', '/api/clipboard', json={'content': cur, 'source': NAME})
                log(f"[CLIP] → server: {cur[:60]}")

            # Pull remote clipboard
            remote = api('get', '/api/clipboard')
            if (remote and remote.get('content')
                    and remote.get('source') != NAME
                    and remote['content'] != last_clip):
                _set_clip(remote['content'])
                last_clip = remote['content']
                log(f"[CLIP] ← {remote.get('source')}: {remote['content'][:60]}")
        except Exception as e:
            log(f"[CLIP] error: {e}")
        time.sleep(POLL)

# ─── Notifications ────────────────────────────────────────────────────────────
def _notify(title, body, app=''):
    prefix = f"[{app}] " if app else ""
    try:
        subprocess.Popen(['notify-send', '--urgency=normal',
                          f"{prefix}{title}", body],
                         stderr=subprocess.DEVNULL)
    except:
        log(f"[NOTIF] {prefix}{title}: {body}")

def notification_loop():
    seen = set()
    while running:
        try:
            notifs = api('get', '/api/notifications')
            if isinstance(notifs, list):
                for n in notifs:
                    if n['id'] not in seen:
                        seen.add(n['id'])
                        if n.get('source') != NAME:
                            _notify(n.get('title',''), n.get('body',''), n.get('app',''))
                            log(f"[NOTIF] {n.get('app')} — {n.get('title')}")
        except Exception as e:
            log(f"[NOTIF] error: {e}")
        time.sleep(POLL)

# ─── Shell ────────────────────────────────────────────────────────────────────
def shell_loop():
    while running:
        try:
            cmds = api('get', f'/api/shell/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for cmd_obj in cmds:
                    rid     = cmd_obj['id']
                    command = cmd_obj['command']
                    log(f"[SHELL] exec: {command}")
                    try:
                        res = subprocess.run(
                            command, shell=True, capture_output=True,
                            text=True, timeout=30)
                        api('post', '/api/shell/result', json={
                            'request_id': rid,
                            'output':     res.stdout,
                            'error':      res.stderr,
                            'exit_code':  res.returncode,
                            'device':     NAME,
                        })
                    except subprocess.TimeoutExpired:
                        api('post', '/api/shell/result', json={
                            'request_id': rid,
                            'output': '', 'error': 'Timeout (30s)', 'exit_code': -1,
                            'device': NAME,
                        })
        except Exception as e:
            log(f"[SHELL] error: {e}")
        time.sleep(POLL)

# ─── File Helper ──────────────────────────────────────────────────────────────
def upload_file(path):
    """Upload a file to SyncBridge (call manually from Python or CLI)."""
    with open(path, 'rb') as fh:
        r = requests.post(f"{SERVER}/api/files/upload",
                          headers={'X-Auth-Token': TOKEN},
                          files={'file': fh},
                          data={'source': NAME})
        return r.json()

# ─── Main ─────────────────────────────────────────────────────────────────────
def stop(*_):
    global running
    running = False
    log("Stopping agent...")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT,  stop)
    signal.signal(signal.SIGTERM, stop)
    register()
    threads = [
        threading.Thread(target=heartbeat_loop,    daemon=True, name='heartbeat'),
        threading.Thread(target=clipboard_loop,    daemon=True, name='clipboard'),
        threading.Thread(target=notification_loop, daemon=True, name='notifications'),
        threading.Thread(target=shell_loop,        daemon=True, name='shell'),
    ]
    for t in threads:
        t.start()
        log(f"Started {t.name} thread")
    log(f"Agent running. Server={SERVER}  Poll={POLL}s")
    while running:
        time.sleep(1)

if __name__ == '__main__':
    main()
