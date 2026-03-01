#!/usr/bin/env python3
"""
Social Media Video Downloader Telegram Bot
Supports: YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, Vimeo, and more
"""

import os
import re
import asyncio
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Telegram's max file size for bots = 50 MB
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Supported domains (yt-dlp supports 1000+ but we surface the popular ones)
SUPPORTED_SITES = [
    "youtube.com", "youtu.be",
    "instagram.com",
    "tiktok.com",
    "twitter.com", "x.com",
    "facebook.com", "fb.watch",
    "reddit.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
    "pinterest.com",
    "linkedin.com",
    "snapchat.com",
    "soundcloud.com",
]

URL_REGEX = re.compile(
    r"https?://[^\s]+"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_url(text: str) -> str | None:
    match = URL_REGEX.search(text)
    return match.group(0) if match else None


def get_platform(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    for site in SUPPORTED_SITES:
        if site in host:
            return site.split(".")[0].capitalize()
    return "Unknown"


def human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


async def fetch_info(url: str) -> dict:
    """Return video metadata without downloading."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
    return info


async def download_video(url: str, tmpdir: str, quality: str = "best") -> tuple[str, dict]:
    """Download video, returns (filepath, info_dict)."""

    if quality == "audio":
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": f"{tmpdir}/%(title).50s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    elif quality == "720p":
        ydl_opts = {
            "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best",
            "outtmpl": f"{tmpdir}/%(title).50s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
        }
    elif quality == "480p":
        ydl_opts = {
            "format": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]/best",
            "outtmpl": f"{tmpdir}/%(title).50s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
        }
    else:  # best
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": f"{tmpdir}/%(title).50s.%(ext)s",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
        }

    loop = asyncio.get_event_loop()
    info = {}

    def _download():
        nonlocal info
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        return info

    info = await loop.run_in_executor(None, _download)

    # Find the downloaded file
    files = list(Path(tmpdir).glob("*"))
    if not files:
        raise FileNotFoundError("Download failed – no file found.")
    filepath = str(max(files, key=lambda p: p.stat().st_size))
    return filepath, info


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Welcome to Social Media Video Downloader Bot!*\n\n"
        "📥 Just send me any video link and I'll download it for you.\n\n"
        "✅ *Supported Platforms:*\n"
        "• YouTube & YouTube Shorts\n"
        "• Instagram (Reels, Posts, Stories)\n"
        "• TikTok\n"
        "• Twitter / X\n"
        "• Facebook\n"
        "• Reddit\n"
        "• Vimeo\n"
        "• Dailymotion\n"
        "• Twitch\n"
        "• SoundCloud (audio)\n"
        "• _...and 1000+ more sites!_\n\n"
        "📌 *Commands:*\n"
        "/start – Show this message\n"
        "/help – Usage instructions\n\n"
        "👉 Go ahead – paste a link!"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "ℹ️ *How to use:*\n\n"
        "1️⃣ Copy a video URL from any supported platform.\n"
        "2️⃣ Paste it here in the chat.\n"
        "3️⃣ Choose your preferred quality.\n"
        "4️⃣ Wait for your video/audio file! 🎉\n\n"
        "⚠️ *Limitations:*\n"
        "• Max file size: 50 MB (Telegram limit)\n"
        "• Private/login-required content cannot be downloaded\n"
        "• Playlists are not supported – send individual video links\n\n"
        "💡 *Tip:* For large YouTube videos choose 480p to stay under the size limit."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    url = extract_url(update.message.text or "")
    if not url:
        await update.message.reply_text("❌ No valid URL detected. Please send a proper video link.")
        return

    platform = get_platform(url)
    status_msg = await update.message.reply_text(
        f"🔍 Fetching info from *{platform}*…", parse_mode="Markdown"
    )

    try:
        info = await asyncio.wait_for(fetch_info(url), timeout=30)
    except asyncio.TimeoutError:
        await status_msg.edit_text("⏱️ Timed out while fetching video info. Try again.")
        return
    except Exception as e:
        await status_msg.edit_text(
            f"❌ Could not fetch video info.\n\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )
        return

    title = info.get("title", "Unknown title")[:60]
    duration = info.get("duration", 0)
    uploader = info.get("uploader", "Unknown")
    mins, secs = divmod(int(duration), 60)

    caption = (
        f"🎬 *{title}*\n"
        f"👤 {uploader}\n"
        f"⏱️ {mins}m {secs}s\n\n"
        f"Choose quality:"
    )

    # Store URL in user_data keyed by message id
    context.user_data[f"url_{status_msg.message_id}"] = url

    keyboard = [
        [
            InlineKeyboardButton("🏆 Best Quality", callback_data=f"dl|best|{status_msg.message_id}"),
            InlineKeyboardButton("📺 720p", callback_data=f"dl|720p|{status_msg.message_id}"),
        ],
        [
            InlineKeyboardButton("📱 480p", callback_data=f"dl|480p|{status_msg.message_id}"),
            InlineKeyboardButton("🎵 Audio Only (MP3)", callback_data=f"dl|audio|{status_msg.message_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{status_msg.message_id}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await status_msg.edit_text(caption, parse_mode="Markdown", reply_markup=reply_markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")

    if data[0] == "cancel":
        await query.edit_message_text("❌ Download cancelled.")
        return

    if data[0] != "dl" or len(data) < 3:
        return

    quality = data[1]
    msg_id = data[2]
    url = context.user_data.get(f"url_{msg_id}")

    if not url:
        await query.edit_message_text("❌ Session expired. Please send the link again.")
        return

    quality_labels = {
        "best": "Best Quality",
        "720p": "720p",
        "480p": "480p",
        "audio": "Audio MP3",
    }
    await query.edit_message_text(
        f"⬇️ Downloading ({quality_labels.get(quality, quality)})…\nThis may take a moment ⏳"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            filepath, info = await asyncio.wait_for(
                download_video(url, tmpdir, quality), timeout=300
            )
        except asyncio.TimeoutError:
            await query.edit_message_text("⏱️ Download timed out. Try a shorter video or lower quality.")
            return
        except Exception as e:
            await query.edit_message_text(
                f"❌ Download failed.\n\n`{str(e)[:300]}`", parse_mode="Markdown"
            )
            return

        file_size = os.path.getsize(filepath)
        if file_size > MAX_FILE_SIZE_BYTES:
            await query.edit_message_text(
                f"⚠️ File is too large ({human_size(file_size)}) for Telegram (max {MAX_FILE_SIZE_MB} MB).\n"
                "Try 480p or Audio Only."
            )
            return

        title = info.get("title", "video")[:60]
        caption_text = (
            f"🎬 *{title}*\n"
            f"📦 Size: {human_size(file_size)}\n"
            f"✅ Downloaded via @YourBotUsername"
        )

        await query.edit_message_text("📤 Uploading to Telegram…")

        try:
            if quality == "audio" or filepath.endswith(".mp3"):
                with open(filepath, "rb") as f:
                    await query.message.reply_audio(
                        audio=f,
                        caption=caption_text,
                        parse_mode="Markdown",
                        title=title,
                    )
            else:
                with open(filepath, "rb") as f:
                    await query.message.reply_video(
                        video=f,
                        caption=caption_text,
                        parse_mode="Markdown",
                        supports_streaming=True,
                    )
            await query.edit_message_text("✅ Done! Enjoy your video 🎉")
        except Exception as e:
            await query.edit_message_text(
                f"❌ Upload failed: `{str(e)[:200]}`", parse_mode="Markdown"
            )


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤔 I only understand video links. Send me a URL from YouTube, TikTok, Instagram, etc."
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ERROR: Please set your BOT_TOKEN in the .env file or environment variable.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    logger.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
