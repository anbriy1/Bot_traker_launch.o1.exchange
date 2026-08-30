from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import requests

from config import Settings
from repository import TokenRepository, utc_now
from telegram_notifier import TelegramNotifier
from token_parser import (
    is_contract_address,
    launched_at,
    market_cap_usd,
    token_id,
    token_link,
    token_name,
    token_symbol,
)

log = logging.getLogger("o1-launch-alerts")


class Scanner:
    def __init__(
        self,
        settings: Settings,
        repo: TokenRepository,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.notifier = notifier

    def process_list(self, tokens: list[dict[str, Any]]) -> None:
        if self.repo.count() == 0 and self.settings.initial_scan == "mark_seen":
            self._mark_existing(tokens)
            return
        for token in reversed(tokens):
            self._handle_token(token)
        self._retry_failed_new_alerts(tokens)

    def _mark_existing(self, tokens: list[dict[str, Any]]) -> None:
        seen_at = utc_now()
        for token in tokens:
            address = token_id(token)
            self.repo.insert_discovered(
                address=address,
                name=token_name(token),
                symbol=token_symbol(token),
                token_url=token_link(token),
                market_cap=market_cap_usd(token),
                first_seen=seen_at,
                active=False,
                new_alert_sent=True,
            )
        log.info("[SCANNER] Initial scan complete: marked %s existing tokens", len(tokens))

    def _handle_token(self, token: dict[str, Any]) -> None:
        address = token_id(token)
        existing = self.repo.get(address)
        if existing is not None:
            return
        created = self.repo.insert_discovered(
            address=address,
            name=token_name(token),
            symbol=token_symbol(token),
            token_url=token_link(token),
            market_cap=market_cap_usd(token),
            first_seen=utc_now(),
            active=is_contract_address(address),
            new_alert_sent=False,
        )
        if not created:
            return
        log.info("[SCANNER] New token detected: %s", address)
        self._send_new(token, address)

    def _retry_failed_new_alerts(self, tokens: list[dict[str, Any]]) -> None:
        by_id = {token_id(token): token for token in tokens}
        for record in self.repo.list_pending_new_alerts():
            payload = by_id.get(record.address)
            if payload is None:
                payload = {
                    "token": {
                        "address": record.address,
                        "name": record.name,
                        "symbol": record.symbol,
                    },
                    "url": record.token_url,
                    "market_data": {"market_cap": {"usd": record.current_mc}},
                }
            self._send_new(payload, record.address)

    def _send_new(self, token: dict[str, Any], address: str) -> None:
        launched = launched_at(token)
        launched_text = "just now"
        if launched is not None:
            age = datetime.now(timezone.utc) - launched
            if age.total_seconds() > 90:
                launched_text = launched.strftime("%Y-%m-%d %H:%M UTC")
        try:
            self.notifier.send_new_token(
                name=token_name(token),
                symbol=token_symbol(token),
                market_cap=market_cap_usd(token),
                address=address,
                link=token_link(token),
                launched=launched_text,
            )
        except requests.RequestException as exc:
            log.warning("[TELEGRAM] New token alert failed for %s: %s", address, exc)
            return
        self.repo.mark_new_alert_sent(address)
