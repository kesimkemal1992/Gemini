# // Telegram Auto Views 2024 (FIXED - No ProxyLink folder needed) \\
# - Looks for http.txt, socks4.txt, socks5.txt in the same directory
# - Stops after target views (-a)
# - Clear error messages, no infinite waiting

import aiohttp, asyncio
from re import search, finditer
from aiohttp_socks import ProxyConnector
from argparse import ArgumentParser
from re import compile
from threading import Thread
from time import sleep
import os

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
REGEX = compile(
    r"(?:^|\D)?(("+ r"(?:[1-9]|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"\." + r"(?:\d|[1-9]\d|1\d{2}|2[0-4]\d|25[0-5])"
    + r"):" + (r"(?:\d|[1-9]\d{1,3}|[1-5]\d{4}|6[0-4]\d{3}"
    + r"|65[0-4]\d{2}|655[0-2]\d|6553[0-5])")
    + r")(?:\D|$)"
)

class Telegram:
    def __init__(self, channel: str, post: int, target_views: int = None) -> None:
        self.tasks = 225
        self.channel = channel
        self.post = post
        self.target_views = target_views
        self.cookie_error = 0
        self.sucsess_sent = 0
        self.failled_sent = 0
        self.token_error  = 0
        self.proxy_error  = 0

    async def request(self, proxy: str, proxy_type: str):
        if proxy_type == 'socks4': connector = ProxyConnector.from_url(f'socks4://{proxy}')
        elif proxy_type == 'socks5': connector = ProxyConnector.from_url(f'socks5://{proxy}')
        elif proxy_type == 'https': connector = ProxyConnector.from_url(f'https://{proxy}')
        else: connector = ProxyConnector.from_url(f'http://{proxy}')
        
        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar, connector=connector) as session:
            try:
                async with session.get(
                    f'https://t.me/{self.channel}/{self.post}?embed=1&mode=tme', 
                    headers={'referer': f'https://t.me/{self.channel}/{self.post}', 'user-agent': user_agent},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as embed_response:
                    if jar.filter_cookies(embed_response.url).get('stel_ssid'):
                        views_token = search('data-view="([^"]+)"', await embed_response.text())
                        if views_token:
                            views_response = await session.post(
                                'https://t.me/v/?views=' + views_token.group(1), 
                                headers={'referer': f'https://t.me/{self.channel}/{self.post}?embed=1&mode=tme',
                                         'user-agent': user_agent, 'x-requested-with': 'XMLHttpRequest'},
                                timeout=aiohttp.ClientTimeout(total=5)
                            )
                            if await views_response.text() == "true" and views_response.status == 200:
                                self.sucsess_sent += 1
                                if self.target_views and self.sucsess_sent >= self.target_views:
                                    print(f"\n✅ Reached {self.target_views} views. Stopping.")
                                    os._exit(0)
                            else:
                                self.failled_sent += 1
                        else:
                            self.token_error += 1
                    else:
                        self.cookie_error += 1
            except:
                self.proxy_error += 1
            finally:
                jar.clear()

    def run_proxies_tasks(self, proxies: list, proxy_type: str):
        async def inner(proxies_list):
            await asyncio.wait([asyncio.create_task(self.request(proxy, proxy_type)) for proxy in proxies_list])
        chunks = [proxies[i:i+self.tasks] for i in range(0, len(proxies), self.tasks)]
        for chunk in chunks:
            asyncio.run(inner(chunk))

    def run_auto_tasks(self, proxies_list):
        async def inner(proxies_tuples):
            await asyncio.wait([asyncio.create_task(self.request(proxy, ptype)) for ptype, proxy in proxies_tuples])
        chunks = [proxies_list[i:i+self.tasks] for i in range(0, len(proxies_list), self.tasks)]
        for chunk in chunks:
            asyncio.run(inner(chunk))

    async def run_rotated_task(self, proxy, proxy_type):
        while True:
            await asyncio.wait([asyncio.create_task(self.request(proxy, proxy_type)) for _ in range(self.tasks)])

    def cli(self):
        logo = '''
        *** Telegram Auto Views 2024 ***
          ** github.com/javadbazokar **
               * @javadbazokar *
        '''
        while not self.sucsess_sent:
            print(logo)
            print('\n        [ Waiting for proxies and sending views... ]\n')
            sleep(1)

        while True:
            print(logo)
            print(f'''
        DATA: 
        @{self.channel}/{self.post}
        Sent: {self.sucsess_sent}
        Fail: {self.failled_sent}

        ERRORS:
        Proxy Error:  {self.proxy_error}
        Token Error:  {self.token_error}
        Cookie Error: {self.cookie_error}
            ''')
            sleep(1)

class Auto:
    def __init__(self):
        self.proxies = []
        # Look for .txt files in the CURRENT DIRECTORY (not ProxyLink folder)
        self.http_sources = self.load_urls_from_file("http.txt")
        self.socks4_sources = self.load_urls_from_file("socks4.txt")
        self.socks5_sources = self.load_urls_from_file("socks5.txt")
        
        if not self.http_sources and not self.socks4_sources and not self.socks5_sources:
            print("[ERROR] No proxy source URLs found. Please create http.txt, socks4.txt, socks5.txt")
            print("Each file should contain one URL per line pointing to a raw proxy list.")
            exit(1)
        print("[*] Scraping proxies from sources...")
        asyncio.run(self.scrape_all())
        print(f"[✓] Found {len(self.proxies)} proxies. Starting views...")

    def load_urls_from_file(self, filename):
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return [line.strip() for line in f if line.strip()]
        return []

    async def scrape_sources(self, urls, proxy_type):
        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, headers={'user-agent': user_agent}, timeout=15) as resp:
                        text = await resp.text()
                        for match in REGEX.finditer(text):
                            proxy = match.group(1)
                            self.proxies.append((proxy_type, proxy))
                except Exception:
                    pass  # silently ignore failed sources

    async def scrape_all(self):
        tasks = []
        if self.http_sources:
            tasks.append(self.scrape_sources(self.http_sources, 'http'))
        if self.socks4_sources:
            tasks.append(self.scrape_sources(self.socks4_sources, 'socks4'))
        if self.socks5_sources:
            tasks.append(self.scrape_sources(self.socks5_sources, 'socks5'))
        await asyncio.gather(*tasks)

# ---------- Main ----------
parser = ArgumentParser()
parser.add_argument('-c', '--channel', required=True, help='Channel username')
parser.add_argument('-pt', '--post', required=True, type=int, help='Post number')
parser.add_argument('-m', '--mode', required=True, choices=['auto', 'l', 'r'], help='Mode: auto (scrape), l (list from file), r (single rotating)')
parser.add_argument('-t', '--type', choices=['http', 'https', 'socks4', 'socks5'], help='Proxy type for mode l or r')
parser.add_argument('-p', '--proxy', help='For mode l: path to proxy file (one IP:PORT per line). For mode r: single proxy string')
parser.add_argument('-a', '--amount', type=int, help='Stop after this many successful views')
args = parser.parse_args()

api = Telegram(args.channel, args.post, args.amount)
Thread(target=api.cli, daemon=True).start()

if args.mode == 'l':
    if not args.proxy or not args.type:
        print("Error: mode 'l' requires -p (proxy file) and -t (proxy type)")
        exit(1)
    with open(args.proxy, 'r') as f:
        proxies = [line.strip() for line in f if line.strip()]
    print(f"[*] Loaded {len(proxies)} proxies from {args.proxy}")
    api.run_proxies_tasks(proxies, args.type)

elif args.mode == 'r':
    if not args.proxy or not args.type:
        print("Error: mode 'r' requires -p (proxy string) and -t (proxy type)")
        exit(1)
    asyncio.run(api.run_rotated_task(args.proxy, args.type))

else:  # auto mode
    scraper = Auto()
    if not scraper.proxies:
        print("[ERROR] No proxies found from any source. Exiting.")
        exit(1)
    api.run_auto_tasks(scraper.proxies)
