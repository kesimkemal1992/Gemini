# Telegram Task Worker Bot

Multi-account Telegram task manager. Deploys on Railway.app with PostgreSQL.

---

## Setup

### 1. Get credentials

- **BOT TOKEN** — create a bot via [@BotFather](https://t.me/BotFather)
- **ADMIN_TELEGRAM_ID** — your user ID from [@userinfobot](https://t.me/userinfobot)
- **TG_API_ID / TG_API_HASH** — from [my.telegram.org](https://my.telegram.org)

### 2. Generate String Sessions (run locally)

For each Telegram account you want to manage:

```bash
pip install telethon
python gen_session.py
```

Copy the printed session string.

### 3. Deploy to Railway

1. Push this repo to GitHub (make it **private**)
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add a **PostgreSQL** plugin (Railway auto-sets `DATABASE_URL`)
4. Add these environment variables:

| Variable             | Value                        |
|----------------------|------------------------------|
| MASTER_BOT_TOKEN     | Your bot token               |
| ADMIN_TELEGRAM_ID    | Your Telegram user ID        |
| TG_API_ID            | From my.telegram.org         |
| TG_API_HASH          | From my.telegram.org         |
| DATABASE_URL         | Auto-set by Railway Postgres |

5. Deploy — Railway will run `python main.py`

### 4. Add accounts to the bot

In your master bot chat, send:

```
/addaccount account1|SESSION_STRING_HERE|+251912345678
```

With proxy:
```
/addaccount account1|SESSION_STRING|+251912345678|proxy.host.com|1080|SOCKS5|user|pass
```

### 5. Start a task

Send any `t.me/...` link to the bot and follow the prompts.

---

## Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/help` | Full usage guide |
| `/accounts` | List all stored accounts |
| `/addaccount` | Add a client account |
| `/removeaccount` | Remove an account |

---

## File Structure

```
main.py          ← entire bot (single file)
gen_session.py   ← run locally to generate sessions
requirements.txt
Procfile
railway.json
.env.example
README.md
```
