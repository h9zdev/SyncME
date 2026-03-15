# SyncBridge v3.2 — Device Mesh & Control Hub

SyncBridge is a lightweight, cross-platform system designed to connect and control your devices (Android, Linux, Windows) through a central server. It features a modern tactical Web UI, real-time synchronization, and powerful remote execution capabilities.

## 🚀 Key Features

### 🌐 Central Server (Flask + Socket.IO)
- **Modern Web Dashboard**: Tactical UI for managing all connected devices.
- **REST API & WebSockets**: Low-latency communication and real-time updates.
- **MJPEG Streaming**: Live camera feed from Android devices directly in the browser.
- **File Management**: Centralized file transfers and storage.
- **Discovery**: Automatic device discovery via UDP and mDNS.
- **PWA Support**: Install the dashboard as a standalone app.

### 📱 Android Agent (Termux)
- **Full Control**: Torch, vibration, volume, brightness, TTS, and toasts.
- **Media**: On-demand photos, microphone recording, and MJPEG live stream.
- **Data Sync**: Bidirectional clipboard, notification mirroring, SMS inbox/send, contacts, and call logs.
- **Tracking**: Continuous and on-demand GPS location tracking.
- **Remote Shell**: Execute commands remotely on your Android device.
- **Smart Fallback**: Works in both "Full API" (Termux:API) and "No-API" modes.

### 🐧 Linux & 🪟 Windows Agents
- **Clipboard Sync**: Bidirectional clipboard sharing across your mesh.
- **Notifications**: Mirror server-side notifications to your desktop.
- **Remote Shell**: Securely execute shell commands from the dashboard.
- **Heartbeat**: Real-time status reporting.

---

## 🛠 Installation & Setup

### 1. Server Setup (Linux/Kali/VPS)
The server acts as the central hub.

```bash
# Clone the repository
git clone https://github.com/your-repo/syncbridge.git
cd syncbridge

# Install dependencies
pip install -r requirements.txt

# Start the server
python server.py
```
Open **http://localhost:5000** in your browser. Default token is `syncbridge-token-2024`.

### 2. Android Setup (Termux)
For full features, install the **Termux:API** app from F-Droid.

```bash
# Run the one-shot setup script in Termux
curl -O https://raw.githubusercontent.com/your-repo/syncbridge/main/termux_setup.sh
chmod +x termux_setup.sh
./termux_setup.sh

# Edit your configuration
nano ~/.syncbridge_env

# Start the agent
sb
```

### 3. Linux Agent
```bash
export SYNCBRIDGE_SERVER="http://YOUR_SERVER_IP:5000"
export SYNCBRIDGE_TOKEN="your-secret-token"
python agent_linux.py
```

### 4. Windows Agent
```powershell
# Install dependencies
pip install requests pywin32 plyer

# Set environment and run
$env:SYNCBRIDGE_SERVER="http://YOUR_SERVER_IP:5000"
$env:SYNCBRIDGE_TOKEN="your-secret-token"
python agent_windows.py
```

---

## 🛰 How it Works
1. **The Hub**: `server.py` runs a Flask web server and a Socket.IO hub. It stores device states and queues commands.
2. **The Agents**: Agents connect to the server via REST (polling for commands) and push data (heartbeats, clipboard, stats).
3. **The Tunnel**: If your server is behind a NAT, use a tunnel like Ngrok or Cloudflare Tunnel to expose the port.
4. **Live Stream**: Android agents capture frames using `termux-camera-photo` and POST them to the server, which then streams them to the dashboard using MJPEG.

---

## ❓ Troubleshooting
- **Termux:API calls fail**: Ensure you have both the `termux-api` package (`pkg install termux-api`) and the **Termux:API app** from F-Droid installed.
- **Device shows as Offline**: Check if the agent is running and the `SYNCBRIDGE_SERVER` URL is correct.
- **MJPEG Lag**: Streaming performance depends on network latency and device CPU. Lower the FPS in the dashboard if needed.

---

## 🔒 Security
SyncBridge uses a simple token-based authentication (`X-Auth-Token`). It is highly recommended to run the server behind a reverse proxy with HTTPS and use a strong, unique token.

```bash
export SYNCBRIDGE_TOKEN="a-very-strong-random-token"
export SECRET_KEY="your-flask-secret"
python server.py
```

---
*SyncBridge v3.2 — Documentation updated 2024*
