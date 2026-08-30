from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def token_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("tokens", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("API response does not contain a token list")


def token_body(token: dict[str, Any]) -> dict[str, Any]:
    nested = token.get("token")
    return nested if isinstance(nested, dict) else token


def token_id(token: dict[str, Any]) -> str:
    token_data = token_body(token)
    for key in ("id", "address", "contractAddress", "tokenAddress", "slug"):
        value = token_data.get(key)
        if value:
            text = str(value)
            return text.lower() if ADDRESS_RE.match(text) else text
    return json.dumps(token, sort_keys=True)


def is_contract_address(value: str) -> bool:
    return bool(ADDRESS_RE.match(value))


def token_name(token: dict[str, Any]) -> str:
    token_data = token_body(token)
    return str(token_data.get("name") or "New token")


def token_symbol(token: dict[str, Any]) -> str:
    token_data = token_body(token)
    symbol = token_data.get("symbol")
    return str(symbol) if symbol else ""


def token_display_name(token: dict[str, Any]) -> str:
    name = token_name(token)
    symbol = token_symbol(token)
    return f"{name} ({symbol})" if symbol and symbol not in name else name


def token_link(token: dict[str, Any]) -> str:
    for key in ("url", "link", "tokenUrl"):
        if token.get(key):
            return str(token[key])
    token_data = token_body(token)
    identifier = (
        token_data.get("address")
        or token_data.get("contractAddress")
        or token_data.get("slug")
        or token_id(token)
    )
    return f"https://launch.o1.exchange/token/{identifier}"


def _as_float(value: Any) -> float | None:
    if value is None or value is False:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def market_cap_usd(token: dict[str, Any]) -> float | None:
    market_data = token.get("market_data")
    if not isinstance(market_data, dict):
        market_data = token.get("market")
    if not isinstance(market_data, dict):
        return None
    market_cap = market_data.get("market_cap")
    if isinstance(market_cap, dict):
        return _as_float(market_cap.get("usd"))
    return _as_float(market_cap)


def launched_at(token: dict[str, Any]) -> datetime | None:
    launch = token.get("launch")
    raw = launch.get("created_at") if isinstance(launch, dict) else None
    if not raw:
        return None
    try:
        text = str(raw).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def format_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1000:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def growth_percent(initial_mc: float | None, current_mc: float | None) -> float | None:
    if initial_mc is None or current_mc is None or initial_mc <= 0:
        return None
    return (current_mc - initial_mc) / initial_mc * 100


def format_growth(percent: float | None) -> str:
    if percent is None:
        return "n/a"
    sign = "+" if percent >= 0 else ""
    return f"{sign}{percent:.2f}%"


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
