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

MAX_CONCURRENT = 30          # Concurrent requests (Railway free tier can handle ~30)
VIEW_TIMEOUT = 12            # Seconds per request
PROXY_TEST_URL = "https://httpbin.org/ip"   # Quick proxy test endpoint
PROXY_API_URL = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all"

# Conversation states
WAITING_FOR_LINK, WAITING_FOR_COUNT = range(2)

# ------------------ Live Proxy Fetcher ------------------
class ProxyFetcher:
    @staticmethod
    async def fetch_live_proxies() -> List[str]:
        """Fetch fresh HTTP proxies from proxyscrape API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(PROXY_API_URL, timeout=15) as resp:
                    if resp.status != 200:
                        logging.error(f"Proxy API returned {resp.status}")
                        return []
                    text = await resp.text()
                    # Extract IP:PORT lines
                    proxies = []
                    for line in text.splitlines():
                        line = line.strip()
                        if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5}$", line):
                            proxies.append(line)
                    logging.info(f"Fetched {len(proxies)} raw proxies from API")
                    return proxies
        except Exception as e:
            logging.error(f"Failed to fetch proxies: {e}")
            return []

    @staticmethod
    async def validate_proxies(proxies: List[str], limit: int = 100) -> List[str]:
        """Test which proxies actually work (quick connectivity test)."""
        if not proxies:
            return []
        valid = []
        semaphore = asyncio.Semaphore(20)  # Test 20 at a time

        async def test_one(proxy: str):
            async with semaphore:
                connector = ProxyConnector.from_url(f"http://{proxy}")
                try:
                    async with aiohttp.ClientSession(connector=connector) as sess:
                        async with sess.get(PROXY_TEST_URL, timeout=5) as resp:
                            if resp.status == 200:
                                return proxy
                except Exception:
                    pass
                return None

        # Test first 'limit' proxies or all if fewer
        test_proxies = proxies[:min(limit, len(proxies))]
        tasks = [test_one(p) for p in test_proxies]
        results = await asyncio.gather(*tasks)
        valid = [p for p in results if p]
        logging.info(f"Validated {len(valid)} working proxies out of {len(test_proxies)} tested")
        return valid

# ------------------ View Booster ------------------
class TelegramBooster:
    def __init__(self, channel: str, post_id: int, concurrency: int = MAX_CONCURRENT):
        self.channel = channel
        self.post_id = post_id
        self.concurrency = concurrency
        self.ua = UserAgent()

    async def _get_view_token(self, proxy: str) -> Optional[str]:
        url = f"https://t.me/{self.channel}/{self.post_id}?embed=1"
        headers = {"User-Agent": self.ua.random}
        connector = ProxyConnector.from_url(f"http://{proxy}")
        try:
            async with aiohttp.ClientSession(connector=connector) as sess:
                async with sess.get(url, headers=headers, timeout=VIEW_TIMEOUT) as resp:
                    text = await resp.text()
                    # Look for the token in the embed page
                    match = re.search(r'window\.telegramEmbed="([^"]+)"', text)
                    if not match:
                        # Fallback: try another pattern (some posts use different JS)
                        match = re.search(r'"token":"([^"]+)"', text)
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
        if not proxies:
            return 0
        semaphore = asyncio.Semaphore(self.concurrency)
        success = 0

        async def worker(proxy: str):
            nonlocal success
            if success >= target_count:
                return
            async with semaphore:
                ok = await self.send_one_view(proxy)
                if ok:
                    success += 1

        # Cycle through proxies
        proxy_count = len(proxies)
        tasks = []
        for i in range(target_count):
            proxy = proxies[i % proxy_count]
            tasks.append(worker(proxy))
        await asyncio.gather(*tasks)
        return success

# ------------------ Bot Handlers ------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 *Ultimate View Bot (Live Proxies)* 🔥\n\n"
        "Send me a Telegram post URL like:\n"
        "`https://t.me/durov/123`\n\n"
        "Then I'll ask how many views you want.\n"
        "I will fetch fresh proxies automatically and validate them.",
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
        f"🚀 Preparing to send *{count}* views to `{channel}/{post_id}`...\n"
        "🌐 Fetching fresh proxies from API...",
        parse_mode="Markdown"
    )

    # Step 1: Fetch raw proxies from API
    raw_proxies = await ProxyFetcher.fetch_live_proxies()
    if not raw_proxies:
        await status_msg.edit_text("❌ Failed to fetch proxies from API. Try again later.")
        return ConversationHandler.END

    await status_msg.edit_text(f"📡 Fetched {len(raw_proxies)} proxies. Testing connectivity...")

    # Step 2: Validate proxies (test first 150 for speed)
    valid_proxies = await ProxyFetcher.validate_proxies(raw_proxies, limit=150)
    if not valid_proxies:
        await status_msg.edit_text("❌ No working proxies found after testing. Try again later (API may have given dead ones).")
        return ConversationHandler.END

    await status_msg.edit_text(f"✅ Found {len(valid_proxies)} working proxies. Sending {count} views...\n⏱️ This may take a while.")

    # Step 3: Send views using only validated proxies
    booster = TelegramBooster(channel, post_id, concurrency=MAX_CONCURRENT)
    sent = await booster.send_views(valid_proxies, count)

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
