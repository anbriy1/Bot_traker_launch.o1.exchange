import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("o1-launch-alerts")

API_KEY = os.getenv("O1_API_KEY", "").strip()
API_URL = os.getenv("O1_API_URL", "").strip()
CHAIN_ID = os.getenv("O1_CHAIN_ID", "8453").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
POLL_SECONDS = max(10, int(os.getenv("POLL_SECONDS", "30")))
STATE_FILE = Path(os.getenv("STATE_FILE", "seen_tokens.json"))


def require_config() -> None:
    missing = [
        name for name, value in {
            "O1_API_KEY": API_KEY,
            "O1_API_URL": API_URL,
            "TELEGRAM_BOT_TOKEN": TELEGRAM_TOKEN,
            "TELEGRAM_CHAT_ID": CHAT_ID,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit("Missing .env values: " + ", ".join(missing))


def load_seen() -> set[str]:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except FileNotFoundError:
        return set()
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Cannot read state file: %s", exc)
        return set()


def save_seen(seen: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(seen), ensure_ascii=True, indent=2), encoding="utf-8")


def token_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("tokens", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("API response does not contain a token list")


def token_id(token: dict[str, Any]) -> str:
    token_data = token.get("token") if isinstance(token.get("token"), dict) else token
    for key in ("id", "address", "contractAddress", "tokenAddress", "slug"):
        value = token_data.get(key)
        if value:
            return str(value)
    return json.dumps(token, sort_keys=True)


def token_name(token: dict[str, Any]) -> str:
    token_data = token.get("token") if isinstance(token.get("token"), dict) else token
    name = token_data.get("name") or token_data.get("symbol") or "New token"
    symbol = token_data.get("symbol")
    return f"{name} ({symbol})" if symbol and str(symbol) not in str(name) else str(name)


def token_link(token: dict[str, Any]) -> str:
    for key in ("url", "link", "tokenUrl"):
        if token.get(key):
            return str(token[key])
    token_data = token.get("token") if isinstance(token.get("token"), dict) else token
    identifier = token_data.get("address") or token_data.get("contractAddress") or token_data.get("slug") or token_id(token)
    return f"https://launch.o1.exchange/token/{identifier}"


def fetch_tokens(session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(
        API_URL,
        headers={"Authorization": f"Bearer {API_KEY}", "X-API-Key": API_KEY, "Accept": "application/json"},
        params={"chain_id": CHAIN_ID},
        timeout=20,
    )
    response.raise_for_status()
    return token_list(response.json())


def send_telegram(session: requests.Session, token: dict[str, Any]) -> None:
    message = f"🚀 New token on o1 Launchpad\n<b>{token_name(token)}</b>\n{token_link(token)}"
    response = session.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False},
        timeout=20,
    )
    response.raise_for_status()


def main() -> None:
    require_config()
    seen = load_seen()
    session = requests.Session()
    log.info("Watching %s every %ss", API_URL, POLL_SECONDS)

    while True:
        try:
            tokens = fetch_tokens(session)
            fresh = [token for token in tokens if token_id(token) not in seen]
            for token in reversed(fresh):
                send_telegram(session, token)
                seen.add(token_id(token))
                save_seen(seen)
                log.info("Sent %s", token_name(token))
        except (requests.RequestException, ValueError, OSError) as exc:
            log.warning("Polling failed: %s", exc)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
