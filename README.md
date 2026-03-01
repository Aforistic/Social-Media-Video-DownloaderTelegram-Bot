# 🎬 Social Media Video Downloader Telegram Bot

A powerful Telegram bot that lets users download videos from YouTube, TikTok, Instagram, Twitter/X, Facebook, Reddit, and 1000+ other platforms — just by sending a link.

---

## ✨ Features

- 📥 Download from **1000+ websites** (powered by yt-dlp)
- 🎚️ Quality options: Best, 720p, 480p, Audio MP3
- ⚡ Inline keyboard UI for quality selection
- 🔒 Safe temp file handling (auto-cleaned after upload)
- 🐳 Docker-ready for easy deployment

---

## 📋 Supported Platforms (Popular)

| Platform | Videos | Audio |
|---|---|---|
| YouTube / Shorts | ✅ | ✅ |
| Instagram Reels/Posts | ✅ | ✅ |
| TikTok | ✅ | ✅ |
| Twitter / X | ✅ | ✅ |
| Facebook | ✅ | ✅ |
| Reddit | ✅ | ✅ |
| Vimeo | ✅ | ✅ |
| Dailymotion | ✅ | ✅ |
| Twitch | ✅ | ✅ |
| SoundCloud | ❌ | ✅ |

> ℹ️ yt-dlp supports 1000+ sites. If it works in yt-dlp, it works here.

---

## 🚀 Quick Setup

### 1. Get a Bot Token

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **API token** you receive

### 2. Clone & Configure

```bash
git clone https://github.com/yourusername/telegram-video-bot.git
cd telegram-video-bot

cp .env.example .env
# Edit .env and paste your bot token:
# BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUVwxyz
```

### 3. Install Dependencies

Make sure you have **Python 3.10+** and **ffmpeg** installed.

```bash
# Install ffmpeg
# Ubuntu/Debian:
sudo apt install ffmpeg

# macOS:
brew install ffmpeg

# Windows: download from https://ffmpeg.org/download.html

# Install Python dependencies
pip install -r requirements.txt
```

### 4. Run the Bot

```bash
python bot.py
```

---

## 🐳 Docker Deployment (Recommended)

```bash
cp .env.example .env
# Fill in BOT_TOKEN in .env

docker-compose up -d
```

The bot will restart automatically on crashes or server reboots.

---

## 🌐 Deploy to a Server (VPS)

For 24/7 uptime, deploy to any VPS (DigitalOcean, Linode, Hetzner, etc.):

```bash
# On your server:
git clone https://github.com/yourusername/telegram-video-bot.git
cd telegram-video-bot
cp .env.example .env
nano .env  # add your token

# Run with Docker
docker-compose up -d

# Or run as a systemd service (see below)
```

### Systemd Service (without Docker)

```ini
# /etc/systemd/system/tgbot.service
[Unit]
Description=Telegram Video Downloader Bot
After=network.target

[Service]
WorkingDirectory=/opt/telegram-video-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
EnvironmentFile=/opt/telegram-video-bot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tgbot
sudo systemctl start tgbot
sudo systemctl status tgbot
```

---

## ⚠️ Important Notes

- **Telegram file size limit is 50 MB.** Videos larger than this cannot be sent through the bot. Use 480p or audio-only for large videos.
- **Private/login-required content** (e.g., private Instagram posts) cannot be downloaded.
- **Playlists are not supported** — send individual video URLs only.
- This bot is for **personal use**. Respect copyright and platform terms of service.

---

## 📁 Project Structure

```
telegram-video-bot/
├── bot.py              # Main bot code
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── Dockerfile          # Docker image definition
├── docker-compose.yml  # Docker Compose config
└── README.md           # This file
```

---

## 🛠️ Customization

**Change bot username in caption:** Edit line in `bot.py`:
```python
f"✅ Downloaded via @YourBotUsername"
```

**Add user whitelist** (restrict to specific users):
```python
ALLOWED_USERS = [123456789, 987654321]  # Telegram user IDs

async def handle_url(update, context):
    if update.effective_user.id not in ALLOWED_USERS:
        await update.message.reply_text("❌ You are not authorized.")
        return
    ...
```

---

## 📄 License

MIT License – free to use and modify.
