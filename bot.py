import os
import asyncio
import logging
import re
from typing import List, Optional

import aiohttp
from aiohttp_socks import ProxyConnector
from fake_useragent import UserAgent
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ------------------ Configuration ------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

MAX_CONCURRENT = 30          # Higher concurrency for 5000+ views (Railway allows ~30-50)
VIEW_TIMEOUT = 10            # Reduced timeout for speed
PROXY_FILE = "proxies.txt"   # Single file with all proxies (ip:port, one per line)

# Conversation states
WAITING_FOR_LINK, WAITING_FOR_COUNT = range(2)

# ------------------ Proxy Loader (Single File) ------------------
class ProxyLoader:
    @staticmethod
    async def load_proxies() -> List[str]:
        """Load proxies from proxies.txt (ip:port format)."""
        proxies = []
        try:
            with open(PROXY_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Ensure format is ip:port (no protocol)
                        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}$", line):
                            proxies.append(line)
                        else:
                            logging.warning(f"Skipping invalid proxy: {line}")
            logging.info(f"Loaded {len(proxies)} proxies from {PROXY_FILE}")
        except FileNotFoundError:
            logging.error(f"Proxy file {PROXY_FILE} not found! Please create it.")
            return []
        return proxies

# ------------------ View Booster (Optimized for High Volume) ------------------
class TelegramBooster:
    def __init__(self, channel: str, post_id: int, concurrency: int = MAX_CONCURRENT):
        self.channel = channel
        self.post_id = post_id
        self.concurrency = concurrency
        self.ua = UserAgent()

    async def _get_view_token(self, proxy: str) -> Optional[str]:
        """Get token using HTTP proxy (default)."""
        url = f"https://t.me/{self.channel}/{self.post_id}?embed=1"
        headers = {"User-Agent": self.ua.random}
        connector = ProxyConnector.from_url(f"http://{proxy}")
        try:
            async with aiohttp.ClientSession(connector=connector) as sess:
                async with sess.get(url, headers=headers, timeout=VIEW_TIMEOUT) as resp:
                    text = await resp.text()
                    match = re.search(r'window\.telegramEmbed="([^"]+)"', text)
                    return match.group(1) if match else None
        except Exception:
            return None

    async def _send_view(self, token: str, proxy: str) -> bool:
        url = "https://t.me/iv"
        headers = {
            "User-Agent": self.ua.random,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = f"token={token}&post_id={self.post_id}&channel={self.channel}"
        connector = ProxyConnector.from_url(f"http://{proxy}")
        try:
            async with aiohttp.ClientSession(connector=connector) as sess:
                async with sess.post(url, headers=headers, data=data, timeout=VIEW_TIMEOUT) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def send_one_view(self, proxy: str) -> bool:
        token = await self._get_view_token(proxy)
        if token:
            return await self._send_view(token, proxy)
        return False

    async def send_views(self, proxies: List[str], target_count: int) -> int:
        """Send views using rotating proxies."""
        if not proxies:
            return 0
        semaphore = asyncio.Semaphore(self.concurrency)
        success = 0
        proxy_count = len(proxies)

        async def worker(proxy: str):
            nonlocal success
            if success >= target_count:
                return
            async with semaphore:
                ok = await self.send_one_view(proxy)
                if ok:
                    success += 1

        # Create tasks, cycling through proxies
        tasks = []
        for i in range(target_count):
            proxy = proxies[i % proxy_count]
            tasks.append(worker(proxy))
        await asyncio.gather(*tasks)
        return success

# ------------------ Bot Handlers ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 *Ultimate View Bot (5000+ ready)* 🔥\n\n"
        "Send me a Telegram post URL like:\n"
        "`https://t.me/durov/123`\n\n"
        "Then I'll ask how many views you want.\n"
        "I will use proxies from `proxies.txt` to send them.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_LINK

async def receive_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    match = re.search(r"t\.me/([^/]+)/(\d+)", url)
    if not match:
        await update.message.reply_text("❌ Invalid URL. Use format: `https://t.me/username/post_id`", parse_mode="Markdown")
        return WAITING_FOR_LINK

    channel = match.group(1)
    post_id = int(match.group(2))
    context.user_data["channel"] = channel
    context.user_data["post_id"] = post_id

    await update.message.reply_text(
        f"✅ Target: `{channel}/{post_id}`\n\n"
        "Now send the *number of views* (e.g., 5000).\n"
        "⚠️ Large numbers may take several minutes.",
        parse_mode="Markdown"
    )
    return WAITING_FOR_COUNT

async def receive_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Send a positive integer (e.g., 1000).")
        return WAITING_FOR_COUNT

    channel = context.user_data["channel"]
    post_id = context.user_data["post_id"]

    status_msg = await update.message.reply_text(
        f"🚀 Sending *{count}* views to `{channel}/{post_id}`...\n"
        "📂 Loading proxies...",
        parse_mode="Markdown"
    )

    # Load proxies from single file
    proxies = await ProxyLoader.load_proxies()
    if not proxies:
        await status_msg.edit_text("❌ No proxies found. Please upload `proxies.txt` with at least 100 proxies.")
        return ConversationHandler.END

    await status_msg.edit_text(f"📡 Loaded {len(proxies)} proxies. Sending {count} views...\n⏱️ This may take a while.")

    booster = TelegramBooster(channel, post_id, concurrency=MAX_CONCURRENT)
    sent = await booster.send_views(proxies, count)

    await status_msg.edit_text(
        f"✅ *Complete!*\n"
        f"Successfully sent {sent} out of {count} views.\n"
        f"Success rate: {sent/count*100:.1f}%\n\n"
        f"Use /start to try another post.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled. Use /start to begin again.")
    return ConversationHandler.END

def main():
    logging.basicConfig(level=logging.INFO)
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_FOR_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_link)],
            WAITING_FOR_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_count)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv_handler)

    logging.info("Bot started. Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
