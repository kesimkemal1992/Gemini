import asyncio
import aiohttp
import re
import random
import time
import json
from datetime import timedelta
from aiohttp_socks import ProxyConnector
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
BOT_TOKEN = "8759135008:AAFc5a-Ek1RrtmAwd7vWK04kdyt21TNgE4I"
SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=5000",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://proxyspace.pro/socks5.txt"
]

# Realistic browser headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://t.me/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin"
}

class ViewEngine:
    def __init__(self):
        self.is_running = False
        self.channel = ""
        self.post_id = 0
        self.target = 0
        self.success = 0
        self.start_views = 0
        self.current_views = 0
        self.start_time = None
        self.proxies = []          # list of (type, proxy_str)
        self.custom_urls = []
        self.custom_ips = []
        self.work_queue = asyncio.Queue()
        self.worker_tasks = []
        self.active_workers = 200   # concurrency limit (safe for free proxies)

    async def get_views(self):
        """Extract current view count from embed page"""
        try:
            async with aiohttp.ClientSession(headers=HEADERS) as s:
                url = f"https://t.me/{self.channel}/{self.post_id}?embed=1"
                async with s.get(url, timeout=10) as r:
                    html = await r.text()
                    # Try multiple patterns
                    patterns = [
                        r'<span class="tgme_widget_message_views">([^<]+)</span>',
                        r'data-views="([^"]+)"',
                        r'<div class="tgme_widget_message_views">([^<]+)</div>'
                    ]
                    for pat in patterns:
                        m = re.search(pat, html)
                        if m:
                            v = m.group(1).replace('K', '000').replace('M', '000000').replace('.', '')
                            return int(''.join(filter(str.isdigit, v)))
        except Exception as e:
            print(f"View fetch error: {e}")
        return 0

    async def scrape_proxies(self):
        """Fetch fresh proxies from sources"""
        all_srcs = SOURCES + self.custom_urls
        temp = self.custom_ips.copy()
        async with aiohttp.ClientSession() as s:
            for url in all_srcs:
                try:
                    async with s.get(url, timeout=10) as r:
                        if "application/json" in r.headers.get("Content-Type", ""):
                            data = await r.json()
                            # Handle different JSON structures
                            proxies = data.get('data', [])
                            if isinstance(proxies, list):
                                for p in proxies:
                                    if isinstance(p, dict):
                                        ip = p.get('ip') or p.get('host')
                                        port = p.get('port')
                                        if ip and port:
                                            temp.append(('socks5', f"{ip}:{port}"))
                        else:
                            text = await r.text()
                            found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}", text)
                            temp.extend([('socks5', p) for p in found])
                except:
                    pass
        # Deduplicate
        self.proxies = list(set(temp))
        random.shuffle(self.proxies)
        print(f"Scraped {len(self.proxies)} proxies")

    async def validate_proxy(self, proxy_type, proxy_str):
        """Quick check if proxy is alive and can reach Telegram"""
        try:
            connector = ProxyConnector.from_url(f"{proxy_type}://{proxy_str}")
            async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5)) as s:
                async with s.get("https://t.me/", headers=HEADERS) as r:
                    if r.status == 200:
                        return True
        except:
            pass
        return False

    async def hit(self, proxy_type, proxy_str):
        """Attempt to register one view using a proxy"""
        if not self.is_running:
            return
        try:
            connector = ProxyConnector.from_url(f"{proxy_type}://{proxy_str}")
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(total=8, connect=3),
                headers=HEADERS
            ) as s:
                # Step 1: Get the embed page to extract view token
                embed_url = f"https://t.me/{self.channel}/{self.post_id}?embed=1"
                async with s.get(embed_url) as resp:
                    html = await resp.text()
                    # Look for data-view token (old method)
                    token_match = re.search(r'data-view="([^"]+)"', html)
                    if not token_match:
                        # Alternative: look for view key in script
                        token_match = re.search(r'view":"([^"]+)"', html)
                    if token_match:
                        token = token_match.group(1)
                        # Step 2: Send view request
                        view_url = f"https://t.me/v/?views={token}"
                        async with s.post(view_url, headers={"X-Requested-With": "XMLHttpRequest"}) as vr:
                            text = await vr.text()
                            # Check for success response
                            if "true" in text or '"ok":true' in text:
                                self.success += 1
                                return True
        except Exception as e:
            # Silent fail
            pass
        return False

    async def worker(self):
        """Worker that consumes proxies from queue"""
        while self.is_running:
            try:
                proxy = await asyncio.wait_for(self.work_queue.get(), timeout=1)
            except asyncio.TimeoutError:
                continue
            try:
                await self.hit(*proxy)
            except:
                pass
            self.work_queue.task_done()

    async def start_workers(self):
        """Launch worker tasks"""
        self.worker_tasks = []
        for _ in range(self.active_workers):
            task = asyncio.create_task(self.worker())
            self.worker_tasks.append(task)

    async def stop_workers(self):
        """Stop all workers"""
        for task in self.worker_tasks:
            task.cancel()
        await asyncio.gather(*self.worker_tasks, return_exceptions=True)

    async def run(self, msg):
        """Main loop: refresh proxies, fill queue, monitor progress"""
        await self.start_workers()
        last_refresh = 0
        while self.is_running:
            # Update current views
            self.current_views = await self.get_views()
            added = max(0, self.current_views - self.start_views)
            if self.current_views >= (self.start_views + self.target):
                self.is_running = False
                await msg.edit_text(f"✅ Target reached!\nViews: {self.current_views}")
                break

            # Progress display
            prog = min(100, int((added / self.target) * 100)) if self.target > 0 else 0
            bar = "▓" * (prog // 10) + "░" * (10 - (prog // 10))
            elapsed = time.time() - self.start_time
            speed = int(added / (elapsed / 60)) if elapsed > 0 else 0
            rem_time = str(timedelta(seconds=int((self.target - added) / (added / elapsed)))) if added > 0 else "..."
            text = (f"🚀 **BOOSTING ACTIVE**\n"
                    f"━━━━━━━━━━━━━━━\n"
                    f"📊 [{bar}] {prog}%\n"
                    f"✅ Views: `{self.current_views}` | 🎯 Target: `{self.start_views + self.target}`\n"
                    f"⚡ Speed: `{speed} views/min`\n"
                    f"🕒 Remaining: `{rem_time}`\n"
                    f"🛠 Successful hits: `{self.success}`\n"
                    f"🌐 Proxies in queue: `{self.work_queue.qsize()}`")
            try:
                await msg.edit_text(text, parse_mode="Markdown")
            except:
                pass

            # Refresh proxy list every 30 seconds
            if time.time() - last_refresh > 30:
                await self.scrape_proxies()
                # Validate a subset (optional, time-consuming)
                # Filter only good proxies to queue
                for p in self.proxies[:500]:  # limit to 500 per cycle
                    await self.work_queue.put(p)
                last_refresh = time.time()
            else:
                # If queue is low, refill without full scrape
                if self.work_queue.qsize() < 100 and self.proxies:
                    for p in self.proxies[:100]:
                        await self.work_queue.put(p)

            await asyncio.sleep(2)

        await self.stop_workers()

# Global engine instance
engine = ViewEngine()

# --- Bot Handlers ---
async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/add channel post_id target`\nExample: `/add mychannel 123 1000`")
        return
    engine.channel = context.args[0].replace("@", "")
    engine.post_id = int(context.args[1])
    engine.target = int(context.args[2])
    engine.is_running = True
    engine.success = 0
    engine.start_time = time.time()
    engine.start_views = await engine.get_views()
    if engine.start_views == 0:
        await update.message.reply_text("⚠️ Could not fetch current view count. Make sure the post exists and is public.")
        engine.is_running = False
        return
    msg = await update.message.reply_text("🔥 Starting booster...")
    asyncio.create_task(engine.run(msg))

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    engine.is_running = False
    await update.message.reply_text("🛑 Stopped.")

async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if txt.startswith("http"):
        engine.custom_urls.append(txt)
        await update.message.reply_text("✅ Custom proxy source added. It will be used on next refresh.")
    else:
        # Accept plain IP:port lines
        found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}:\d{1,5}", txt)
        if found:
            engine.custom_ips.extend([('socks5', p) for p in found])
            await update.message.reply_text(f"✅ Added {len(found)} custom proxy(ies).")
        else:
            await update.message.reply_text("Send me a proxy source URL or a list of `IP:PORT` (one per line).")

# --- Main ---
if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    print("Bot started. Use /add @channel post_id target")
    app.run_polling()
