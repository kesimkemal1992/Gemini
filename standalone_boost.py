"""
standalone_boost.py
────────────────────
Run the view booster WITHOUT a bot — directly from command line.
Mirrors the vwh/telegram-views CLI interface.

Usage:
    python standalone_boost.py --channel Squad_4xx --post 42 --views 500 --mode auto
    python standalone_boost.py --channel Squad_4xx --post 42 --views 200 --mode list --proxy proxies.txt
    python standalone_boost.py --channel Squad_4xx --post 42 --views 100 --mode rotate --proxy user:pass@1.2.3.4:8080
"""

import asyncio
import argparse
import sys
import logging
from view_booster import boost_views, scrape_proxies

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Telegram Post View Booster",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modes:
  auto    — Scrapes proxies automatically (no proxy file needed)
  list    — Use a text file with one proxy per line
  rotate  — Use a single rotating proxy (user:pass@host:port)

Examples:
  python standalone_boost.py --channel Squad_4xx --post 5 --views 300 --mode auto
  python standalone_boost.py --channel Squad_4xx --post 5 --views 200 --mode list --type socks5 --proxy socks5.txt
  python standalone_boost.py --channel Squad_4xx --post 5 --views 100 --mode rotate --proxy user:pass@1.2.3.4:1080
        """,
    )
    parser.add_argument("--channel", required=True, help="Channel username (e.g. Squad_4xx)")
    parser.add_argument("--post", required=True, type=int, help="Post ID number")
    parser.add_argument("--views", type=int, default=100, help="Number of views to send (default: 100)")
    parser.add_argument("--mode", required=True, choices=["auto", "list", "rotate"], help="Operation mode")
    parser.add_argument("--type", default="http", choices=["http", "socks4", "socks5"], help="Proxy type")
    parser.add_argument("--proxy", default=None, help="Proxy file path or single proxy string")
    parser.add_argument("--concurrency", type=int, default=50, help="Max concurrent requests (default: 50)")
    return parser.parse_args()


async def main():
    args = parse_args()
    channel = args.channel.lstrip("@")

    print(f"""
╔══════════════════════════════════════════╗
║     Telegram View Booster  v1.0          ║
╠══════════════════════════════════════════╣
║  Channel   : @{channel:<27}║
║  Post ID   : {args.post:<29}║
║  Target    : {args.views:<29}║
║  Mode      : {args.mode:<29}║
║  Proxy Type: {args.type:<29}║
╚══════════════════════════════════════════╝
    """)

    proxy_list = None

    # ── Mode: list (load from file)
    if args.mode == "list":
        if not args.proxy:
            print("❌ --proxy file path required for list mode")
            sys.exit(1)
        try:
            with open(args.proxy) as f:
                raw = [l.strip() for l in f if l.strip() and ":" in l]
            proxy_list = [
                f"{args.type}://{p}" if not p.startswith("http") and not p.startswith("socks") else p
                for p in raw
            ]
            print(f"✅ Loaded {len(proxy_list)} proxies from {args.proxy}")
        except FileNotFoundError:
            print(f"❌ File not found: {args.proxy}")
            sys.exit(1)

    # ── Mode: rotate (single proxy, repeated)
    elif args.mode == "rotate":
        if not args.proxy:
            print("❌ --proxy required for rotate mode (format: user:pass@host:port)")
            sys.exit(1)
        proxy = args.proxy
        if not proxy.startswith("http") and not proxy.startswith("socks"):
            proxy = f"{args.type}://{proxy}"
        proxy_list = [proxy] * args.views  # repeat same proxy
        print(f"🔄 Using rotating proxy: {proxy}")

    # ── Mode: auto (scrape proxies)
    else:
        print("🌐 Auto mode: scraping proxies from public sources...")

    # Progress display
    last_pct = [-1]

    async def progress(sent, total, failed, status="running"):
        pct = int((sent / total) * 100) if total > 0 else 0
        if pct != last_pct[0] or status == "done":
            last_pct[0] = pct
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            end = "\n" if status == "done" else "\r"
            print(
                f"  [{bar}] {pct:3d}%  ✅ {sent}  ❌ {failed}  / {total}",
                end=end,
                flush=True,
            )

    result = await boost_views(
        channel=channel,
        post_id=args.post,
        target_views=args.views,
        proxy_type=args.type,
        proxy_list=proxy_list,
        concurrency=args.concurrency,
        progress_callback=progress,
    )

    if "error" in result:
        print(f"\n❌ Error: {result['error']}")
        sys.exit(1)

    success_rate = int((result["sent"] / max(result["total_attempted"], 1)) * 100)
    print(f"""
╔══════════════════════════════════╗
║         BOOST COMPLETE           ║
╠══════════════════════════════════╣
║  Views Sent  : {result['sent']:<19}║
║  Failed      : {result['failed']:<19}║
║  Success Rate: {success_rate}%{'':<16}║
║  Proxies Used: {result['proxies_used']:<19}║
╚══════════════════════════════════╝
    """)


if __name__ == "__main__":
    asyncio.run(main())
