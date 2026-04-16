import asyncio, aiohttp, re, random, time
from datetime import timedelta
from aiohttp_socks import ProxyConnector
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIG ---
BOT_TOKEN = "8254387734:AAEd4VK_abdQuwgbFEiadoqj7UwlxDpmg3A"

SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=5000",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/Zaeem20/FREE_PROXIES_LIST/master/socks5.txt",
    "https://proxyspace.pro/socks5.txt"
]

class ViewEngine:
    def __init__(self):
        self.is_running = False
        self.channel, self.post_id, self.target = "", 0, 0
        self.success, self.start_views, self.current_views = 0, 0, 0
        self.start_time = None
        self.proxies = [] 
        self.sem = asyncio.Semaphore(2000)

    async def get_views(self):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", timeout=10) as r:
                    html = await r.text()
                    m = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', html)
                    if m:
                        v = m.group(1).replace('K', '000').replace('M', '000000').replace('.', '')
                        return int(''.join(filter(str.isdigit, v)))
        except: return 0
        return 0

    async def scrape_fixed(self):
        temp = []
        async with aiohttp.ClientSession() as s:
            for url in SOURCES:
                try:
                    async with s.get(url, timeout=10) as r:
                        content = await r.text()
                        found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", content)
                        temp.extend([('socks5', p) for p in found])
                except: pass
        return temp

    async def deep_scan_repo(self, repo_url):
        # GitHub URL ፎርማትን ማስተካከል
        repo_path = repo_url.replace("https://github.com/", "").strip("/")
        api_url = f"https://api.github.com/repos/{repo_path}/contents"
        all_found = []

        async with aiohttp.ClientSession() as s:
            async def scan(url):
                try:
                    async with s.get(url, timeout=15) as r:
                        if r.status != 200: return
                        items = await r.json()
                        if not isinstance(items, list): return
                        
                        for item in items:
                            if item['type'] == 'dir':
                                await scan(item['url']) # ሪከርሲቭ ፍለጋ
                            elif item['type'] == 'file' and any(ext in item['name'] for ext in ['.txt', '.list', '.s5', '.proxy']):
                                async with s.get(item['download_url']) as fr:
                                    text = await fr.text()
                                    found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", text)
                                    all_found.extend([('socks5', p) for p in found])
                except: pass

            await scan(api_url)
        return list(set(all_found))

    async def hit(self, pt, p):
        async with self.sem:
            if not self.is_running: return
            try:
                conn = ProxyConnector.from_url(f"{pt}://{p}")
                # ለቪው መቆጠር ወሳኙ ክፍል (Headers)
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Android 14; Mobile; rv:122.0) Gecko/122.0 Firefox/122.0',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1',
                    'X-Requested-With': 'org.telegram.messenger'
                }
                async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=10, connect=3)) as s:
                    async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", headers=headers) as r:
                        html = await r.text()
                        token = re.search(r'data-view="([^"]+)"', html)
                        if token:
                            # እውነተኛ የቪው ጥያቄ መላክ
                            async with s.post(f"https://t.me/v/?views={token.group(1)}", headers=headers) as vr:
                                if "true" in await vr.text(): self.success += 1
            except: pass

engine = ViewEngine()

async def work(msg):
    while engine.is_running:
        curr = await engine.get_views()
        if curr > 0: engine.current_views = curr
        
        added = max(0, engine.current_views - engine.start_views)
        if engine.current_views >= (engine.start_views + engine.target):
            engine.is_running = False
            await msg.edit_text(f"✅ ተጠናቋል! Views: {engine.current_views}")
            break

        speed = int(added / ((time.time() - engine.start_time) / 60)) if (time.time() - engine.start_time) > 0 else 0
        
        text = (f"🚀 **DEEP SCAN TURBO V6**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📊 Progress: `{added}/{engine.target}`\n"
                f"✅ Views: `{engine.current_views}`\n"
                f"⚡ Speed: `{speed} v/min`\n"
                f"🛠 Success: `{engine.success}`\n"
                f"📡 Total Proxies: `{len(engine.proxies)}`\n"
                f"━━━━━━━━━━━━━━━")
        try: await msg.edit_text(text, parse_mode="Markdown")
        except: pass
        
        # 3000 ፕሮክሲዎችን በአንድ ላይ መላክ (Extreme)
        tasks = [engine.hit(pt, p) for pt, p in engine.proxies[:3000]]
        if tasks: await asyncio.gather(*tasks)
        await asyncio.sleep(1)

async def handle_repo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if "github.com" in txt:
        s_msg = await update.message.reply_text("🔎 **DEEP SCANNING**... ሁሉንም ፎልደሮች እስከ ጥግ ድረስ እያሰስኩ ነው...")
        repo_ips = await engine.deep_scan_repo(txt)
        fixed_ips = await engine.scrape_fixed()
        engine.proxies = list(set(repo_ips + fixed_ips))
        await s_msg.edit_text(f"🏁 **ምርመራ ተጠናቋል!**\n\n📁 ከ GitHub ፎልደሮች: **{len(repo_ips)}**\n🌐 ከ ቋሚ ምንጮች: **{len(fixed_ips)}**\n🎯 ጠቅላላ ተገኙ: **{len(engine.proxies)}**\n\nአሁን `/add channel post_id target` ይበሉ!")
    else:
        # ለተራ አይፒዎች
        ips = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", txt)
        if ips:
            engine.proxies.extend([('socks5', p) for p in ips])
            await update.message.reply_text(f"✅ {len(ips)} አይፒዎች ተጨምረዋል።")

async def add(update, context):
    if not engine.proxies:
        engine.proxies = await engine.scrape_fixed()
    if len(context.args) < 3: return
    engine.channel, engine.post_id, engine.target = context.args[0].replace("@",""), int(context.args[1]), int(context.args[2])
    engine.is_running, engine.success, engine.start_time = True, 0, time.time()
    engine.start_views = await engine.get_views()
    msg = await update.message.reply_text("🔥 ስራ ተጀመረ...")
    context.application.create_task(work(msg))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("stop", lambda u,c: setattr(engine, 'is_running', False)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_repo))
    app.run_polling()
