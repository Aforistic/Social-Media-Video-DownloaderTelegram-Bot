#!/usr/bin/env python3
"""
Social Media Video Downloader Telegram Bot
Supports: YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, Vimeo, and more

Features:
  - User tracking with SQLite database
  - Admin gets notified on every new user & every download
  - Admin dashboard commands: /stats, /users, /user <id>, /broadcast <msg>
"""

import os
import re
import asyncio
import logging
import tempfile
import sqlite3
from pathlib import Path
from datetime import datetime
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
BOT_TOKEN = os.getenv("BOT_TOKEN",  "YOUR_BOT_TOKEN_HERE")
ADMIN_ID  = int(os.getenv("ADMIN_ID",  "0"))   # Channel ID (-1001234567890) OR personal ID for notifications
OWNER_ID  = int(os.getenv("OWNER_ID",  "0"))   # Your personal ID — grants access to admin commands
DB_PATH   = os.getenv("DB_PATH", "users.db")

MAX_FILE_SIZE_MB    = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

SUPPORTED_SITES = [
    "youtube.com", "youtu.be", "instagram.com", "tiktok.com",
    "twitter.com", "x.com", "facebook.com", "fb.watch",
    "reddit.com", "vimeo.com", "dailymotion.com", "twitch.tv",
    "pinterest.com", "linkedin.com", "snapchat.com", "soundcloud.com",
]

URL_REGEX = re.compile(r"https?://[^\s]+")


# ── Database ──────────────────────────────────────────────────────────────────

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         INTEGER PRIMARY KEY,
                username        TEXT,
                first_name      TEXT,
                last_name       TEXT,
                joined_at       TEXT NOT NULL,
                last_seen       TEXT NOT NULL,
                total_downloads INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                url           TEXT NOT NULL,
                platform      TEXT,
                quality       TEXT,
                status        TEXT,
                downloaded_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
        """)
    logger.info("Database ready at %s", DB_PATH)


def register_user(tg_user) -> bool:
    """Upsert user. Returns True if brand-new."""
    now = datetime.utcnow().isoformat()
    with db_connect() as conn:
        exists = conn.execute(
            "SELECT user_id FROM users WHERE user_id = ?", (tg_user.id,)
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE users SET last_seen=?, username=?, first_name=?, last_name=? WHERE user_id=?",
                (now, tg_user.username, tg_user.first_name, tg_user.last_name, tg_user.id),
            )
            return False
        conn.execute(
            "INSERT INTO users (user_id, username, first_name, last_name, joined_at, last_seen) VALUES (?,?,?,?,?,?)",
            (tg_user.id, tg_user.username, tg_user.first_name, tg_user.last_name, now, now),
        )
        return True


def log_download(user_id: int, url: str, platform: str, quality: str, status: str) -> None:
    now = datetime.utcnow().isoformat()
    with db_connect() as conn:
        conn.execute(
            "INSERT INTO downloads (user_id, url, platform, quality, status, downloaded_at) VALUES (?,?,?,?,?,?)",
            (user_id, url, platform, quality, status, now),
        )
        if status == "success":
            conn.execute(
                "UPDATE users SET total_downloads = total_downloads + 1 WHERE user_id = ?",
                (user_id,),
            )


def get_stats() -> dict:
    today = datetime.utcnow().date().isoformat()
    with db_connect() as conn:
        total_users     = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_downloads = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='success'").fetchone()[0]
        new_today       = conn.execute("SELECT COUNT(*) FROM users WHERE joined_at LIKE ?", (f"{today}%",)).fetchone()[0]
        dl_today        = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='success' AND downloaded_at LIKE ?", (f"{today}%",)).fetchone()[0]
        top_platforms   = conn.execute(
            "SELECT platform, COUNT(*) cnt FROM downloads WHERE status='success' GROUP BY platform ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
    return dict(total_users=total_users, total_downloads=total_downloads,
                new_today=new_today, dl_today=dl_today, top_platforms=top_platforms)


def get_all_users(page=0, per_page=15) -> list:
    with db_connect() as conn:
        return conn.execute(
            "SELECT user_id, username, first_name, last_name, joined_at, total_downloads FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
            (per_page, page * per_page),
        ).fetchall()


def get_all_user_ids() -> list[int]:
    with db_connect() as conn:
        return [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_url(text: str) -> str | None:
    m = URL_REGEX.search(text)
    return m.group(0) if m else None


def get_platform(url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "")
    for site in SUPPORTED_SITES:
        if site in host:
            return site.split(".")[0].capitalize()
    return "Unknown"


def human_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def user_display(tg_user) -> str:
    name = (tg_user.first_name or "") + (" " + tg_user.last_name if tg_user.last_name else "")
    suffix = f" (@{tg_user.username})" if tg_user.username else ""
    return f"{name.strip()}{suffix}"


async def notify_admin(app, text: str) -> None:
    """Post to the notification channel (or personal chat if no channel set)."""
    target = ADMIN_ID or OWNER_ID
    if not target:
        return
    try:
        await app.bot.send_message(chat_id=target, text=text,
                                   parse_mode="Markdown", disable_notification=False)
    except Exception as e:
        logger.warning("Channel notify failed: %s", e)


# ── yt-dlp wrappers ───────────────────────────────────────────────────────────

async def fetch_info(url: str) -> dict:
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))


async def download_video(url: str, tmpdir: str, quality: str = "best") -> tuple[str, dict]:
    fmt = {
        "audio": "bestaudio/best",
        "720p":  "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]/best",
        "480p":  "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]/best",
        "best":  "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    }.get(quality, "best")

    opts: dict = {"format": fmt, "outtmpl": f"{tmpdir}/%(title).50s.%(ext)s",
                  "quiet": True, "no_warnings": True, "noplaylist": True}
    if quality == "audio":
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    else:
        opts["merge_output_format"] = "mp4"

    loop = asyncio.get_event_loop()
    info: dict = {}

    def _dl():
        nonlocal info
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

    await loop.run_in_executor(None, _dl)
    files = list(Path(tmpdir).glob("*"))
    if not files:
        raise FileNotFoundError("No output file after download.")
    return str(max(files, key=lambda p: p.stat().st_size)), info


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    is_new = register_user(user)

    if is_new:
        await notify_admin(
            context.application,
            f"🆕 *New user joined!*\n\n"
            f"👤 {user_display(user)}\n"
            f"🆔 ID: `{user.id}`\n"
            f"📅 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
        )

    await update.message.reply_text(
        "👋 *Welcome to Social Media Video Downloader Bot!*\n\n"
        "📥 Just send me any video link and I'll download it for you.\n\n"
        "✅ *Supported:* YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, Vimeo, Twitch, SoundCloud & 1000+ more.\n\n"
        "📌 Commands: /start /help\n\n"
        "👉 Paste a link to get started!",
        parse_mode="Markdown",
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    await update.message.reply_text(
        "ℹ️ *How to use:*\n\n"
        "1️⃣ Copy a video link from any platform\n"
        "2️⃣ Paste it here\n"
        "3️⃣ Pick a quality\n"
        "4️⃣ Download your file 🎉\n\n"
        "⚠️ Max file size: 50 MB (Telegram limit)\n"
        "💡 Use 480p or Audio for large videos.",
        parse_mode="Markdown",
    )


# ── Admin Commands ────────────────────────────────────────────────────────────

def is_admin(update: Update) -> bool:
    """Only the OWNER (you) can run admin commands."""
    return bool(OWNER_ID) and update.effective_user.id == OWNER_ID


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    s = get_stats()
    plat = "\n".join(f"  • {r['platform']}: {r['cnt']}" for r in s["top_platforms"]) or "  No data yet"
    await update.message.reply_text(
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total users: *{s['total_users']}*\n"
        f"🆕 New today: *{s['new_today']}*\n\n"
        f"📥 Total downloads: *{s['total_downloads']}*\n"
        f"📥 Downloads today: *{s['dl_today']}*\n\n"
        f"🏆 Top platforms:\n{plat}",
        parse_mode="Markdown",
    )


async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return

    page = int(context.args[0]) - 1 if context.args and context.args[0].isdigit() else 0
    rows = get_all_users(page=page)
    if not rows:
        await update.message.reply_text("No users found.")
        return

    lines = []
    for r in rows:
        handle = f"@{r['username']}" if r["username"] else f"ID:{r['user_id']}"
        lines.append(f"• {r['first_name'] or '?'} ({handle}) — {r['joined_at'][:10]} — {r['total_downloads']} DLs")

    total = get_stats()["total_users"]
    text  = f"👥 *Users — Page {page+1}* (total: {total})\n\n" + "\n".join(lines)
    if len(rows) == 15:
        text += f"\n\n➡️ `/users {page+2}`"
    await update.message.reply_text(text[:4096], parse_mode="Markdown")


async def admin_user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: `/user <user_id>`", parse_mode="Markdown")
        return

    uid = int(context.args[0])
    with db_connect() as conn:
        u  = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        dls = conn.execute(
            "SELECT platform, quality, status, downloaded_at FROM downloads WHERE user_id=? ORDER BY downloaded_at DESC LIMIT 5",
            (uid,)
        ).fetchall()

    if not u:
        await update.message.reply_text("❌ User not found.")
        return

    dl_lines = "\n".join(
        f"  • {d['platform']} ({d['quality']}) [{d['status']}] {d['downloaded_at'][:16]}" for d in dls
    ) or "  No downloads yet"

    await update.message.reply_text(
        f"👤 *User Detail*\n\n"
        f"🆔 ID: `{u['user_id']}`\n"
        f"📛 Name: {u['first_name']} {u['last_name'] or ''}\n"
        f"🔗 Username: {'@'+u['username'] if u['username'] else '—'}\n"
        f"📅 Joined: {u['joined_at'][:16]} UTC\n"
        f"👁 Last seen: {u['last_seen'][:16]} UTC\n"
        f"📥 Total downloads: {u['total_downloads']}\n\n"
        f"🕓 Recent downloads:\n{dl_lines}",
        parse_mode="Markdown",
    )


async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast Your message`", parse_mode="Markdown")
        return

    msg     = " ".join(context.args)
    ids     = get_all_user_ids()
    status  = await update.message.reply_text(f"📡 Broadcasting to {len(ids)} users…")
    sent = failed = 0

    for uid in ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {msg}")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await status.edit_text(f"✅ Done!\n📨 Sent: {sent}\n❌ Failed (blocked): {failed}")


# ── URL Handler ───────────────────────────────────────────────────────────────

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    register_user(user)

    url = extract_url(update.message.text or "")
    if not url:
        await update.message.reply_text("❌ No valid URL detected. Send a proper video link.")
        return

    platform = get_platform(url)
    msg = await update.message.reply_text(f"🔍 Fetching info from *{platform}*…", parse_mode="Markdown")

    try:
        info = await asyncio.wait_for(fetch_info(url), timeout=30)
    except asyncio.TimeoutError:
        await msg.edit_text("⏱️ Timed out fetching video info. Try again.")
        return
    except Exception as e:
        await msg.edit_text(f"❌ Could not fetch video info.\n\n`{str(e)[:300]}`", parse_mode="Markdown")
        return

    title = info.get("title", "Unknown")[:60]
    mins, secs = divmod(int(info.get("duration", 0)), 60)
    uploader   = info.get("uploader", "Unknown")

    context.user_data[f"url_{msg.message_id}"]      = url
    context.user_data[f"platform_{msg.message_id}"] = platform

    kb = [
        [InlineKeyboardButton("🏆 Best",  callback_data=f"dl|best|{msg.message_id}"),
         InlineKeyboardButton("📺 720p", callback_data=f"dl|720p|{msg.message_id}")],
        [InlineKeyboardButton("📱 480p",  callback_data=f"dl|480p|{msg.message_id}"),
         InlineKeyboardButton("🎵 Audio MP3", callback_data=f"dl|audio|{msg.message_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{msg.message_id}")],
    ]
    await msg.edit_text(
        f"🎬 *{title}*\n👤 {uploader}\n⏱️ {mins}m {secs}s\n\nChoose quality:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")

    if parts[0] == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return
    if parts[0] != "dl" or len(parts) < 3:
        return

    quality, msg_id = parts[1], parts[2]
    url      = context.user_data.get(f"url_{msg_id}")
    platform = context.user_data.get(f"platform_{msg_id}", "Unknown")
    user     = update.effective_user
    qlabel   = {"best": "Best Quality", "720p": "720p", "480p": "480p", "audio": "Audio MP3"}.get(quality, quality)

    if not url:
        await query.edit_message_text("❌ Session expired. Send the link again.")
        return

    await query.edit_message_text(f"⬇️ Downloading ({qlabel})…\nThis may take a moment ⏳")

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            filepath, info = await asyncio.wait_for(download_video(url, tmpdir, quality), timeout=300)
        except asyncio.TimeoutError:
            log_download(user.id, url, platform, quality, "failed")
            await query.edit_message_text("⏱️ Download timed out. Try a lower quality.")
            return
        except Exception as e:
            log_download(user.id, url, platform, quality, "failed")
            await query.edit_message_text(f"❌ Download failed.\n\n`{str(e)[:300]}`", parse_mode="Markdown")
            return

        size = os.path.getsize(filepath)
        if size > MAX_FILE_SIZE_BYTES:
            log_download(user.id, url, platform, quality, "too_large")
            await query.edit_message_text(
                f"⚠️ File too large ({human_size(size)}) for Telegram (max {MAX_FILE_SIZE_MB} MB).\nTry 480p or Audio."
            )
            return

        title        = info.get("title", "video")[:60]
        caption_text = f"🎬 *{title}*\n📦 {human_size(size)}\n✅ @InternetDownloaderBot"

        await query.edit_message_text("📤 Uploading…")
        try:
            if quality == "audio" or filepath.endswith(".mp3"):
                with open(filepath, "rb") as f:
                    await query.message.reply_audio(audio=f, caption=caption_text,
                                                    parse_mode="Markdown", title=title)
            else:
                with open(filepath, "rb") as f:
                    await query.message.reply_video(video=f, caption=caption_text,
                                                    parse_mode="Markdown", supports_streaming=True)

            log_download(user.id, url, platform, quality, "success")
            await query.edit_message_text("✅ Done! Enjoy your video 🎉")

            await notify_admin(
                context.application,
                f"📥 *Download done*\n"
                f"👤 {user_display(user)} (`{user.id}`)\n"
                f"🌐 {platform} | 🎚 {qlabel} | 📦 {human_size(size)}"
            )
        except Exception as e:
            log_download(user.id, url, platform, quality, "failed")
            await query.edit_message_text(f"❌ Upload failed: `{str(e)[:200]}`", parse_mode="Markdown")


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    await update.message.reply_text("🤔 Send me a video URL. Use /help for instructions.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Set BOT_TOKEN in .env"); return
    if not ADMIN_ID and not OWNER_ID:
        print("⚠️  Neither ADMIN_ID nor OWNER_ID set – notifications and admin commands disabled")
    elif not ADMIN_ID:
        print("ℹ️  No ADMIN_ID (channel) set – notifications will go to your personal chat (OWNER_ID)")
    elif not OWNER_ID:
        print("ℹ️  No OWNER_ID set – admin commands (/stats /users /broadcast) are disabled")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("help",      help_cmd))
    app.add_handler(CommandHandler("stats",     admin_stats))
    app.add_handler(CommandHandler("users",     admin_users))
    app.add_handler(CommandHandler("user",      admin_user_detail))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown))

    logger.info("Bot running…")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
