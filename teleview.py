import asyncio
import aiohttp
import re
import random
import time
from datetime import datetime, timedelta
from aiohttp_socks import ProxyConnector
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# --- CONFIGURATION ---
BOT_TOKEN = "8254387734:AAEd4VK_abdQuwgbFEiadoqj7UwlxDpmg3A" # እዚህ ጋር የቦት ቶከንህን አስገባ
SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://proxyspace.pro/socks5.txt",
    "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/socks5/socks5.txt"
]

class ViewManager:
    def __init__(self):
        self.is_running = False
        self.channel = ""
        self.post_id = 0
        self.target = 0
        self.success = 0
        self.start_views = 0
        self.current_views = 0
        self.start_time = None
        self.proxies = []
        self.sem = asyncio.Semaphore(1500) # Extreme Speed

    async def get_real_views(self):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", timeout=10) as r:
                    html = await r.text()
                    match = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', html)
                    if match:
                        val = match.group(1).replace('K', '000').replace('M', '000000').replace('.', '')
                        return int(''.join(filter(str.isdigit, val)))
        except: return 0
        return 0

    async def fetch_proxies(self):
        all_proxies = []
        async with aiohttp.ClientSession() as s:
            for url in SOURCES:
                try:
                    async with s.get(url, timeout=10) as r:
                        found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", await r.text())
                        all_proxies.extend([('socks5', p) for p in found])
                except: pass
        self.proxies = list(set(all_proxies))
        random.shuffle(self.proxies)

    async def send_view(self, ptype, proxy):
        async with self.sem:
            if not self.is_running or self.current_views >= (self.start_views + self.target): return
            try:
                conn = ProxyConnector.from_url(f"{ptype}://{proxy}")
                async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=8, connect=3)) as s:
                    headers = {'User-Agent': "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15", 'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1', 'X-Requested-With': 'XMLHttpRequest'}
                    async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", headers=headers) as r:
                        token = re.search(r'data-view="([^"]+)"', await r.text())
                        if token:
                            async with s.post(f"https://t.me/v/?views={token.group(1)}", headers=headers) as vr:
                                if "true" in await vr.text(): self.success += 1
            except: pass

manager = ViewManager()

# --- TELEGRAM BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 እንኳን ደህና መጡ! ቪው ለመጀመር ትዕዛዙን እንዲህ ይላኩ፦\n\n`/add channel_username post_id amount` \n\nምሳሌ፦ `/add xauusd_x1 164 1000` ")

async def add_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("❌ ስህተት! ትክክለኛው አጻጻፍ፦ `/add channel post_id amount` ")
        return

    manager.channel = context.args[0].replace("@", "")
    manager.post_id = int(context.args[1])
    manager.target = int(context.args[2])
    manager.is_running = True
    manager.success = 0
    manager.start_time = time.time()
    manager.start_views = await manager.get_real_views()
    
    status_msg = await update.message.reply_text("🚀 ስራ ተጀምሯል... መረጃው እስኪመጣ ይጠብቁ")
    
    # Background task ማስጀመር
    asyncio.create_task(run_process(status_msg))

async def run_process(status_msg):
    while manager.is_running:
        manager.current_views = await manager.get_real_views()
        total_goal = manager.start_views + manager.target
        
        if manager.current_views >= total_goal:
            manager.is_running = False
            await status_msg.edit_text(f"✅ ተጠናቋል! \nጠቅላላ ቪው: {manager.current_views}")
            break

        # Progress Animation & Logic
        added_so_far = manager.current_views - manager.start_views
        if added_so_far < 0: added_so_far = 0
        progress = min(100, int((added_so_far / manager.target) * 100))
        bar = "▓" * (progress // 10) + "░" * (10 - (progress // 10))
        
        # የቀሪ ጊዜ ግምት
        elapsed = time.time() - manager.start_time
        if added_so_far > 0:
            speed_per_sec = added_so_far / elapsed
            remaining_views = manager.target - added_so_far
            rem_seconds = remaining_views / speed_per_sec if speed_per_sec > 0 else 0
            rem_time = str(timedelta(seconds=int(rem_seconds)))
        else:
            rem_time = "በመገመት ላይ..."

        text = (
            f"🔥 **የቪው ሂደት ላይ...**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 Progress: [{bar}] {progress}%\n"
            f"✅ የደረሰው: `{manager.current_views}`\n"
            f"🎯 ግባችን: `{total_goal}`\n"
            f"⏳ የቀረው ቪው: `{max(0, manager.target - added_so_far)}`\n"
            f"🕒 የቀረው ጊዜ: `{rem_time}`\n"
            f"━━━━━━━━━━━━━━━\n"
            f"⚡ Speed: Aggressive SOCKS5\n"
            f"🛠 Logs Success: {manager.success}"
        )

        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except: pass

        await manager.fetch_proxies()
        tasks = [manager.send_view(pt, p) for pt, p in manager.proxies[:1500]]
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    manager.is_running = False
    await update.message.reply_text("🛑 ስራው ተቋርጧል!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_view))
    app.add_handler(CommandHandler("stop", stop))
    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
