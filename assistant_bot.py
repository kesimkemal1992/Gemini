"""
Squad 4x Assistant Bot – Answers questions addressed to the channel owner
- Listens for messages that mention @AdminUsername or reply to Admin ID
- Shows typing animation, then replies via Gemini
- Never reveals "Gemini", only "Squad 4x Assistant"
"""

import os
import asyncio
import logging
import re

from telethon import TelegramClient, events
from telethon.tl.types import SendMessageTypingAction
import google.generativeai as genai

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ========== ENVIRONMENT VARIABLES ==========
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = int(os.environ["GROUP_ID"])               # The group where bot listens
ADMIN_ID = int(os.environ["ADMIN_ID"])               # Channel owner's user ID
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").lstrip("@")  # e.g., "Squad4xAdmin"
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Optional: keywords that indicate a question (if not mention/reply)
QUESTION_KEYWORDS = ["what", "how", "why", "when", "where", "who", "can you", "please explain", "tell me", "ምን", "እንዴት", "ለምን", "መቼ", "እባክህ"]

# ========== GEMINI SETUP ==========
# Support multiple keys (comma-separated) for rotation
_keys = [k.strip() for k in GEMINI_API_KEY.split(",") if k.strip()]
_current_key_index = 0
_quota_exhausted = False

def get_gemini_model():
    genai.configure(api_key=_keys[_current_key_index])
    return genai.GenerativeModel("gemini-2.0-flash")

def rotate_key():
    global _current_key_index, _quota_exhausted
    next_idx = (_current_key_index + 1) % len(_keys)
    if next_idx == 0 and len(_keys) == 1:
        _quota_exhausted = True
        return False
    _current_key_index = next_idx
    _quota_exhausted = False
    log.info("🔄 Switched to Gemini key #%s", _current_key_index+1)
    return True

# ========== TELEGRAM CLIENT ==========
bot = TelegramClient("assistant_bot", API_ID, API_HASH)

# ========== HELPER: ASK GEMINI ==========
async def ask_gemini(question: str) -> str:
    """Send question to Gemini, return answer or error message."""
    global _quota_exhausted
    if _quota_exhausted:
        return "I'm sorry, the assistant service is temporarily unavailable. Please try again later."

    tried = 0
    total = len(_keys)
    while True:
        try:
            model = get_gemini_model()
            response = await asyncio.to_thread(model.generate_content, question)
            answer = response.text.strip()
            return answer
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "RESOURCE_EXHAUSTED" in err:
                tried += 1
                if not rotate_key():
                    _quota_exhausted = True
                    return "Assistant offline. Please contact group admin."
                continue
            log.warning(f"Gemini error: {e}")
            return "Sorry, I encountered an error while processing your request."

# ========== GROUP MESSAGE HANDLER ==========
@bot.on(events.NewMessage(chats=GROUP_ID))
async def handler(event):
    # Ignore messages from the bot itself
    if event.out:
        return

    sender = await event.get_sender()
    if sender is None:
        return

    # Ignore messages from the admin himself (no self‑reply)
    if sender.id == ADMIN_ID:
        return

    text = event.raw_text or ""
    if not text:
        return

    # 1. Check if message is a reply to admin
    is_reply_to_admin = False
    if event.is_reply:
        try:
            reply_msg = await event.get_reply_message()
            if reply_msg and reply_msg.sender_id == ADMIN_ID:
                is_reply_to_admin = True
        except Exception:
            pass

    # 2. Check if message mentions admin's username
    mentions_admin = ADMIN_USERNAME and f"@{ADMIN_USERNAME}" in text

    # 3. Check for keywords like "admin", "owner" (common in groups)
    admin_keywords = re.search(r'\b(admin|owner|ሰላጤ|ባለቤት)\b', text, re.IGNORECASE)

    # 4. Optional: if no direct address but contains question keywords and is long enough
    has_question_keywords = any(kw in text.lower() for kw in QUESTION_KEYWORDS)
    is_long_enough = len(text.split()) >= 4

    # Decide: respond only if clearly addressed to admin
    is_addressed = is_reply_to_admin or mentions_admin or admin_keywords
    # If you want to also catch questions that might be intended for admin but not directly addressed,
    # uncomment the line below (be careful: may cause false positives)
    # if not is_addressed and has_question_keywords and is_long_enough:
    #     is_addressed = True

    if not is_addressed:
        return

    log.info(f"📨 Question for admin from {sender.first_name} (@{sender.username or 'no username'}): {text[:100]}")

    # Show typing animation
    async with bot.action(event.chat_id, SendMessageTypingAction()):
        await asyncio.sleep(2)   # Simulate thinking/typing
        answer = await ask_gemini(text)

    # Format answer professionally
    reply_text = f"🤖 *Squad 4x Assistant*:\n\n{answer}"

    # Send the reply
    await event.reply(reply_text, parse_mode="markdown")

    log.info(f"✅ Replied to question from {sender.id}")

# ========== MAIN ==========
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    log.info(f"🤖 Assistant Bot started: @{me.username}")
    log.info(f"Listening to group ID: {GROUP_ID}")
    log.info(f"Admin ID: {ADMIN_ID} | Admin username: @{ADMIN_USERNAME}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
