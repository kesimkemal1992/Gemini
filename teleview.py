import asyncio, aiohttp, re, random, time
from aiohttp_socks import ProxyConnector
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
BOT_TOKEN = "8254387734:AAEd4VK_abdQuwgbFEiadoqj7UwlxDpmg3A"

# የቋሚ ፕሮክሲ ምንጮች (እነዚህ በፍጹም አይቀነሱም)
FIXED_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=5000",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://proxyspace.pro/socks5.txt",
    "https://api.openproxylist.xyz/socks5.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"
]

class ViewEngine:
    def __init__(self):
        self.is_running = False
        self.channel, self.post_id, self.target = "", 0, 0
        self.success, self.start_views, self.current_views = 0, 0, 0
        self.start_time = None
        self.proxies = [] # ጠቅላላ ፕሮክሲዎች እዚህ ይከማቻሉ
        self.github_api_url = "" # አንተ የምትሰጠው API Link
        self.sem = asyncio.Semaphore(5000)

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

    async def fetch_proxies(self):
        """ሁሉንም ምንጮች በአንዴ ሰብስቦ ፕሮክሲዎቹን ያበዛል"""
        all_found = []
        async with aiohttp.ClientSession() as s:
            # 1. ከቋሚ ምንጮች (Fixed Sources)
            for url in FIXED_SOURCES:
                try:
                    async with s.get(url, timeout=10) as r:
                        text = await r.text()
                        found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", text)
                        all_found.extend([('socks5', p) for p in found])
                except: pass

            # 2. ከ GitHub API (Deep Scan) - አንተ የሰጠኸኝ ሊንክ ከሆነ
            if self.github_api_url:
                async def scan(url):
                    try:
                        async with s.get(url, timeout=10) as r:
                            items = await r.json()
                            if isinstance(items, list):
                                for item in items:
                                    if item['type'] == 'dir': await scan(item['url'])
                                    elif item['type'] == 'file' and '.txt' in item['name']:
                                        async with s.get(item['download_url']) as fr:
                                            text = await fr.text()
                                            ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", text)
                                            all_found.extend([('socks5', p) for p in ips])
                    except: pass
                await scan(self.github_api_url)
        
        self.proxies = list(set(all_found)) # ልዩ የሆኑትን ብቻ አስቀር
        random.shuffle(self.proxies)

    async def hit(self, pt, p):
        async with self.sem:
            if not self.is_running: return
            try:
                conn = ProxyConnector.from_url(f"{pt}://{p}")
                h = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36', 'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1', 'X-Requested-With': 'XMLHttpRequest'}
                async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=4, connect=2)) as s:
                    async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", headers=h) as r:
                        token = re.search(r'data-view="([^"]+)"', await r.text())
                        if token:
                            async with s.post(f"https://t.me/v/?views={token.group(1)}", headers=h) as vr:
                                if "true" in await vr.text(): self.success += 1
            except: pass

engine = ViewEngine()

async def handle_msg(update, context):
    txt = update.message.text.strip()
    if "api.github.com" in txt:
        engine.github_api_url = txt
        await update.message.reply_text(f"✅ GitHub API ተጨምሯል! አሁን ከቋሚ ምንጮች ጋር ተቀናጅቶ ይሰራል::")
    else:
        await update.message.reply_text("እባክህ የ GitHub API ሊንክ ላክልኝ::")

async def add(update, context):
    if len(context.args) < 3: return
    engine.channel, engine.post_id, engine.target = context.args[0].replace("@",""), int(context.args[1]), int(context.args[2])
    engine.is_running, engine.success, engine.start_time = True, 0, time.time()
    engine.start_views = await engine.get_views()
    msg = await update.message.reply_text("🚀 ከፍተኛ ፍጥነት ያለው ስራ ተጀመረ...")
    
    while engine.is_running:
        engine.current_views = await engine.get_views()
        added = max(0, engine.current_views - engine.start_views)
        if engine.current_views >= (engine.start_views + engine.target):
            engine.is_running = False
            break
        
        # በየዙሩ ፕሮክሲዎችን ማደስ (Proxy Refresh)
        await engine.fetch_proxies()
        
        speed = int(added / ((time.time() - engine.start_time) / 60)) if (time.time() - engine.start_time) > 0 else 0
        text = (f"🔥 **MAXIMUM PROXY POOL**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📈 Views: `{engine.current_views}`\n"
                f"⚡ Speed: `{speed} v/min` | 🛠 Success: `{engine.success}`\n"
                f"📡 Total Proxies: `{len(engine.proxies)}` \n"
                f"━━━━━━━━━━━━━━━")
        try: await msg.edit_text(text, parse_mode="Markdown")
        except: pass
        
        tasks = [engine.hit(pt, p) for pt, p in engine.proxies[:5000]]
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("reset", lambda u,c: setattr(engine, 'proxies', [])))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))
    app.run_polling()
