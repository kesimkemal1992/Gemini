"""
Telegram Task Worker Bot — Single File
=======================================
Master bot that manages multiple Telegram client accounts and
executes tasks (join channel, start bot) across all of them.

Deploy on Railway.app with PostgreSQL.
"""

import asyncio
import logging
import os
import re
import random
from urllib.parse import urlparse, parse_qs
from dataclasses import dataclass, field
from typing import Optional

import asyncpg
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import StartBotRequest

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES  (set these on Railway)
# ─────────────────────────────────────────────────────────────────────────────
BOT_TOKEN    = os.environ["MASTER_BOT_TOKEN"]        # Master bot token from @BotFather
ADMIN_ID     = int(os.environ["ADMIN_TELEGRAM_ID"])  # Your personal Telegram user ID
TG_API_ID    = int(os.environ["TG_API_ID"])          # From my.telegram.org
TG_API_HASH  = os.environ["TG_API_HASH"]             # From my.telegram.org
DATABASE_URL = os.environ["DATABASE_URL"]            # PostgreSQL URL (auto-set by Railway)

# ─────────────────────────────────────────────────────────────────────────────
# IN-MEMORY TASK STATE  (tracks questionnaire progress per admin)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PendingTask:
    link:        str
    task_type:   Optional[str] = None   # 'channel' | 'bot'
    open_when:   Optional[str] = None   # 'immediate' | 'after_join'
    username:    Optional[str] = None   # extracted from link
    start_param: Optional[str] = None   # referral / start param

# Keyed by Telegram user_id (only the admin uses this)
pending: dict[int, PendingTask] = {}

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE  (asyncpg — PostgreSQL)
# ─────────────────────────────────────────────────────────────────────────────
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return _pool


async def init_db():
    """Create tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id          SERIAL PRIMARY KEY,
                label       TEXT NOT NULL UNIQUE,
                session_str TEXT NOT NULL,
                phone       TEXT,
                proxy_host  TEXT,
                proxy_port  INTEGER,
                proxy_type  TEXT DEFAULT 'SOCKS5',
                proxy_user  TEXT,
                proxy_pass  TEXT,
                active      BOOLEAN DEFAULT TRUE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS task_log (
                id          SERIAL PRIMARY KEY,
                task_type   TEXT NOT NULL,
                target_link TEXT NOT NULL,
                account_id  INTEGER REFERENCES accounts(id),
                status      TEXT,
                detail      TEXT,
                executed_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
    log.info("[DB] Tables ready.")


async def fetch_active_accounts() -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM accounts WHERE active = TRUE ORDER BY id"
        )


async def add_account(label, session_str, phone=None,
                      proxy_host=None, proxy_port=None,
                      proxy_type="SOCKS5", proxy_user=None, proxy_pass=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO accounts
                (label, session_str, phone, proxy_host, proxy_port,
                 proxy_type, proxy_user, proxy_pass)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (label) DO UPDATE
            SET session_str=$2, phone=$3, proxy_host=$4, proxy_port=$5,
                proxy_type=$6, proxy_user=$7, proxy_pass=$8
        """, label, session_str, phone,
             proxy_host, proxy_port, proxy_type, proxy_user, proxy_pass)


async def delete_account(label: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM accounts WHERE label = $1", label
        )
        return result == "DELETE 1"


async def log_task(task_type, target_link, account_id, status, detail=None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO task_log
                (task_type, target_link, account_id, status, detail)
            VALUES ($1,$2,$3,$4,$5)
        """, task_type, target_link, account_id, status, detail)

# ─────────────────────────────────────────────────────────────────────────────
# TELETHON CLIENT  (one per account, created on-demand)
# ─────────────────────────────────────────────────────────────────────────────

def _build_proxy(record):
    """Convert a DB account record into a Telethon-compatible proxy tuple."""
    if not record["proxy_host"]:
        return None
    try:
        import socks
        type_map = {
            "SOCKS5": socks.SOCKS5,
            "SOCKS4": socks.SOCKS4,
            "HTTP":   socks.HTTP,
        }
        return (
            type_map.get(record["proxy_type"].upper(), socks.SOCKS5),
            record["proxy_host"],
            record["proxy_port"],
            True,                       # rdns — resolve DNS through proxy
            record["proxy_user"] or None,
            record["proxy_pass"] or None,
        )
    except ImportError:
        log.warning("PySocks not installed — proxy skipped for %s", record["label"])
        return None


async def execute_task_on_account(record, task_type: str,
                                   target: str, start_param: str = None):
    """
    Connect a Telethon client for one account and execute the task.
    Returns (status, detail).
    """
    client = None
    try:
        proxy = _build_proxy(record)
        client = TelegramClient(
            StringSession(record["session_str"]),
            TG_API_ID,
            TG_API_HASH,
            proxy=proxy,
        )
        await client.connect()

        if not await client.is_user_authorized():
            return "error", "Session not authorized — re-add this account"

        if task_type == "channel":
            await client(JoinChannelRequest(target))
            return "ok", f"Joined {target}"

        elif task_type == "bot":
            entity = await client.get_entity(target)
            await client(StartBotRequest(
                bot=entity,
                peer=entity,
                start_param=start_param or "",
            ))
            return "ok", f"Started @{target} param='{start_param or ''}'"

        else:
            return "skipped", f"Unknown task_type: {task_type}"

    except Exception as exc:
        return "error", str(exc)

    finally:
        if client and client.is_connected():
            await client.disconnect()


async def run_task_on_all_accounts(task_type: str, target: str,
                                    start_param: str = None,
                                    delay_min: float = 3.0,
                                    delay_max: float = 9.0) -> list[dict]:
    """
    Run a task across ALL active accounts with random delays between each.
    Returns a list of result dicts.
    """
    accounts = await fetch_active_accounts()
    if not accounts:
        return []

    results = []
    for i, record in enumerate(accounts):
        if i > 0:
            delay = random.uniform(delay_min, delay_max)
            log.info("[Worker] Sleeping %.1fs before next account...", delay)
            await asyncio.sleep(delay)

        log.info("[Worker] Task on account: %s", record["label"])
        status, detail = await execute_task_on_account(
            record, task_type, target, start_param
        )
        await log_task(task_type, target, record["id"], status, detail)

        results.append({
            "label":  record["label"],
            "status": status,
            "detail": detail,
        })
        log.info("[Worker]  → %s: %s", status, detail)

    return results

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def extract_link_parts(link: str) -> tuple[str, Optional[str]]:
    """
    Parse a t.me link → (username, start_param | None).
    Handles:
      https://t.me/username
      https://t.me/username?start=REF
      https://t.me/username/app?startapp=REF
    """
    m = re.match(r"https?://t\.me/([^/?#\s]+)", link)
    if not m:
        return link.lstrip("@"), None

    username = m.group(1)
    parsed   = urlparse(link)
    qs       = parse_qs(parsed.query)
    param    = (qs.get("start",    [None])[0] or
                qs.get("startapp", [None])[0])
    return username, param


def is_admin(uid: int) -> bool:
    return uid == ADMIN_ID


def format_results(results: list[dict]) -> str:
    if not results:
        return "⚠️ No accounts configured."
    ok      = sum(1 for r in results if r["status"] == "ok")
    errors  = sum(1 for r in results if r["status"] == "error")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    lines   = ["📊 *Task Results*\n"]
    for r in results:
        icon = {"ok": "✅", "error": "❌", "skipped": "⏭️"}.get(r["status"], "❔")
        lines.append(f"{icon} `{r['label']}` — {r['detail']}")
    lines.append(
        f"\n*Total:* {len(results)} | ✅ {ok} | ❌ {errors} | ⏭️ {skipped}"
    )
    return "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# BOT HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🤖 *Task Worker Bot*\n\n"
        "Send me any `t.me/...` link to begin.\n\n"
        "📋 *Commands:*\n"
        "/accounts — list stored accounts\n"
        "/addaccount — add a client account\n"
        "/removeaccount — remove an account\n"
        "/help — full usage guide",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📖 *Help & Usage*\n\n"
        "*Add an account:*\n"
        "`/addaccount label|SESSION|phone`\n"
        "_With proxy:_\n"
        "`/addaccount label|SESSION|phone|host|port|SOCKS5|user|pass`\n\n"
        "*Remove an account:*\n"
        "`/removeaccount label`\n\n"
        "*Start a task:*\n"
        "Just send a `t.me/...` link and follow the prompts.\n\n"
        "*Get a String Session:*\n"
        "Run `gen_session.py` locally (see README) and paste the output.",
        parse_mode="Markdown",
    )


async def cmd_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    accounts = await fetch_active_accounts()
    if not accounts:
        await update.message.reply_text("No accounts stored yet. Use /addaccount.")
        return
    lines = [f"📋 *Accounts ({len(accounts)})*\n"]
    for a in accounts:
        proxy = f"{a['proxy_host']}:{a['proxy_port']}" if a["proxy_host"] else "None"
        lines.append(
            f"• `{a['label']}` | {a['phone'] or 'no phone'} | proxy: {proxy}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_addaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /addaccount label|SESSION_STRING|phone[|proxy_host|proxy_port|type|user|pass]
    """
    if not is_admin(update.effective_user.id):
        return
    try:
        raw   = " ".join(ctx.args)
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 2:
            raise ValueError("Need at least label and session string.")

        label       = parts[0]
        session_str = parts[1]
        phone       = parts[2] if len(parts) > 2 else None
        proxy_host  = parts[3] if len(parts) > 3 else None
        proxy_port  = int(parts[4]) if len(parts) > 4 else None
        proxy_type  = parts[5] if len(parts) > 5 else "SOCKS5"
        proxy_user  = parts[6] if len(parts) > 6 else None
        proxy_pass  = parts[7] if len(parts) > 7 else None

        await add_account(label, session_str, phone,
                          proxy_host, proxy_port, proxy_type,
                          proxy_user, proxy_pass)
        await update.message.reply_text(
            f"✅ Account `{label}` saved.", parse_mode="Markdown"
        )
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Error: {exc}\n\n"
            "Usage: `/addaccount label|SESSION|phone|host|port|SOCKS5|user|pass`",
            parse_mode="Markdown",
        )


async def cmd_removeaccount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /removeaccount label
    """
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Usage: `/removeaccount label`", parse_mode="Markdown")
        return
    label = ctx.args[0].strip()
    removed = await delete_account(label)
    if removed:
        await update.message.reply_text(f"🗑️ Account `{label}` removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ Account `{label}` not found.", parse_mode="Markdown")


async def handle_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Receives a t.me link → starts the questionnaire.
    """
    if not is_admin(update.effective_user.id):
        return

    text = (update.message.text or "").strip()
    if "t.me/" not in text:
        return  # Not a Telegram link — ignore

    uid = update.effective_user.id
    username, start_param = extract_link_parts(text)

    # Store pending task
    pending[uid] = PendingTask(
        link=text,
        username=username,
        start_param=start_param,
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 Mini-App / Bot", callback_data="type:bot"),
            InlineKeyboardButton("📢 Channel / Group", callback_data="type:channel"),
        ]
    ])
    await update.message.reply_text(
        f"🔗 Link received: `{text}`\n\n"
        "❓ *Question 1:* What type is this task?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handles all inline keyboard button presses through the questionnaire flow.
    """
    query = update.callback_query
    await query.answer()

    uid  = query.from_user.id
    data = query.data

    if not is_admin(uid):
        return

    task = pending.get(uid)
    if not task:
        await query.edit_message_text("⚠️ Session expired. Send the link again.")
        return

    # ── Step 1: task type selected ────────────────────────────────────────────
    if data.startswith("type:"):
        task.task_type = data.split(":")[1]  # 'bot' or 'channel'

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡ Open Immediately",       callback_data="when:immediate"),
                InlineKeyboardButton("⏳ After Joining/Starting", callback_data="when:after_join"),
            ]
        ])
        label = "Mini-App / Bot" if task.task_type == "bot" else "Channel / Group"
        await query.edit_message_text(
            f"✅ Type: *{label}*\n\n"
            "❓ *Question 2:* When should the task run?",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    # ── Step 2: timing selected → show summary ────────────────────────────────
    elif data.startswith("when:"):
        task.open_when = data.split(":")[1]

        type_label = "Mini-App / Bot" if task.task_type == "bot" else "Channel / Group"
        when_label = "Immediately" if task.open_when == "immediate" else "After joining/starting"

        summary = (
            "📋 *Task Summary*\n\n"
            f"🔗 Link: `{task.link}`\n"
            f"🏷️ Type: {type_label}\n"
            f"⏱️ Timing: {when_label}\n"
        )
        if task.start_param:
            summary += f"🎯 Referral param: `{task.start_param}`\n"

        accounts = await fetch_active_accounts()
        summary += f"\n👥 Will run on *{len(accounts)} account(s)*."

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🚀 Confirm & Start Task", callback_data="confirm"),
                InlineKeyboardButton("❌ Cancel",               callback_data="cancel"),
            ]
        ])
        await query.edit_message_text(
            summary, reply_markup=keyboard, parse_mode="Markdown"
        )

    # ── Confirm → execute ─────────────────────────────────────────────────────
    elif data == "confirm":
        await query.edit_message_text(
            "⏳ Task started! Running across all accounts...\n"
            "_(This may take a few minutes)_",
            parse_mode="Markdown",
        )

        task = pending.pop(uid, None)
        if not task:
            await ctx.bot.send_message(uid, "⚠️ Task data lost. Please try again.")
            return

        results = await run_task_on_all_accounts(
            task_type=task.task_type,
            target=task.username,
            start_param=task.start_param,
        )

        summary = format_results(results)
        await ctx.bot.send_message(uid, summary, parse_mode="Markdown")

    # ── Cancel ────────────────────────────────────────────────────────────────
    elif data == "cancel":
        pending.pop(uid, None)
        await query.edit_message_text("❌ Task cancelled.")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN  —  entry point
# ─────────────────────────────────────────────────────────────────────────────

async def post_init(application: Application):
    """Runs once after the bot starts — initialises the database."""
    await init_db()
    log.info("[Bot] Database initialised.")


def main():
    log.info("[Bot] Starting Task Worker Bot...")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("accounts",      cmd_accounts))
    app.add_handler(CommandHandler("addaccount",    cmd_addaccount))
    app.add_handler(CommandHandler("removeaccount", cmd_removeaccount))

    # Link messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    # Inline keyboard callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("[Bot] Polling started.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
