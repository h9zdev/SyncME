#!/usr/bin/env python3
"""
SyncBridge Server v3.2  —  Central Hub
Connects Linux · Windows · Android via REST + WebSocket + MJPEG stream
"""
import os, uuid, time, threading, json, socket, io, queue
from flask import Flask, request, jsonify, render_template, send_file, abort, Response
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

# ── App ───────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY']         = os.environ.get('SECRET_KEY', 'syncbridge-v3')
app.config['UPLOAD_FOLDER']      = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MEDIA_FOLDER']       = os.path.join(os.path.dirname(__file__), 'media')
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['MEDIA_FOLDER'],  exist_ok=True)

AUTH_TOKEN = os.environ.get('SYNCBRIDGE_TOKEN', 'syncbridge-token-2024')
PORT       = int(os.environ.get('SYNCBRIDGE_PORT', 5000))

# ── State ─────────────────────────────────────────────────────────────────────
devices           = {}
notifications     = []
clipboard_store   = {'content': '', 'source': '', 'timestamp': 0}
files_store       = []
shell_commands    = {}
shell_results     = {}
android_stats     = {}
sms_inbox         = {}
sms_pending       = {}
camera_cmds       = {}
mic_cmds          = {}
photos_store      = []
recordings_store  = []
gps_latest        = {}
gps_history       = {}
gps_trigger       = {}
contacts_store    = {}
calllog_store     = {}
screenshots_store = []
screenshot_cmds   = {}
control_cmds      = {}
control_results   = {}
stream_frames     = {}
stream_cmds       = {}
stream_clients    = {}
stream_conds      = {}

# ── Auth ──────────────────────────────────────────────────────────────────────
def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        token = (request.headers.get('X-Auth-Token')
                 or request.args.get('token')
                 or (request.json or {}).get('token'))
        if token != AUTH_TOKEN:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80)); ip = s.getsockname()[0]; s.close(); return ip
    except: return '127.0.0.1'

# ── Devices ───────────────────────────────────────────────────────────────────
@app.route('/api/register', methods=['POST'])
@require_auth
def register():
    data = request.json or {}
    did  = data.get('device_id') or str(uuid.uuid4())
    devices[did] = {
        'id': did, 'name': data.get('name', 'Unknown'),
        'type': data.get('type', 'unknown'), 'os': data.get('os', ''),
        'ip': request.remote_addr, 'last_seen': time.time(), 'status': 'online',
        'capabilities': data.get('capabilities', []),
    }
    socketio.emit('device_update', list(devices.values()))
    return jsonify({'status': 'registered', 'device_id': did})

@app.route('/api/heartbeat', methods=['POST'])
@require_auth
def heartbeat():
    data = request.json or {}
    did  = data.get('device_id')
    if did in devices:
        devices[did]['last_seen'] = time.time()
        devices[did]['status']    = 'online'
        if data.get('quick_stats'):
            android_stats.setdefault(did, {}).update(data['quick_stats'])
    return jsonify({'status': 'ok'})

@app.route('/api/devices', methods=['GET'])
@require_auth
def get_devices():
    now = time.time()
    for d in devices.values():
        d['status'] = 'online' if now - d['last_seen'] <= 30 else 'offline'
    return jsonify(list(devices.values()))

# ── Files ─────────────────────────────────────────────────────────────────────
@app.route('/api/files/upload', methods=['POST'])
@require_auth
def upload_file():
    if 'file' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['file']
    fid = str(uuid.uuid4())
    filename = secure_filename(f.filename) or 'untitled'
    path = os.path.join(app.config['UPLOAD_FOLDER'], fid + '_' + filename)
    f.save(path)
    meta = {'id': fid, 'filename': filename, 'size': os.path.getsize(path),
            'source': request.form.get('source', 'unknown'),
            'timestamp': time.time(), '_path': path}
    files_store.append(meta)
    socketio.emit('file_added', {k: v for k, v in meta.items() if k != '_path'})
    return jsonify({'status': 'uploaded', 'file_id': fid})

@app.route('/api/files', methods=['GET'])
@require_auth
def list_files():
    return jsonify([{k: v for k, v in f.items() if k != '_path'} for f in files_store])

@app.route('/api/files/download/<fid>', methods=['GET'])
@require_auth
def download_file(fid):
    for f in files_store:
        if f['id'] == fid: return send_file(f['_path'], as_attachment=True, download_name=f['filename'])
    abort(404)

@app.route('/api/files/<fid>', methods=['DELETE'])
@require_auth
def delete_file(fid):
    global files_store
    for f in files_store:
        if f['id'] == fid:
            try: os.remove(f['_path'])
            except: pass
            files_store = [x for x in files_store if x['id'] != fid]
            socketio.emit('file_deleted', {'file_id': fid})
            return jsonify({'status': 'deleted'})
    abort(404)

# ── Clipboard ─────────────────────────────────────────────────────────────────
@app.route('/api/clipboard', methods=['GET'])
@require_auth
def get_clipboard(): return jsonify(clipboard_store)

@app.route('/api/clipboard', methods=['POST'])
@require_auth
def set_clipboard():
    data = request.json or {}
    clipboard_store.update({'content': data.get('content', ''),
                             'source': data.get('source', 'unknown'),
                             'timestamp': time.time()})
    socketio.emit('clipboard_update', clipboard_store)
    return jsonify({'status': 'ok'})

# ── Notifications ─────────────────────────────────────────────────────────────
@app.route('/api/notifications', methods=['GET'])
@require_auth
def get_notifications(): return jsonify(notifications[-50:])

@app.route('/api/notifications', methods=['POST'])
@require_auth
def post_notification():
    data  = request.json or {}
    notif = {'id': str(uuid.uuid4()), 'title': data.get('title',''),
             'body': data.get('body',''), 'app': data.get('app',''),
             'icon': data.get('icon','🔔'), 'source': data.get('source','unknown'),
             'timestamp': time.time()}
    notifications.append(notif)
    if len(notifications) > 200: notifications.pop(0)
    socketio.emit('notification', notif)
    return jsonify({'status': 'ok', 'id': notif['id']})

@app.route('/api/notifications/<nid>', methods=['DELETE'])
@require_auth
def delete_notification(nid):
    global notifications
    notifications = [n for n in notifications if n['id'] != nid]
    socketio.emit('notification_deleted', {'id': nid})
    return jsonify({'status': 'deleted'})

@app.route('/api/notifications', methods=['DELETE'])
@require_auth
def clear_notifications():
    global notifications
    notifications = []
    socketio.emit('notifications_cleared', {})
    return jsonify({'status': 'cleared'})

# ── Shell ─────────────────────────────────────────────────────────────────────
@app.route('/api/shell/send', methods=['POST'])
@require_auth
def shell_send():
    data = request.json or {}
    did  = data.get('device_id'); cmd = data.get('command', '').strip()
    if not did or not cmd: return jsonify({'error': 'device_id and command required'}), 400
    rid = str(uuid.uuid4())
    shell_commands.setdefault(did, []).append({'id': rid, 'command': cmd, 'ts': time.time()})
    socketio.emit('shell_command', {'device_id': did, 'id': rid, 'command': cmd})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/shell/poll', methods=['GET'])
@require_auth
def shell_poll():
    return jsonify(shell_commands.pop(request.args.get('device_id'), []))

@app.route('/api/shell/result', methods=['POST'])
@require_auth
def shell_result():
    data = request.json or {}; rid = data.get('request_id')
    res  = {'output': data.get('output',''), 'error': data.get('error',''),
            'exit_code': data.get('exit_code',0), 'device': data.get('device',''),
            'timestamp': time.time()}
    shell_results[rid] = res
    socketio.emit('shell_result', {'request_id': rid, **res})
    return jsonify({'status': 'ok'})

@app.route('/api/shell/result/<rid>', methods=['GET'])
@require_auth
def get_shell_result(rid):
    if rid in shell_results: return jsonify(shell_results[rid])
    return jsonify({'status': 'pending'}), 202

# ── Android Stats ─────────────────────────────────────────────────────────────
@app.route('/api/android/stats', methods=['POST'])
@require_auth
def post_android_stats():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    stats = {k: v for k, v in data.items() if k not in ('device_id','token')}
    stats['updated'] = time.time()
    android_stats[did] = stats
    socketio.emit('android_stats', {'device_id': did, **stats})
    return jsonify({'status': 'ok'})

@app.route('/api/android/stats', methods=['GET'])
@require_auth
def get_all_stats(): return jsonify(android_stats)

@app.route('/api/android/stats/<did>', methods=['GET'])
@require_auth
def get_stats(did): return jsonify(android_stats.get(did, {}))

# ── SMS ───────────────────────────────────────────────────────────────────────
@app.route('/api/sms/<did>/inbox', methods=['GET'])
@require_auth
def get_sms_inbox(did): return jsonify(sms_inbox.get(did, [])[:100])

@app.route('/api/sms/inbox', methods=['POST'])
@require_auth
def post_sms_inbox():
    data = request.json or {}; did = data.get('device_id'); msgs = data.get('messages', [])
    if not did: return jsonify({'error': 'device_id required'}), 400
    existing = {(m.get('thread_id'), m.get('received')): m for m in sms_inbox.get(did, [])}
    for m in msgs: existing[(m.get('thread_id'), m.get('received'))] = m
    sms_inbox[did] = sorted(existing.values(), key=lambda x: x.get('received',''), reverse=True)[:200]
    socketio.emit('sms_update', {'device_id': did, 'count': len(sms_inbox[did])})
    return jsonify({'status': 'ok', 'stored': len(sms_inbox[did])})

@app.route('/api/sms/send', methods=['POST'])
@require_auth
def queue_sms():
    data = request.json or {}; did = data.get('device_id')
    to   = data.get('to','').strip(); body = data.get('body','').strip()
    if not all([did, to, body]): return jsonify({'error': 'device_id, to, body required'}), 400
    rid = str(uuid.uuid4())
    sms_pending.setdefault(did, []).append({'id': rid, 'to': to, 'body': body, 'ts': time.time()})
    socketio.emit('sms_send_queued', {'device_id': did, 'id': rid, 'to': to})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/sms/poll', methods=['GET'])
@require_auth
def poll_sms(): return jsonify(sms_pending.pop(request.args.get('device_id'), []))

# ── Camera ────────────────────────────────────────────────────────────────────
@app.route('/api/camera/trigger', methods=['POST'])
@require_auth
def camera_trigger():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    rid = str(uuid.uuid4())
    camera_cmds.setdefault(did, []).append({'id': rid, 'camera': data.get('camera',0), 'ts': time.time()})
    socketio.emit('camera_trigger', {'device_id': did, 'id': rid})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/camera/poll', methods=['GET'])
@require_auth
def camera_poll(): return jsonify(camera_cmds.pop(request.args.get('device_id'), []))

@app.route('/api/camera/upload', methods=['POST'])
@require_auth
def camera_upload():
    if 'photo' not in request.files: return jsonify({'error': 'No photo'}), 400
    f = request.files['photo']; pid = str(uuid.uuid4())
    did = request.form.get('device_id','unknown'); rid = request.form.get('request_id','')
    name = f'photo_{pid}.jpg'
    path = os.path.join(app.config['MEDIA_FOLDER'], name)
    f.save(path)
    meta = {'id': pid, 'device_id': did, 'request_id': rid, 'filename': name,
            'path': path, 'size': os.path.getsize(path), 'timestamp': time.time()}
    photos_store.append(meta)
    socketio.emit('photo_added', {k: v for k, v in meta.items() if k != 'path'})
    return jsonify({'status': 'uploaded', 'photo_id': pid})

@app.route('/api/camera/photos', methods=['GET'])
@require_auth
def list_photos():
    return jsonify([{k: v for k, v in p.items() if k != 'path'} for p in photos_store])

@app.route('/api/camera/photos/<pid>', methods=['GET'])
@require_auth
def get_photo(pid):
    for p in photos_store:
        if p['id'] == pid: return send_file(p['path'], mimetype='image/jpeg')
    abort(404)

@app.route('/api/camera/photos/<pid>', methods=['DELETE'])
@require_auth
def delete_photo(pid):
    global photos_store
    for p in photos_store:
        if p['id'] == pid:
            try: os.remove(p['path'])
            except: pass
            photos_store = [x for x in photos_store if x['id'] != pid]
            socketio.emit('photo_deleted', {'photo_id': pid})
            return jsonify({'status': 'deleted'})
    abort(404)

# ── Mic ───────────────────────────────────────────────────────────────────────
@app.route('/api/mic/trigger', methods=['POST'])
@require_auth
def mic_trigger():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    rid = str(uuid.uuid4())
    mic_cmds.setdefault(did, []).append({'id': rid, 'duration': data.get('duration',10), 'ts': time.time()})
    socketio.emit('mic_trigger', {'device_id': did, 'id': rid, 'duration': mic_cmds[did][-1]['duration']})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/mic/poll', methods=['GET'])
@require_auth
def mic_poll(): return jsonify(mic_cmds.pop(request.args.get('device_id'), []))

@app.route('/api/mic/upload', methods=['POST'])
@require_auth
def mic_upload():
    if 'recording' not in request.files: return jsonify({'error': 'No recording'}), 400
    f = request.files['recording']; rid_ = str(uuid.uuid4())
    did = request.form.get('device_id','unknown'); rid = request.form.get('request_id','')
    name = f'rec_{rid_}.m4a'
    path = os.path.join(app.config['MEDIA_FOLDER'], name)
    f.save(path)
    meta = {'id': rid_, 'device_id': did, 'request_id': rid, 'filename': name,
            'path': path, 'size': os.path.getsize(path), 'timestamp': time.time()}
    recordings_store.append(meta)
    socketio.emit('recording_added', {k: v for k, v in meta.items() if k != 'path'})
    return jsonify({'status': 'uploaded', 'recording_id': rid_})

@app.route('/api/mic/recordings', methods=['GET'])
@require_auth
def list_recordings():
    return jsonify([{k: v for k, v in r.items() if k != 'path'} for r in recordings_store])

@app.route('/api/mic/recordings/<rid>', methods=['GET'])
@require_auth
def get_recording(rid):
    for r in recordings_store:
        if r['id'] == rid: return send_file(r['path'], mimetype='audio/mp4')
    abort(404)

# ── GPS ───────────────────────────────────────────────────────────────────────
@app.route('/api/gps/update', methods=['POST'])
@require_auth
def gps_update():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    fix = {k: v for k, v in data.items() if k not in ('device_id','token')}
    fix['received'] = time.time()
    gps_latest[did] = fix
    gps_history.setdefault(did, []).append(fix)
    if len(gps_history[did]) > 500: gps_history[did].pop(0)
    socketio.emit('gps_update', {'device_id': did, **fix})
    return jsonify({'status': 'ok'})

@app.route('/api/gps/all', methods=['GET'])
@require_auth
def get_all_gps(): return jsonify(gps_latest)

@app.route('/api/gps/<did>', methods=['GET'])
@require_auth
def get_gps(did): return jsonify(gps_latest.get(did, {}))

@app.route('/api/gps/<did>/history', methods=['GET'])
@require_auth
def get_gps_history(did):
    limit = int(request.args.get('limit', 200))
    return jsonify(gps_history.get(did, [])[-limit:])

@app.route('/api/gps/trigger', methods=['POST'])
@require_auth
def gps_trigger_route():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    rid = str(uuid.uuid4())
    gps_trigger.setdefault(did, []).append({'id': rid, 'ts': time.time()})
    socketio.emit('gps_trigger', {'device_id': did, 'id': rid})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/gps/poll', methods=['GET'])
@require_auth
def gps_poll(): return jsonify(gps_trigger.pop(request.args.get('device_id'), []))

# ── Contacts ──────────────────────────────────────────────────────────────────
@app.route('/api/contacts/sync', methods=['POST'])
@require_auth
def contacts_sync():
    data = request.json or {}; did = data.get('device_id'); contacts = data.get('contacts', [])
    if not did: return jsonify({'error': 'device_id required'}), 400
    contacts_store[did] = contacts
    socketio.emit('contacts_update', {'device_id': did, 'count': len(contacts)})
    return jsonify({'status': 'ok', 'stored': len(contacts)})

@app.route('/api/contacts/<did>', methods=['GET'])
@require_auth
def get_contacts(did):
    q = request.args.get('q','').lower(); c = contacts_store.get(did, [])
    if q: c = [x for x in c if q in (x.get('name','')+x.get('number','')).lower()]
    return jsonify(c[:300])

# ── Call Log ──────────────────────────────────────────────────────────────────
@app.route('/api/calllog/sync', methods=['POST'])
@require_auth
def calllog_sync():
    data = request.json or {}; did = data.get('device_id'); calls = data.get('calls', [])
    if not did: return jsonify({'error': 'device_id required'}), 400
    calllog_store[did] = calls[:300]
    socketio.emit('calllog_update', {'device_id': did, 'count': len(calls)})
    return jsonify({'status': 'ok', 'stored': len(calls)})

@app.route('/api/calllog/<did>', methods=['GET'])
@require_auth
def get_calllog(did):
    return jsonify(calllog_store.get(did, [])[:int(request.args.get('limit',100))])

# ── Screenshot ────────────────────────────────────────────────────────────────
@app.route('/api/screenshot/trigger', methods=['POST'])
@require_auth
def screenshot_trigger():
    data = request.json or {}; did = data.get('device_id')
    if not did: return jsonify({'error': 'device_id required'}), 400
    rid = str(uuid.uuid4())
    screenshot_cmds.setdefault(did, []).append({'id': rid, 'ts': time.time()})
    socketio.emit('screenshot_trigger', {'device_id': did, 'id': rid})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/screenshot/poll', methods=['GET'])
@require_auth
def screenshot_poll(): return jsonify(screenshot_cmds.pop(request.args.get('device_id'), []))

@app.route('/api/screenshot/upload', methods=['POST'])
@require_auth
def screenshot_upload():
    if 'screenshot' not in request.files: return jsonify({'error': 'No file'}), 400
    f = request.files['screenshot']; sid = str(uuid.uuid4())
    did = request.form.get('device_id','unknown'); rid = request.form.get('request_id','')
    name = f'ss_{sid}.png'
    path = os.path.join(app.config['MEDIA_FOLDER'], name)
    f.save(path)
    meta = {'id': sid, 'device_id': did, 'request_id': rid, 'filename': name,
            'path': path, 'size': os.path.getsize(path), 'timestamp': time.time()}
    screenshots_store.append(meta)
    socketio.emit('screenshot_added', {k: v for k, v in meta.items() if k != 'path'})
    return jsonify({'status': 'uploaded', 'screenshot_id': sid})

@app.route('/api/screenshot/list', methods=['GET'])
@require_auth
def list_screenshots():
    return jsonify([{k: v for k, v in s.items() if k != 'path'} for s in screenshots_store])

@app.route('/api/screenshot/<sid>', methods=['GET'])
@require_auth
def get_screenshot(sid):
    for s in screenshots_store:
        if s['id'] == sid: return send_file(s['path'], mimetype='image/png')
    abort(404)

@app.route('/api/screenshot/<sid>', methods=['DELETE'])
@require_auth
def delete_screenshot(sid):
    global screenshots_store
    for s in screenshots_store:
        if s['id'] == sid:
            try: os.remove(s['path'])
            except: pass
            screenshots_store = [x for x in screenshots_store if x['id'] != sid]
            socketio.emit('screenshot_deleted', {'screenshot_id': sid})
            return jsonify({'status': 'deleted'})
    abort(404)

# ── Device Control ────────────────────────────────────────────────────────────
@app.route('/api/control/send', methods=['POST'])
@require_auth
def control_send():
    data = request.json or {}; did = data.get('device_id'); cmd = data.get('command')
    if not did or not cmd: return jsonify({'error': 'device_id and command required'}), 400
    rid = str(uuid.uuid4())
    payload = {k: v for k, v in data.items() if k not in ('device_id','token')}
    payload.update({'id': rid, 'ts': time.time()})
    control_cmds.setdefault(did, []).append(payload)
    socketio.emit('control_cmd', {'device_id': did, 'id': rid, 'command': cmd})
    return jsonify({'status': 'queued', 'request_id': rid})

@app.route('/api/control/poll', methods=['GET'])
@require_auth
def control_poll(): return jsonify(control_cmds.pop(request.args.get('device_id'), []))

@app.route('/api/control/result', methods=['POST'])
@require_auth
def control_result():
    data = request.json or {}; rid = data.get('request_id')
    res = {'output': data.get('output',''), 'error': data.get('error',''),
           'success': data.get('success', True), 'device': data.get('device',''),
           'timestamp': time.time()}
    control_results[rid] = res
    socketio.emit('control_result', {'request_id': rid, **res})
    return jsonify({'status': 'ok'})

# ── MJPEG Stream ──────────────────────────────────────────────────────────────
def _stream_cond(did):
    if did not in stream_conds:
        stream_conds[did] = threading.Condition(threading.Lock())
    return stream_conds[did]

@app.route('/api/stream/<did>/push', methods=['POST'])
@require_auth
def stream_push(did):
    data = request.get_data()
    if not data or len(data) < 100: return jsonify({'error': 'empty frame'}), 400
    seq = stream_frames.get(did, {}).get('seq', 0) + 1
    stream_frames[did] = {'jpeg': data, 'ts': time.time(), 'seq': seq}
    if did in devices: devices[did]['last_seen'] = time.time()
    cond = _stream_cond(did)
    with cond: cond.notify_all()
    return jsonify({'status': 'ok', 'seq': seq, 'viewers': stream_clients.get(did, 0)}), 200

@app.route('/api/stream/<did>/view')
def stream_view(did):
    if request.args.get('token','') != AUTH_TOKEN:
        return Response('Unauthorized', status=401)
    stream_cmds.setdefault(did, {'active': False, 'fps': 4, 'camera': 0})
    fps    = max(1, min(15, int(request.args.get('fps', stream_cmds[did]['fps']))))
    camera = int(request.args.get('camera', stream_cmds[did]['camera']))
    stream_cmds[did].update({'fps': fps, 'camera': camera, 'active': True})
    stream_clients[did] = stream_clients.get(did, 0) + 1
    socketio.emit('stream_start', {'device_id': did, 'fps': fps, 'camera': camera})
    BOUNDARY = b'syncbridge_frame'
    interval = 1.0 / fps

    def generate():
        cond      = _stream_cond(did)
        last_seq  = -1
        last_sent = 0.0
        try:
            while True:
                with cond:
                    cond.wait_for(
                        lambda: stream_frames.get(did, {}).get('seq', -1) > last_seq,
                        timeout=8)
                frame = stream_frames.get(did)
                if not frame:
                    yield b'--' + BOUNDARY + b'\r\nContent-Type: text/plain\r\n\r\nwait\r\n'
                    continue
                seq = frame['seq']
                if seq == last_seq: continue
                now = time.time()
                if now - last_sent < interval * 0.9:
                    last_seq = seq; continue
                jpeg = frame['jpeg']
                last_seq = seq; last_sent = now
                yield (b'--' + BOUNDARY + b'\r\nContent-Type: image/jpeg\r\nContent-Length: '
                       + str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
        except GeneratorExit:
            pass
        finally:
            stream_clients[did] = max(0, stream_clients.get(did, 1) - 1)
            if stream_clients.get(did, 0) == 0:
                stream_cmds.get(did, {}).update({'active': False})
                socketio.emit('stream_stop', {'device_id': did})

    return Response(generate(),
                    mimetype=f'multipart/x-mixed-replace; boundary={BOUNDARY.decode()}',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/api/stream/<did>/status')
@require_auth
def stream_status(did):
    cmd = stream_cmds.get(did, {'active': False, 'fps': 4, 'camera': 0})
    return jsonify({**cmd, 'viewers': stream_clients.get(did, 0),
                    'last_push': stream_frames.get(did, {}).get('ts', 0)})

@app.route('/api/stream/list')
@require_auth
def stream_list():
    result = []
    for did in set(list(stream_frames.keys()) + list(stream_cmds.keys())):
        result.append({'device_id': did,
                       'device_name': devices.get(did, {}).get('name', did),
                       'active': stream_cmds.get(did, {}).get('active', False),
                       'viewers': stream_clients.get(did, 0),
                       'last_push': stream_frames.get(did, {}).get('ts', 0),
                       'fps': stream_cmds.get(did, {}).get('fps', 4)})
    return jsonify(result)

# ── QR / PWA ──────────────────────────────────────────────────────────────────
@app.route('/api/qr')
def qr_code():
    local_ip = get_local_ip()
    try:
        import qrcode as qrc
        data = json.dumps({'url': f'http://{local_ip}:{PORT}', 'token': AUTH_TOKEN})
        img  = qrc.make(data, box_size=8, border=2)
        buf  = io.BytesIO(); img.save(buf, format='PNG'); buf.seek(0)
        return send_file(buf, mimetype='image/png')
    except ImportError:
        url = f'http://{local_ip}:{PORT}?token={AUTH_TOKEN}'
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="300" height="60">'
               f'<rect width="300" height="60" fill="#0f1218"/>'
               f'<text x="150" y="20" font-family="monospace" font-size="10" '
               f'fill="#1e90ff" text-anchor="middle">pip install qrcode[pil]</text>'
               f'<text x="150" y="45" font-family="monospace" font-size="9" '
               f'fill="#5a7090" text-anchor="middle">{url}</text></svg>')
        return Response(svg, mimetype='image/svg+xml')

@app.route('/api/pair-info')
def pair_info():
    return jsonify({'url': f'http://{get_local_ip()}:{PORT}', 'token': AUTH_TOKEN, 'version': '3.2'})

@app.route('/manifest.json')
def pwa_manifest():
    m = {'name': 'SyncBridge', 'short_name': 'SyncBridge',
         'start_url': f'/?token={AUTH_TOKEN}', 'display': 'standalone',
         'background_color': '#0a0c10', 'theme_color': '#1e90ff', 'orientation': 'any',
         'icons': [{'src': '/api/icon/192', 'sizes': '192x192', 'type': 'image/svg+xml'},
                   {'src': '/api/icon/512', 'sizes': '512x512', 'type': 'image/svg+xml'}]}
    return Response(json.dumps(m), mimetype='application/json')

@app.route('/sw.js')
def service_worker():
    sw = ("const C='sb-v3';const A=['/','/manifest.json'];"
          "self.addEventListener('install',e=>{e.waitUntil(caches.open(C).then(c=>c.addAll(A)));self.skipWaiting();});"
          "self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C).map(k=>caches.delete(k)))));self.clients.claim();});"
          "self.addEventListener('fetch',e=>{if(e.request.method!=='GET'||e.request.url.includes('/api/'))return;"
          "e.respondWith(fetch(e.request).then(r=>{caches.open(C).then(c=>c.put(e.request,r.clone()));return r;}).catch(()=>caches.match(e.request)));});")
    return Response(sw, mimetype='application/javascript')

@app.route('/api/icon/<int:sz>')
def app_icon(sz):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{sz}" height="{sz}" viewBox="0 0 100 100">'
           f'<rect width="100" height="100" rx="20" fill="#0f1218"/>'
           f'<rect x="8" y="8" width="84" height="84" rx="14" fill="none" stroke="#1e90ff" stroke-width="3"/>'
           f'<text x="50" y="68" font-size="52" text-anchor="middle">⚡</text></svg>')
    return Response(svg, mimetype='image/svg+xml')

# ── Status ────────────────────────────────────────────────────────────────────
@app.route('/api/status', methods=['GET'])
@require_auth
def api_status():
    return jsonify({'status': 'online', 'version': '3.2',
                    'devices': len(devices), 'files': len(files_store),
                    'notifications': len(notifications),
                    'photos': len(photos_store), 'recordings': len(recordings_store),
                    'screenshots': len(screenshots_store),
                    'contacts_devices': len(contacts_store),
                    'calllog_devices': len(calllog_store)})

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    return render_template('dashboard.html',
                            token=AUTH_TOKEN,
                            server_ip=get_local_ip(),
                            port=PORT)

# ── WebSocket ─────────────────────────────────────────────────────────────────
@socketio.on('connect')
def on_connect():
    now = time.time()
    for d in devices.values():
        d['status'] = 'online' if now - d['last_seen'] <= 30 else 'offline'
    emit('state', {
        'devices':       list(devices.values()),
        'clipboard':     clipboard_store,
        'notifications': notifications[-30:],
        'files':         [{k: v for k, v in f.items() if k != '_path'} for f in files_store[-30:]],
        'photos':        [{k: v for k, v in p.items() if k != 'path'}  for p in photos_store[-20:]],
        'recordings':    [{k: v for k, v in r.items() if k != 'path'}  for r in recordings_store[-10:]],
        'screenshots':   [{k: v for k, v in s.items() if k != 'path'}  for s in screenshots_store[-20:]],
        'android_stats': android_stats,
        'gps_latest':    gps_latest,
    })

# ── Background threads ────────────────────────────────────────────────────────
def udp_discovery_thread():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('', 5001)); sock.settimeout(2)
        print("[Discovery] UDP on :5001")
        while True:
            try:
                data, addr = sock.recvfrom(1024)
                if data.strip() == b'SYNCBRIDGE_DISCOVER':
                    resp = json.dumps({'url': f'http://{get_local_ip()}:{PORT}',
                                       'token': AUTH_TOKEN, 'name': socket.gethostname()})
                    sock.sendto(resp.encode(), addr)
            except socket.timeout: continue
            except Exception as e: print(f"[Discovery] {e}")
    except Exception as e: print(f"[Discovery] Could not start: {e}")

def mdns_thread():
    try:
        from zeroconf import ServiceInfo, Zeroconf
        zc   = Zeroconf()
        info = ServiceInfo("_syncbridge._tcp.local.", "SyncBridge._syncbridge._tcp.local.",
                           addresses=[socket.inet_aton(get_local_ip())], port=PORT,
                           properties={b'token': AUTH_TOKEN.encode(), b'version': b'3.2'})
        zc.register_service(info); print("[mDNS] Registered")
    except ImportError: print("[mDNS] zeroconf not installed (pip install zeroconf)")
    except Exception as e: print(f"[mDNS] {e}")

def device_watchdog():
    while True:
        time.sleep(15)
        now = time.time(); changed = False
        for d in devices.values():
            was = d['status']
            d['status'] = 'online' if now - d['last_seen'] <= 30 else 'offline'
            if was != d['status']: changed = True
        if changed: socketio.emit('device_update', list(devices.values()))

if __name__ == '__main__':
    for fn in [device_watchdog, udp_discovery_thread, mdns_thread]:
        threading.Thread(target=fn, daemon=True).start()
    ip = get_local_ip()
    print(f"\n⚡ SyncBridge v3.2  |  http://{ip}:{PORT}  |  Token: {AUTH_TOKEN}\n")
    socketio.run(app, host='0.0.0.0', port=PORT, debug=False, allow_unsafe_werkzeug=True)
