# o1 Launch Telegram alerts

This bot watches o1 Launch tokens and sends Telegram notifications about:

- new tokens appearing on the launchpad
- tokens that cross a configured USD market-cap threshold

It works in the background, polls the o1 API, stores state in SQLite, and keeps tracking tokens even after a restart.

## What it does

### New token alerts
The scanner periodically fetches the token list from o1 and checks what is new.
If a token was not seen before, it is saved to the database and a message is sent to `TELEGRAM_CHAT_ID`.

### Growth alerts
The tracker keeps monitoring active tokens and checks their current market cap.
When a token reaches or exceeds `GROWTH_MC_THRESHOLD`, it sends one growth alert to `TELEGRAM_GROWTH_CHAT_ID`.
If `TELEGRAM_GROWTH_CHAT_ID` is not set, the bot falls back to `TELEGRAM_CHAT_ID`.

### Persistence
State is stored in SQLite (`DATABASE_PATH`, default `tokens.db`).
This means the bot does not lose tracking information when restarted.

Legacy `seen_tokens.json` can be migrated once on startup if it exists.

---

## Required environment variables

Copy `.env.example` to `.env` and fill in the values.

```env
O1_API_KEY=your_o1_api_key
O1_API_URL=https://api.launch.o1.exchange/v1/tokens
O1_CHAIN_ID=8453
TELEGRAM_BOT_TOKEN=123456789:your_bot_token
TELEGRAM_CHAT_ID=-1001234567890
TELEGRAM_GROWTH_CHAT_ID=-1001234567890
```

### Required for normal work
- `O1_API_KEY`
- `O1_API_URL`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### Optional but useful
```env
O1_LIST_LIMIT=50
POLL_SECONDS=30
TRACK_INTERVAL_SECONDS=10
GROWTH_MC_THRESHOLD=10000
GROWTH_CONFIRMATION_SECONDS=0
MAX_TRACKING_TIME_MINUTES=30
TRACK_MAX_CONCURRENT_DETAIL=3
DATABASE_PATH=tokens.db
INITIAL_SCAN=mark_seen
TEST_MESSAGE_ON_START=false
TELEGRAM_API_BASE=https://api.telegram.org
LOG_LEVEL=INFO
```

---

## Setup

1. Create a Python virtual environment:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. Copy the example config:

```powershell
Copy-Item .env.example .env
notepad .env
```

3. Create a Telegram bot with [@BotFather](https://t.me/BotFather).
4. Add the bot to the chats/channels you want to use:
   - `TELEGRAM_CHAT_ID` — for new token alerts
   - `TELEGRAM_GROWTH_CHAT_ID` — for growth alerts
5. Fill in the values in `.env`.
6. Start the bot:

```powershell
.\.venv\Scripts\python.exe bot.py
```

---

## Railway / deployment notes

For Railway, use the same environment variables as in `.env`.

Recommended defaults:
- `INITIAL_SCAN=mark_seen` so the first deploy does not spam old tokens
- `TELEGRAM_API_BASE=https://api.telegram.org` unless you need a proxy
- `TEST_MESSAGE_ON_START=false` unless you want a startup ping

---

## Tests

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

---

## Notes

- `GROWTH_MC_THRESHOLD` is in USD.
- `GROWTH_CONFIRMATION_SECONDS=0` means send the alert as soon as the token reaches the threshold.
- `MAX_TRACKING_TIME_MINUTES` limits how long the bot continues tracking a token without a growth event.

This project is a background monitoring bot, not a user-interactive Telegram app. It polls the API, tracks token state, and sends automated alerts.
