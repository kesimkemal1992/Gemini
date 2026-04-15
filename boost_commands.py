"""
boost_commands.py
─────────────────
Drop-in command handlers for your existing python-telegram-bot bot.
Adds /boost and /boostcheck commands.

Usage in your main bot file:
    from boost_commands import register_boost_handlers
    register_boost_handlers(application)
"""

import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from view_booster import boost_views, scrape_proxies

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ADMIN CHECK  ← put your Telegram user IDs here
# ─────────────────────────────────────────────
ADMIN_IDS = []  # e.g. [123456789]  — fill with your Telegram user ID


def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True  # if empty, allow everyone (for testing)
    return user_id in ADMIN_IDS


# ─────────────────────────────────────────────
# /boost command
# Usage: /boost @Squad_4xx 42 200
#   channel  = @Squad_4xx   (your channel)
#   post_id  = 42            (post number)
#   views    = 200           (how many views, default 100)
# ─────────────────────────────────────────────
async def boost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Admin only command.")
        return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "📋 *Usage:*\n"
            "`/boost <channel> <post_id> [views] [proxy_type]`\n\n"
            "*Examples:*\n"
            "`/boost @Squad_4xx 42 200`\n"
            "`/boost Squad_4xx 42 500 socks5`\n\n"
            "_proxy\\_type: http | socks4 | socks5 (default: http)_",
            parse_mode="Markdown",
        )
        return

    channel = args[0].lstrip("@")
    try:
        post_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Post ID must be a number.")
        return

    target_views = 100
    proxy_type = "http"
    if len(args) >= 3:
        try:
            target_views = min(int(args[2]), 2000)  # cap at 2000 per run
        except ValueError:
            pass
    if len(args) >= 4 and args[3] in ("http", "socks4", "socks5"):
        proxy_type = args[3]

    # Send initial status message
    status_msg = await update.message.reply_text(
        f"🔄 *Boosting post* `t.me/{channel}/{post_id}`\n"
        f"🎯 Target: `{target_views}` views\n"
        f"🌐 Proxy type: `{proxy_type}`\n\n"
        f"⏳ Scraping proxies...",
        parse_mode="Markdown",
    )

    # Track active tasks so we can cancel
    task_key = f"boost_{user.id}"
    if task_key in context.bot_data:
        await update.message.reply_text("⚠️ A boost is already running. Use /stopboost to cancel it.")
        return

    # Progress callback
    async def on_progress(sent, total, failed, status="running"):
        icons = {"scraping": "🌐", "running": "📡", "done": "✅"}
        icon = icons.get(status, "📡")
        pct = int((sent / total) * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)

        text = (
            f"{icon} *Boosting* `t.me/{channel}/{post_id}`\n\n"
            f"`[{bar}]` {pct}%\n"
            f"✅ Sent: `{sent}`\n"
            f"❌ Failed: `{failed}`\n"
            f"🎯 Target: `{total}`"
        )
        if status == "done":
            text += f"\n\n🏁 *Done!* {sent}/{total} views sent."

        try:
            await status_msg.edit_text(text, parse_mode="Markdown")
        except Exception:
            pass

    # Run boost in background task
    async def run_boost():
        try:
            result = await boost_views(
                channel=channel,
                post_id=post_id,
                target_views=target_views,
                proxy_type=proxy_type,
                concurrency=50,
                progress_callback=on_progress,
            )
            context.bot_data.pop(task_key, None)

            if "error" in result:
                await status_msg.edit_text(
                    f"❌ *Boost failed:* {result['error']}",
                    parse_mode="Markdown",
                )
                return

            # Final summary
            success_rate = int((result["sent"] / max(result["total_attempted"], 1)) * 100)
            await status_msg.edit_text(
                f"✅ *Boost Complete!*\n\n"
                f"📌 Post: `t.me/{channel}/{post_id}`\n"
                f"👁 Views sent: `{result['sent']}`\n"
                f"❌ Failed: `{result['failed']}`\n"
                f"📊 Success rate: `{success_rate}%`\n"
                f"🌐 Proxies used: `{result['proxies_used']}`",
                parse_mode="Markdown",
            )
        except asyncio.CancelledError:
            context.bot_data.pop(task_key, None)
            await status_msg.edit_text("⛔ Boost was cancelled.")
        except Exception as e:
            context.bot_data.pop(task_key, None)
            logger.error(f"Boost error: {e}")
            await status_msg.edit_text(f"❌ Error: {e}")

    task = asyncio.create_task(run_boost())
    context.bot_data[task_key] = task


# ─────────────────────────────────────────────
# /stopboost — cancel a running boost
# ─────────────────────────────────────────────
async def stop_boost_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    task_key = f"boost_{user.id}"
    task = context.bot_data.get(task_key)
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("⛔ Boost cancelled.")
    else:
        await update.message.reply_text("ℹ️ No active boost to stop.")


# ─────────────────────────────────────────────
# /boostlatest — boost the latest post automatically
# (requires your channel username set in BOT_CHANNEL env var)
# ─────────────────────────────────────────────
async def boost_latest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import os
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("⛔ Admin only.")
        return

    channel = os.getenv("BOT_CHANNEL", "Squad_4xx").lstrip("@")
    args = context.args

    views = 200
    if args:
        try:
            views = min(int(args[0]), 2000)
        except ValueError:
            pass

    # Get latest post ID from the channel
    try:
        chat = await context.bot.get_chat(f"@{channel}")
        # Telegram doesn't expose latest post ID via bot API directly
        # We ask the user to confirm or provide it
        keyboard = [
            [InlineKeyboardButton("📋 Provide post ID manually", callback_data="boost_manual")],
        ]
        await update.message.reply_text(
            f"📡 Channel: `@{channel}`\n\n"
            f"⚠️ Telegram Bot API doesn't expose the latest post ID directly.\n"
            f"Use `/boost @{channel} <post_id> {views}` with the post number.\n\n"
            f"_Tip: Copy the post link — the last number is the post ID._",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────
# /proxies — test & show proxy count
# ─────────────────────────────────────────────
async def proxies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Admin only.")
        return

    msg = await update.message.reply_text("🌐 Scraping proxies... please wait.")
    try:
        http = await scrape_proxies("http")
        socks4 = await scrape_proxies("socks4")
        socks5 = await scrape_proxies("socks5")
        await msg.edit_text(
            f"✅ *Proxy Pool Ready*\n\n"
            f"🔵 HTTP: `{len(http)}` proxies\n"
            f"🟠 SOCKS4: `{len(socks4)}` proxies\n"
            f"🟣 SOCKS5: `{len(socks5)}` proxies\n\n"
            f"_Use /boost to start boosting_",
            parse_mode="Markdown",
        )
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


# ─────────────────────────────────────────────
# REGISTER ALL HANDLERS
# ─────────────────────────────────────────────
def register_boost_handlers(application: Application):
    """
    Call this in your main bot file:
        from boost_commands import register_boost_handlers
        register_boost_handlers(application)
    """
    application.add_handler(CommandHandler("boost", boost_command))
    application.add_handler(CommandHandler("stopboost", stop_boost_command))
    application.add_handler(CommandHandler("boostlatest", boost_latest_command))
    application.add_handler(CommandHandler("proxies", proxies_command))
    logger.info("✅ Boost handlers registered")
