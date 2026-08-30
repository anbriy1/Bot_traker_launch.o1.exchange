from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _env_int(name: str, default: str, minimum: int | None = None) -> int:
    value = int(os.getenv(name, default))
    if minimum is not None:
        return max(minimum, value)
    return value


def _env_float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_url: str
    chain_id: str
    telegram_token: str
    telegram_chat_id: str
    telegram_growth_chat_id: str
    telegram_api_base: str
    poll_seconds: int
    track_interval_seconds: int
    growth_mc_threshold: float
    growth_confirmation_seconds: int
    max_tracking_time_minutes: int
    list_limit: int
    max_concurrent_detail: int
    state_file: Path
    database_path: Path
    initial_scan: str
    test_message_on_start: bool
    log_level: str


def load_settings() -> Settings:
    api_url = os.getenv("O1_API_URL", "").strip().rstrip("/")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    growth_chat = os.getenv("TELEGRAM_GROWTH_CHAT_ID", "").strip() or telegram_chat_id
    return Settings(
        api_key=os.getenv("O1_API_KEY", "").strip(),
        api_url=api_url,
        chain_id=os.getenv("O1_CHAIN_ID", "8453").strip(),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=telegram_chat_id,
        telegram_growth_chat_id=growth_chat,
        telegram_api_base=os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/"),
        poll_seconds=_env_int("POLL_SECONDS", "30", minimum=10),
        track_interval_seconds=_env_int("TRACK_INTERVAL_SECONDS", "10", minimum=5),
        growth_mc_threshold=_env_float("GROWTH_MC_THRESHOLD", "10000"),
        growth_confirmation_seconds=_env_int("GROWTH_CONFIRMATION_SECONDS", "0", minimum=0),
        max_tracking_time_minutes=_env_int("MAX_TRACKING_TIME_MINUTES", "30", minimum=1),
        list_limit=_env_int("O1_LIST_LIMIT", "50", minimum=1),
        max_concurrent_detail=_env_int("TRACK_MAX_CONCURRENT_DETAIL", "3", minimum=1),
        state_file=Path(os.getenv("STATE_FILE", "seen_tokens.json")),
        database_path=Path(os.getenv("DATABASE_PATH", "tokens.db")),
        initial_scan=os.getenv("INITIAL_SCAN", "mark_seen").lower(),
        test_message_on_start=_env_bool("TEST_MESSAGE_ON_START"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def require_config(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "O1_API_KEY": settings.api_key,
            "O1_API_URL": settings.api_url,
            "TELEGRAM_BOT_TOKEN": settings.telegram_token,
            "TELEGRAM_CHAT_ID": settings.telegram_chat_id,
        }.items()
        if not value
    ]
    if missing:
        raise SystemExit("Missing .env values: " + ", ".join(missing))
