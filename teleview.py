import aiohttp, asyncio
from re import search, compile
from aiohttp_socks import ProxyConnector
from argparse import ArgumentParser
from os import system, name
from threading import Thread
from time import sleep

user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
REGEX = compile(r"\d{1,3}(?:\.\d{1,3}){3}(?::\d{1,5})?")

AUTO_PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/officialputuid/KangProxy/KangProxy/http/http.txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt"
]

class Telegram:
    def __init__(self, channel: str, post: int, amount: int) -> None:
        self.tasks = 100 
        self.channel = channel
        self.post = post
        self.amount = amount
        self.sucsess_sent = 0
        self.proxy_error = 0
        self.token_error = 0
        self.proxies = []

    async def scrap_all(self):
        self.proxies.clear()
        async with aiohttp.ClientSession() as session:
            tasks = []
            for url in AUTO_PROXY_SOURCES:
                tasks.append(self.fetch(session, url))
            await asyncio.gather(*tasks)

    async def fetch(self, session, url):
        try:
            async with session.get(url, headers={'user-agent': user_agent}, timeout=10) as resp:
                text = await resp.text()
                found = REGEX.findall(text)
                p_type = 'socks5' if 'socks5' in url else 'http'
                for p in found:
                    self.proxies.append((p_type, p))
        except: pass

    async def request(self, proxy: str, proxy_type: str):
        if self.sucsess_sent >= self.amount: return
        try:
            connector = ProxyConnector.from_url(f'{proxy_type}://{proxy}')
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get(
                    f'https://t.me/{self.channel}/{self.post}?embed=1&mode=tme', 
                    headers={'user-agent': user_agent},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    html = await response.text()
                    token = search(r'data-view="([^"]+)"', html)
                    if token:
                        async with session.post(
                            f'https://t.me/v/?views={token.group(1)}', 
                            headers={
                                'referer': f'https://t.me/{self.channel}/{self.post}?embed=1&mode=tme',
                                'user-agent': user_agent, 'x-requested-with': 'XMLHttpRequest'
                            }, timeout=aiohttp.ClientTimeout(total=10)
                        ) as v_resp:
                            if (await v_resp.text() == "true"): self.sucsess_sent += 1
        except: self.proxy_error += 1

    async def run_auto_tasks(self):
        while self.sucsess_sent < self.amount:
            print(f" [!] ፕሮክሲዎች እየታደሱ ነው...")
            await self.scrap_all()
            
            if not self.proxies:
                await asyncio.sleep(5); continue

            for i in range(0, len(self.proxies), self.tasks):
                if self.sucsess_sent >= self.amount: break
                batch = self.proxies[i:i+self.tasks]
                tasks_list = [self.request(p, pt) for pt, p in batch]
                await asyncio.gather(*tasks_list)
            
            await asyncio.sleep(2)
        print(f"\n [!] ተጠናቋል! ጠቅላላ: {self.sucsess_sent}")

    def cli(self):
        while self.sucsess_sent < self.amount:
            system('cls' if name=='nt' else 'clear')
            print(f"Target: @{self.channel}/{self.post}\nGoal: {self.amount}\nSuccess: {self.sucsess_sent}\nErrors: {self.proxy_error}")
            sleep(2)

if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument('-c', '--channel', required=True)
    parser.add_argument('-pt', '--post', required=True, type=int)
    parser.add_argument('-m', '--mode', default='auto')
    parser.add_argument('-a', '--amount', default=1000, type=int)
    args = parser.parse_args()

    api = Telegram(args.channel, args.post, args.amount)
    Thread(target=api.cli, daemon=True).start()
    asyncio.run(api.run_auto_tasks())
