# o1 Launch Telegram alerts

## Setup

1. Install Python 3.12+ from https://www.python.org/downloads/windows/ and enable **Add python.exe to PATH**.
2. Open PowerShell in this folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

3. Create a Telegram bot with [@BotFather](https://t.me/BotFather), add it to the target chat/channel, and fill in `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. Fill in `O1_API_KEY` with a newly issued key. Use `https://api.launch.o1.exchange/v1/tokens` for `O1_API_URL` and `8453` for `O1_CHAIN_ID` (Base).
5. Start it:

```powershell
.\.venv\Scripts\python.exe bot.py
```

The bot remembers sent token IDs in `seen_tokens.json`, retries on the next poll after temporary failures, and sends the token URL returned by the API when available.
