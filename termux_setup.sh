#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# SyncBridge Termux Setup Script v2.0
# Run this once in Termux to set up everything.
# ─────────────────────────────────────────────────────────────────────────────

set -e
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERR]${NC}  $*"; }

echo -e "\n${CYAN}⚡ SyncBridge Termux Setup${NC}\n"

# ── 1. Update & base packages ─────────────────────────────────────────────────
info "Updating packages..."
pkg update -y -q && pkg upgrade -y -q
ok "Packages updated"

info "Installing base packages..."
pkg install -y -q python python-pip git curl wget openssh
ok "Base packages installed"

# ── 2. Python dependencies ────────────────────────────────────────────────────
info "Installing Python dependencies..."
pip install --quiet requests
pip install --quiet zeroconf         # for mDNS discovery
pip install --quiet qrcode Pillow   # optional — for QR generation
ok "Python deps installed"

# ── 3. Termux API ─────────────────────────────────────────────────────────────
info "Installing Termux:API package..."
pkg install -y -q termux-api
echo ""
warn "IMPORTANT: You must also install 'Termux:API' companion app from F-Droid!"
warn "Without it, SMS / Camera / Battery / Clipboard API calls will fail."
echo ""

# ── 4. Termux permissions ─────────────────────────────────────────────────────
info "Requesting storage permission..."
termux-setup-storage 2>/dev/null || warn "Storage permission prompt may appear — tap Allow"

# ── 5. Download agent ─────────────────────────────────────────────────────────
AGENT_DIR="$HOME/syncbridge"
mkdir -p "$AGENT_DIR"

if [ -f "$AGENT_DIR/agent_android.py" ]; then
    ok "Agent already present at $AGENT_DIR"
else
    info "Please copy agent_android.py to $AGENT_DIR/"
    info "Or run: scp user@server:~/syncbridge/agent_android.py $AGENT_DIR/"
fi

# ── 6. Termux:Boot auto-start ─────────────────────────────────────────────────
info "Setting up Termux:Boot auto-start..."
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"

cat > "$BOOT_DIR/start-syncbridge.sh" << 'BOOTSCRIPT'
#!/data/data/com.termux/files/usr/bin/bash
# SyncBridge auto-start on boot
# Wait for network
sleep 10
source ~/.syncbridge_env 2>/dev/null || true
cd ~/syncbridge
python agent_android.py --discover >> ~/.syncbridge.log 2>&1 &
echo "SyncBridge agent started (PID $!)" >> ~/.syncbridge.log
BOOTSCRIPT

chmod +x "$BOOT_DIR/start-syncbridge.sh"
ok "Boot script installed at $BOOT_DIR/start-syncbridge.sh"
warn "Install 'Termux:Boot' from F-Droid and enable it to activate auto-start"

# ── 7. Termux:Widget shortcut ─────────────────────────────────────────────────
WIDGET_DIR="$HOME/.shortcuts"
mkdir -p "$WIDGET_DIR"

cat > "$WIDGET_DIR/SyncBridge.sh" << 'WIDGET'
#!/data/data/com.termux/files/usr/bin/bash
source ~/.syncbridge_env 2>/dev/null || true
cd ~/syncbridge
python agent_android.py --discover
WIDGET

chmod +x "$WIDGET_DIR/SyncBridge.sh"
ok "Widget shortcut created (install Termux:Widget from F-Droid)"

# ── 8. Environment template ───────────────────────────────────────────────────
if [ ! -f "$HOME/.syncbridge_env" ]; then
    cat > "$HOME/.syncbridge_env" << 'ENV'
# SyncBridge environment — edit with your values
export SYNCBRIDGE_SERVER="http://192.168.1.100:5000"   # or leave blank + use --discover
export SYNCBRIDGE_TOKEN="syncbridge-token-2024"
export SYNCBRIDGE_NAME="My-Android"
# export SYNCBRIDGE_ID="android-custom-id"
ENV
    ok "Created ~/.syncbridge_env — edit it with your server details"
else
    ok "~/.syncbridge_env already exists"
fi

# ── 9. Alias ──────────────────────────────────────────────────────────────────
BASHRC="$HOME/.bashrc"
if ! grep -q 'syncbridge' "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# SyncBridge" >> "$BASHRC"
    echo "alias sb='source ~/.syncbridge_env && python ~/syncbridge/agent_android.py --discover'" >> "$BASHRC"
    echo "alias sb-log='tail -f ~/.syncbridge.log'" >> "$BASHRC"
    echo "alias sb-stop=\"pkill -f agent_android.py && echo 'Stopped'\"" >> "$BASHRC"
    ok "Aliases added to ~/.bashrc: sb / sb-log / sb-stop"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   SyncBridge Termux Setup Complete! ⚡        ║${NC}"
echo -e "${GREEN}╠═══════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║  1. Edit ~/.syncbridge_env with server IP     ║${NC}"
echo -e "${GREEN}║  2. Run: source ~/.bashrc                     ║${NC}"
echo -e "${GREEN}║  3. Run: sb                (start agent)      ║${NC}"
echo -e "${GREEN}║  4. Run: sb-log            (view logs)        ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Required companion apps (from F-Droid):${NC}"
echo "  • Termux:API   — enables clipboard/SMS/camera/battery"
echo "  • Termux:Boot  — enables auto-start on reboot"
echo "  • Termux:Widget— enables home screen shortcut"
echo ""
