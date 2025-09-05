#!/usr/bin/env bash
set -euo pipefail

# Run as root
if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "Run as root: sudo bash install.sh"; exit 1
fi

export DEBIAN_FRONTEND=noninteractive

apt update
apt install -y python3-venv python3-pip git curl wireguard qrencode iptables-persistent

# App dir
APP_DIR="/opt/wgbot"
mkdir -p "$APP_DIR"
cp -r bot.py wg_core.py requirements.txt "$APP_DIR"/
[ -f .env ] && cp .env "$APP_DIR"/ || cp .env.example "$APP_DIR"/.env

cd "$APP_DIR"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Systemd service
cat >/etc/systemd/system/wgbot.service <<'EOF'
[Unit]
Description=WireGuard Telegram Bot
After=network.target wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Type=simple
WorkingDirectory=/opt/wgbot
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/wgbot/.venv/bin/python /opt/wgbot/bot.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable wgbot

# Open UDP 51820 if UFW is present & enabled
if command -v ufw >/dev/null 2>&1; then
  ufw allow 51820/udp || true
fi

echo "----------------------------------------"
echo "✅ Installation done."
echo "Next:"
echo "1) Edit /opt/wgbot/.env and put your BOT_TOKEN"
echo "2) Start the bot: systemctl start wgbot"
echo "3) Open Telegram, /start the bot, tap 'I'm the owner'"
echo "----------------------------------------"
