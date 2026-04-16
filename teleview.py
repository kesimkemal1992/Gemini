import asyncio
import aiohttp
import re
import random
import time
from datetime import timedelta
from aiohttp_socks import ProxyConnector
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
BOT_TOKEN = "8254387734:AAEd4VK_abdQuwgbFEiadoqj7UwlxDpmg3A" 
# የ GeoNode API እና ሌሎች ምንጮች
GEONODE_API = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc"
SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=5000",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://proxyspace.pro/socks5.txt"
]

custom_proxies = []

class ViewEngine:
    def __init__(self):
        self.is_running = False
        self.channel, self.post_id, self.target = "", 0, 0
        self.success, self.start_views, self.current_views = 0, 0, 0
        self.start_time = None
        self.proxies = []
        self.sem = asyncio.Semaphore(600) # ለ Railway የተመጣጠነ ፍጥነት

    async def get_views(self):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", timeout=5) as r:
                    html = await r.text()
                    m = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', html)
                    if m:
                        v = m.group(1).replace('K', '000').replace('M', '000000').replace('.', '')
                        return int(''.join(filter(str.isdigit, v)))
        except: return 0
        return 0

    async def scrape(self):
        global custom_proxies
        temp = []
        if custom_proxies: temp.extend(custom_proxies)
            
        async with aiohttp.ClientSession() as s:
            # 1. GeoNode API ን ማንበብ (JSON Format)
            try:
                async with s.get(GEONODE_API, timeout=10) as r:
                    data = await r.json()
                    for p in data.get('data', []):
                        # SOCKS5 ወይም SOCKS4 ቅድሚያ እንሰጣለን
                        ptype = 'socks5' if 'socks5' in p['protocols'] else 'http'
                        temp.append((ptype, f"{p['ip']}:{p['port']}"))
            except: pass

            # 2. ሌሎች የቴክስት ምንጮችን ማንበብ
            tasks = [s.get(url, timeout=10) for url in SOURCES]
            res = await asyncio.gather(*tasks, return_exceptions=True)
            for r in res:
                if isinstance(r, aiohttp.ClientResponse):
                    found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", await r.text())
                    temp.extend([('socks5', p) for p in found])
                    
        self.proxies = list(set(temp))
        random.shuffle(self.proxies)

    async def hit(self, pt, p):
        async with self.sem:
            if not self.is_running: return
            try:
                conn = ProxyConnector.from_url(f"{pt}://{p}")
                async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=10, connect=3)) as s:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1'}
                    async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", headers=headers) as r:
                        token = re.search(r'data-view="([^"]+)"', await r.text())
                        if token:
                            async with s.post(f"https://t.me/v/?views={token.group(1)}", headers={'X-Requested-With': 'XMLHttpRequest', 'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1'}) as vr:
                                if "true" in await vr.text(): self.success += 1
            except: pass

engine = ViewEngine()

# --- BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 ቦቱ ዝግጁ ነው!\n\n`/add channel post_id target` ይላኩ።\nወይም ፕሮክሲ ሊስት ኮፒ አድርገው ይላኩ።")

async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3: return await update.message.reply_text("💡 አጠቃቀም፦ `/add xauusd_x1 164 1000`")
    if engine.is_running: return await update.message.reply_text("⚠️ ቦቱ ስራ ላይ ነው!")
    
    engine.channel, engine.post_id, engine.target = context.args[0].replace("@",""), int(context.args[1]), int(context.args[2])
    engine.is_running, engine.success, engine.start_time = True, 0, time.time()
    engine.start_views = await engine.get_views()
    
    msg = await update.message.reply_text("🚀 ስራ ተጀምሯል...")
    context.application.create_task(work(msg))

async def work(msg):
    while engine.is_running:
        engine.current_views = await engine.get_views()
        added = max(0, engine.current_views - engine.start_views)
        
        if engine.current_views >= (engine.start_views + engine.target):
            engine.is_running = False
            await msg.edit_text(f"✅ ተጠናቋል! ጠቅላላ: {engine.current_views}")
            break

        prog = min(100, int((added / engine.target) * 100)) if engine.target > 0 else 0
        bar = "▓" * (prog // 10) + "░" * (10 - (prog // 10))
        elapsed = time.time() - engine.start_time
        rem_time = str(timedelta(seconds=int((engine.target - added) / (added / elapsed)))) if added > 0 else "..."

        text = (f"🔥 **ULTRA MODE (GeoNode API)**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📊 Progress: [{bar}] {prog}%\n"
                f"✅ Views: `{engine.current_views}`\n"
                f"🎯 Target: `{engine.start_views + engine.target}`\n"
                f"🕒 የቀረው ጊዜ: `{rem_time}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"⚡ Logs Success: {engine.success}")
        
        try: await msg.edit_text(text, parse_mode="Markdown")
        except: pass

        await engine.scrape()
        await asyncio.gather(*[engine.hit(pt, p) for pt, p in engine.proxies[:1000]])
        await asyncio.sleep(4)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    engine.is_running = False
    await update.message.reply_text("🛑 ቆሟል!")

async def receive_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", update.message.text)
    if found:
        global custom_proxies
        custom_proxies.extend([('socks5', p) for p in found])
        await update.message.reply_text(f"✅ {len(found)} ፕሮክሲዎች ተጨምረዋል!")

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_proxies))
    app.run_polling()
