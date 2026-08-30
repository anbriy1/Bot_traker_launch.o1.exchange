# o1 Launch Telegram alerts

Scanner watches new o1 Launchpad tokens and sends **NEW** alerts to one Telegram chat.
Tracker then follows each token's USD market cap and sends a one-time **GROWTH** alert to a second chat when it reaches the configured threshold (default $10,000).

## Setup

1. Install Python 3.12+ from https://www.python.org/downloads/windows/ and enable **Add python.exe to PATH**.
2. Open PowerShell in this folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

3. Create a Telegram bot with [@BotFather](https://t.me/BotFather). Add it to **two** chats/channels:
   - `TELEGRAM_CHAT_ID` — new tokens
   - `TELEGRAM_GROWTH_CHAT_ID` — growth alerts ($10k)
4. Fill in `O1_API_KEY` with a newly issued key. Use `https://api.launch.o1.exchange/v1/tokens` for `O1_API_URL` and `8453` for `O1_CHAIN_ID` (Base).
5. In Railway Variables, set `INITIAL_SCAN=mark_seen` so the first deployment does not send all existing tokens. Set `TELEGRAM_API_BASE` to a reachable Telegram Bot API proxy only if Railway cannot reach `api.telegram.org`.
6. Start it:

```powershell
.\.venv\Scripts\python.exe bot.py
```

7. Tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

State is stored in SQLite (`DATABASE_PATH`, default `tokens.db`) so a restart continues tracking. Legacy `seen_tokens.json` is imported once if present.

Useful env vars: `GROWTH_MC_THRESHOLD`, `TRACK_INTERVAL_SECONDS`, `MAX_TRACKING_TIME_MINUTES`, `GROWTH_CONFIRMATION_SECONDS` (0 = send as soon as MC is at/above threshold).
