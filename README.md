# WireGuard VPN Manager Bot 🤖🔐

Control your VPS-hosted **WireGuard VPN** fully from **Telegram buttons**.  
No shell after install; no manual config edits. **Perfect for iPhone 13**.

## ✨ Features

- Owner-only access (one-tap “I’m the owner”)
- Button controls (no commands except `/start`)
- Install/Check WireGuard on VPS
- Add peers, list peers
- Send **.conf** files
- Show **QR codes** (scan on iPhone WireGuard app)
- Revoke peers
- Restart WG
- Show stats (handshakes & traffic)

## 🧰 Requirements

- VPS (Ubuntu/Debian recommended)
- Root access
- Open UDP port **51820**
- Telegram bot token (via @BotFather)

## 🚀 Quick Start

```bash
# 1) Upload repo files or git clone your fork
sudo bash install.sh

# 2) Put your bot token
sudo nano /opt/wgbot/.env  # set BOT_TOKEN=...

# 3) Start service
sudo systemctl start wgbot
sudo systemctl status wgbot --no-pager
