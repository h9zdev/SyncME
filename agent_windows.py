#!/usr/bin/env python3
"""
SyncBridge Windows Agent
Syncs clipboard, mirrors notifications, handles remote shell, file transfers.

Usage (PowerShell):
  $env:SYNCBRIDGE_SERVER="http://192.168.1.100:5000"
  $env:SYNCBRIDGE_TOKEN="syncbridge-token-2024"
  $env:SYNCBRIDGE_NAME="my-windows-pc"
  python agent_windows.py

Dependencies:
  pip install requests pywin32 win10toast plyer
"""

import os, sys, uuid, time, signal, platform, subprocess, threading, ctypes
import requests

# ─── Config ──────────────────────────────────────────────────────────────────
SERVER    = os.environ.get('SYNCBRIDGE_SERVER', 'http://localhost:5000')
TOKEN     = os.environ.get('SYNCBRIDGE_TOKEN',  'syncbridge-token-2024')
NAME      = os.environ.get('SYNCBRIDGE_NAME',   platform.node())
DEVICE_ID = os.environ.get('SYNCBRIDGE_ID',     str(uuid.uuid4()))
POLL      = int(os.environ.get('SYNCBRIDGE_POLL', 5))

HEADERS = {'X-Auth-Token': TOKEN, 'Content-Type': 'application/json'}
running = True

# ─── Windows Clipboard (win32) ────────────────────────────────────────────────
try:
    import win32clipboard
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

def _get_clip_win32():
    if not HAS_WIN32:
        return ''
    try:
        win32clipboard.OpenClipboard()
        try:
            data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            return data.strip()
        finally:
            win32clipboard.CloseClipboard()
    except: return ''

def _set_clip_win32(text):
    if not HAS_WIN32:
        return
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()
    except: pass

def _get_clip_powershell():
    """Fallback clipboard get via PowerShell."""
    try:
        out = subprocess.check_output(
            ['powershell', '-Command', 'Get-Clipboard'],
            capture_output=True, text=True, timeout=3)
        return out.stdout.strip()
    except: return ''

def _set_clip_powershell(text):
    """Fallback clipboard set via PowerShell."""
    try:
        subprocess.run(
            ['powershell', '-Command', f'Set-Clipboard -Value "{text}"'],
            capture_output=True, timeout=3)
    except: pass

def get_clipboard():
    return _get_clip_win32() if HAS_WIN32 else _get_clip_powershell()

def set_clipboard(text):
    if HAS_WIN32:
        _set_clip_win32(text)
    else:
        _set_clip_powershell(text)

# ─── Notifications ────────────────────────────────────────────────────────────
try:
    from plyer import notification as plyer_notif
    HAS_PLYER = True
except ImportError:
    HAS_PLYER = False

def _notify_win(title, body, app=''):
    prefix = f"[{app}] " if app else ""
    full_title = f"{prefix}{title}"
    if HAS_PLYER:
        try:
            plyer_notif.notify(
                title=full_title,
                message=body,
                app_name='SyncBridge',
                timeout=5,
            )
            return
        except: pass
    # Ultimate fallback — message box (blocking, use sparingly)
    try:
        ctypes.windll.user32.MessageBoxW(0, body, full_title, 0x40)
    except: pass

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
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ─── Registration & Heartbeat ─────────────────────────────────────────────────
def register():
    log(f"Registering as '{NAME}' ({DEVICE_ID})")
    res = api('post', '/api/register', json={
        'device_id': DEVICE_ID,
        'name':      NAME,
        'type':      'windows',
        'os':        platform.platform(),
    })
    log(f"Server: {res}")

def heartbeat_loop():
    while running:
        api('post', '/api/heartbeat', json={'device_id': DEVICE_ID})
        time.sleep(20)

# ─── Clipboard Loop ───────────────────────────────────────────────────────────
last_clip = ''

def clipboard_loop():
    global last_clip
    while running:
        try:
            cur = get_clipboard()
            if cur and cur != last_clip:
                last_clip = cur
                api('post', '/api/clipboard', json={'content': cur, 'source': NAME})
                log(f"[CLIP] → server: {cur[:60]}")

            remote = api('get', '/api/clipboard')
            if (remote and remote.get('content')
                    and remote.get('source') != NAME
                    and remote['content'] != last_clip):
                set_clipboard(remote['content'])
                last_clip = remote['content']
                log(f"[CLIP] ← {remote.get('source')}: {remote['content'][:60]}")
        except Exception as e:
            log(f"[CLIP] error: {e}")
        time.sleep(POLL)

# ─── Notification Loop ────────────────────────────────────────────────────────
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
                            _notify_win(n.get('title',''), n.get('body',''), n.get('app',''))
                            log(f"[NOTIF] {n.get('app')} — {n.get('title')}")
        except Exception as e:
            log(f"[NOTIF] error: {e}")
        time.sleep(POLL)

# ─── Shell Loop ───────────────────────────────────────────────────────────────
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
                            text=True, timeout=30, encoding='utf-8',
                            errors='replace')
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
