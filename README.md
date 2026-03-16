#  SyncMe
![SyncMe](https://github.com/H9yzz/H9yzz/blob/main/SyncMe.png?raw=true)


SyncMe is a lightweight tool that connects your Android, Linux, and Windows devices so they can work together seamlessly. Control, sync, and manage everything from one simple web interface.
<p align="center"><a href="https://github.com/h9zdev/SyncME"><img src="https://img.shields.io/github/stars/h9zdev/SyncME?style=for-the-badge&logo=github" alt="Stars"/></a> <a href="https://github.com/h9zdev/SyncME/network/members"><img src="https://img.shields.io/github/forks/h9zdev/SyncME?style=for-the-badge&logo=github" alt="Forks"/></a> <a href="https://github.com/h9zdev/SyncME/issues"><img src="https://img.shields.io/github/issues/h9zdev/SyncME?style=for-the-badge&logo=github" alt="Issues"/></a> <img src="https://img.shields.io/badge/Support-Android-3DDC84?style=for-the-badge&logo=android&logoColor=white" alt="Android"/> <img src="https://img.shields.io/badge/Support-Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux"/> <img src="https://img.shields.io/badge/Support-Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows"/> <img src="https://img.shields.io/badge/Kotlin-7F52FF?style=for-the-badge&logo=kotlin&logoColor=white" alt="Kotlin"/> <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/> <a href="https://github.com/sponsors/h9zdev"><img src="https://img.shields.io/badge/Make%20a%20Difference-Sponser%20My%20Work-6A1B9A?style=for-the-badge&logo=github&logoColor=white" alt="Support My Work"/></a></p>



---

## ✨ Key Features

### 🖥️ Central Server (Flask + Socket.IO)
- **Modern Web Dashboard**: Tactical UI for managing all connected devices. 📊
- **REST API & WebSockets**: Low-latency communication and real-time updates. ⚡
- **MJPEG Streaming**: Live camera feed from Android devices directly in the browser. 🎥
- **File Management**: Centralized file transfers and storage. 📂
- **Discovery**: Automatic device discovery via UDP and mDNS. 🔍
- **PWA Support**: Install the dashboard as a standalone app. 📱

### 📱 Android Agent (Native & Termux)
- **Full Control**: Torch, vibration, volume, brightness, TTS, and toasts. 🔦📳🔊
- **Media**: On-demand photos, microphone recording, and MJPEG live stream. 📷🎙️
- **Data Sync**: Bidirectional clipboard, notification mirroring, SMS inbox/send, contacts, and call logs. 📋✉️☎️
- **Tracking**: Continuous and on-demand GPS location tracking. 📍
- **Remote Shell**: Execute commands remotely on your Android device. 🐚
- **Smart Fallback**: Works in both "Full API" (Termux:API) and "No-API" modes. 🧠

### 🐧 Linux & 🪟 Windows Agents
- **Clipboard Sync**: Bidirectional clipboard sharing across your mesh. 📋
- **Notifications**: Mirror server-side notifications to your desktop. 🔔
- **Remote Shell**: Securely execute shell commands from the dashboard. 🐚
- **Heartbeat**: Real-time status reporting. ❤️

---

## 🛠️ Installation & Setup

### 1. 🌐 Server Setup (Linux/Kali/VPS)
The server acts as the central hub.

```bash
# Clone the repository
git clone https://github.com/h9zdev/SyncME.git
cd SyncME

# Install dependencies
pip install -r requirements.txt

# Start the server
python server.py
```
Open **http://localhost:5000** in your browser. Default token is `syncbridge-token-2024`.
> [!TIP]
> If you are running locally, use your local IP address. You can also use port forwarding to expose your server to the internet. 🌍

### 2. 📱 Android Native App Setup
Download the SyncME Android app to easily connect your device.

- **For Android 8 to Android 11**: [Download APK](https://github.com/h9zdev/SyncME/releases/download/AndroidSyncME/SyncMe.apk) 📥
- **For Android 12, 13, and 14+**: [Download APK](https://github.com/h9zdev/SyncME/releases/download/AndroidSyncME/SyncMe.apk) 📥
- **Build your own**: [Syncme-droid Repository](https://github.com/h9zdev/Syncme-droid) 🏗️

Once installed:
1. Open the app.
2. Enter your **Server URL**, **Token**, and **Device Name**.
3. Click **Connect**. 🚀

### 3. 🐚 Android Termux Setup
For advanced users, run the agent within Termux.

**Download Termux and Addons:**
- **Termux**: [F-Droid](https://f-droid.org/en/packages/com.termux/) | [Play Store](https://play.google.com/store/apps/details?id=com.termux)
- **Termux:API**: [F-Droid](https://f-droid.org/en/packages/com.termux.api/)
- **Termux:Widget**: [F-Droid](https://f-droid.org/en/packages/com.termux.widget/)
- **Termux:Boot**: [F-Droid](https://f-droid.org/en/packages/com.termux.boot/)

**Setup Steps:**
```bash
# Open Termux and download the setup script and agent
curl -O https://raw.githubusercontent.com/h9zdev/SyncME/main/termux_setup.sh
curl -O https://raw.githubusercontent.com/h9zdev/SyncME/main/agent_android.py

# Run the setup script
chmod +x termux_setup.sh
./termux_setup.sh

# Start the agent
python agent_android.py --server [YOUR_SERVER_URL] --token [YOUR_TOKEN]
```

### 4. 🐧 Linux Agent
```bash
export SYNCBRIDGE_SERVER="http://YOUR_SERVER_IP:5000"
export SYNCBRIDGE_TOKEN="your-secret-token"
python agent_linux.py
```

### 5. 🪟 Windows Agent
```powershell
# Install dependencies
pip install requests pywin32 plyer

# Set environment and run
$env:SYNCBRIDGE_SERVER="http://YOUR_SERVER_IP:5000"
$env:SYNCBRIDGE_TOKEN="your-secret-token"
python agent_windows.py
```

---

## 🛰️ How it Works
1. **The Hub**: `server.py` runs a Flask web server and a Socket.IO hub. It stores device states and queues commands.
2. **The Agents**: Agents connect to the server via REST (polling for commands) and push data (heartbeats, clipboard, stats).
3. **The Tunnel**: If your server is behind a NAT, use a tunnel like Ngrok or Cloudflare Tunnel to expose the port.
4. **Live Stream**: Android agents capture frames using `termux-camera-photo` and POST them to the server, which then streams them to the dashboard using MJPEG.

---

## ❓ Troubleshooting
- **Termux:API calls fail**: Ensure you have both the `termux-api` package (`pkg install termux-api`) and the **Termux:API app** installed from F-Droid.
- **Device shows as Offline**: Check if the agent is running and the `SYNCBRIDGE_SERVER` URL is correct.
- **MJPEG Lag**: Streaming performance depends on network latency and device CPU. Lower the FPS in the dashboard if needed.

---

## 🔒 Security
SyncBridge uses a simple token-based authentication (`X-Auth-Token`). It is highly recommended to run the server behind a reverse proxy with HTTPS and use a strong, unique token. 🛡️

```bash
export SYNCBRIDGE_TOKEN="a-very-strong-random-token"
export SECRET_KEY="your-flask-secret"
python server.py
```
## 📸 Screenshots

### Login Screen
![Login Screen](https://github.com/H9yzz/H9yzz/blob/main/Screenshot_20260316_101636.png?raw=true)

### Dashboard
![Dashboard](https://github.com/H9yzz/H9yzz/blob/main/Screenshot_20260316_101719.png?raw=true)

### Device Control
![Device Control](https://github.com/H9yzz/H9yzz/blob/main/Screenshot_20260316_101836.png?raw=true)

### Settings / Interface
![Settings](https://github.com/H9yzz/H9yzz/blob/main/Screenshot_20260316_102031.png?raw=true)

## 📜 License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0) License. See the [LICENSE](LICENSE) file for more details.

**Unauthorized use is strictly prohibited.**

📧 Contact: singularat@protn.me

## ☕ Support

Donate via Monero: `45PU6txuLxtFFcVP95qT2xXdg7eZzPsqFfbtZp5HTjLbPquDAugBKNSh1bJ76qmAWNGMBCKk4R1UCYqXxYwYfP2wTggZNhq`

## 👥 Contributors and Developers

[<img src="https://avatars.githubusercontent.com/u/67865621?s=64&v=4" width="64" height="64" alt="haybnzz">](https://github.com/h9zdev) [<img src="https://avatars.githubusercontent.com/u/180658853?s=64&v=4" width="64" height="64" alt="Steiynbrodt">](https://github.com/Steiynbrodt) [<img src="https://avatars.githubusercontent.com/u/220222050?v=4&size=64" width="64" height="64" alt="H9yzz">](https://github.com/H9yzz) [<img src="https://avatars.githubusercontent.com/u/108749445?s=64&size=64" width="64" height="64" alt="VaradScript">](https://github.com/VaradScript)
