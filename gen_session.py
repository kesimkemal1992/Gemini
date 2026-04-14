"""
Run this script LOCALLY (on your PC, not Railway) to generate
a Telethon StringSession for each Telegram account.

Usage:
    pip install telethon
    python gen_session.py

Paste the printed string into /addaccount on your master bot.
"""

import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = int(input("Enter your API_ID: ").strip())
API_HASH = input("Enter your API_HASH: ").strip()
PHONE    = input("Enter the phone number (e.g. +251912345678): ").strip()


async def main():
    async with TelegramClient(StringSession(), API_ID, API_HASH) as client:
        await client.start(phone=PHONE)
        print("\n" + "=" * 60)
        print("STRING SESSION (copy this entire string):")
        print(client.session.save())
        print("=" * 60 + "\n")
        print("Use it with: /addaccount label|<SESSION>|phone")


asyncio.run(main())
