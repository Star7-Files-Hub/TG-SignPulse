# TG-Assistant

A multi-functional Telegram automation helper — check-in, forwarding, red packet grabbing, Emby keep-alive, all in one place.

## ✨ Features

| Module | Description |
|--------|-------------|
| 📊 **Dashboard** | Accounts / Tasks / Monitors / Failure overview |
| 👤 **Accounts** | Multi-account login, session management, status check |
| ⚡ **Tasks** | Scheduled check-in, AI vision click, custom action sequences, batch multi-chat |
| 📻 **Monitors** | Real-time message monitoring, independent of tasks |
| → 📨 **Forward** | Regex match → native forward, multi-account/channel, dedup, smart numeric compare |
| → 🧧 **Red Packet** | Auto-click button / keyword grab, number extraction, delayed reply, templates |
| 🎬 **Emby Keep** | Simulate watch sessions to keep Emby accounts active, Bemby-style UA presets |
| 📋 **Logs** | Task logs / Audit logs / Monitor logs / Emby logs, real-time polling |
| ⚙ **Settings** | Telegram API, Bot notifications, AI model, timezone, config import/export |

## 🛠 Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.10+ / FastAPI / Uvicorn / SQLAlchemy / SQLite/PostgreSQL |
| Frontend | Vue 3 / Vite / TypeScript / Tailwind CSS |
| Scheduler | APScheduler |
| Telegram | Pyrogram (MTProto) |
| AI | OpenAI-compatible API |
| Container | Docker optional |

## 🚀 Quick Deploy

```bash
mkdir -p /root/tg-assistant
tar -xzf tg-assistant.tar.gz -C /root/tg-assistant
cd /root/tg-assistant
chmod +x deploy.sh
sudo ./deploy.sh
```

Admin password:
```bash
cat /data/tg-assistant/.admin_bootstrap_password
```

## 📄 License

MIT License
