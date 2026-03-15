# SyncBridge v3.2 — droid folder

## Files
- server.py          → Run on your Linux/Kali machine
- agent_android.py   → Run in Termux on Android
- agent_linux.py     → Run on any Linux machine
- agent_windows.py   → Run on Windows
- templates/
  └── dashboard.html → Web UI (Flask serves this automatically)
- termux_setup.sh    → One-shot Termux setup script
- requirements.txt   → Python deps

## Quick start

### 1. Server (Linux/Kali)
```
pip install flask flask-socketio requests werkzeug qrcode[pil] zeroconf
python server.py
```
Open http://localhost:5000

### 2. Android (Termux)
```
pip install requests
python agent_android.py --server https://YOUR-TUNNEL.ms --token syncbridge-token-2024
```

### 3. Linux agent
```
export SYNCBRIDGE_SERVER=http://192.168.1.x:5000
export SYNCBRIDGE_TOKEN=syncbridge-token-2024
python agent_linux.py
```

### 4. Windows agent
```
pip install requests pywin32 plyer
python agent_windows.py
```
