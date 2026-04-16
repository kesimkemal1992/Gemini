import asyncio, aiohttp, re, random, time
from aiohttp_socks import ProxyConnector
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# --- CONFIG ---
BOT_TOKEN = "8254387734:AAEd4VK_abdQuwgbFEiadoqj7UwlxDpmg3A"
GEONODE_API = "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc"

class ViewEngine:
    def __init__(self):
        self.is_running = False
        self.channel, self.post_id, self.target = "", 0, 0
        self.success, self.start_views, self.current_views = 0, 0, 0
        self.start_time = None
        self.proxies = []
        self.sem = asyncio.Semaphore(1500)

    async def get_views(self):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", timeout=10) as r:
                    html = await r.text()
                    # ይበልጥ ጠንከር ያለ የቪው መፈለጊያ Regex
                    m = re.search(r'class="tgme_widget_message_views">([0-9\.]+[KkMm]?)', html)
                    if m:
                        v = m.group(1).upper().replace('K', '000').replace('M', '000000').replace('.', '')
                        return int(''.join(filter(str.isdigit, v)))
        except: return 0
        return 0

    async def scrape(self):
        temp = []
        async with aiohttp.ClientSession() as s:
            try:
                # Geonode API ንባብ
                async with s.get(GEONODE_API, timeout=15) as r:
                    data = await r.json()
                    for p in data.get('data', []):
                        if 'socks5' in p.get('protocols', []):
                            temp.append(('socks5', f"{p['ip']}:{p['port']}"))
                # ተጨማሪ ምንጭ
                async with s.get("https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5", timeout=10) as r:
                    text = await r.text()
                    found = re.findall(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?", text)
                    temp.extend([('socks5', p) for p in found])
            except: pass
        self.proxies = list(set(temp))
        random.shuffle(self.proxies)

    async def hit(self, pt, p):
        async with self.sem:
            if not self.is_running: return
            try:
                # በየጥያቄው የተለያየ User-Agent መጠቀም
                ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(100, 124)}.0.0.0 Safari/537.36"
                
                conn = ProxyConnector.from_url(f"{pt}://{p}")
                h = {
                    'User-Agent': ua,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                    'Referer': f'https://t.me/{self.channel}/{self.post_id}?embed=1'
                }
                
                async with aiohttp.ClientSession(connector=conn, timeout=aiohttp.ClientTimeout(total=8, connect=4)) as s:
                    # 1. መጀመሪያ ገጹን ከፍቶ ቶከኑን መቀበል
                    async with s.get(f"https://t.me/{self.channel}/{self.post_id}?embed=1", headers=h) as r:
                        res = await r.text()
                        # አዲሱን የቴሌግራም ቶከን ፎርማት መፈለጊያ
                        token = re.search(r'data-view="([^"]+)"', res)
                        
                        if token:
                            # 2. ቪውውን ለማስቆጠር ኩኪዎችን (Cookies) ጨምሮ መላክ
                            await asyncio.sleep(random.uniform(0.5, 1.5)) # እውነተኛ ሰው እንዲመስል
                            async with s.post(f"https://t.me/v/?views={token.group(1)}", headers=h) as vr:
                                if "true" in await vr.text():
                                    self.success += 1
            except: pass

engine = ViewEngine()

async def work(msg):
    while engine.is_running:
        v = await engine.get_views()
        if v > 0: engine.current_views = v
        added = max(0, engine.current_views - engine.start_views)
        
        if engine.current_views >= (engine.start_views + engine.target):
            engine.is_running = False
            break

        status = (f"🚀 **REFINED TURBO ACTIVE**\n"
                  f"━━━━━━━━━━━━━━━\n"
                  f"📊 Views: `{engine.current_views}`\n"
                  f"✅ Success: `{engine.success}`\n"
                  f"📡 Pool: `{len(engine.proxies)}` \n"
                  f"━━━━━━━━━━━━━━━")
        try: await msg.edit_text(status, parse_mode="Markdown")
        except: pass
        
        await engine.scrape()
        # 1000 በ 1000 ጥያቄዎችን መላክ (ቴሌግራም እንዳይነቃ)
        tasks = [engine.hit(pt, p) for pt, p in engine.proxies[:1000]]
        if tasks: await asyncio.gather(*tasks)
        await asyncio.sleep(2)

async def add(update, context):
    if len(context.args) < 3: return
    engine.channel, engine.post_id, engine.target = context.args[0].replace("@",""), int(context.args[1]), int(context.args[2])
    engine.is_running, engine.success, engine.start_time = True, 0, time.time()
    engine.start_views = await engine.get_views()
    msg = await update.message.reply_text("🔄 ኮዱ ተስተካክሎ ስራ ተጀመረ...")
    context.application.create_task(work(msg))

if __name__ == "__main__":
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("add", add))
    app.add_handler(CommandHandler("stop", lambda u,c: setattr(engine, 'is_running', False)))
    app.run_polling()
