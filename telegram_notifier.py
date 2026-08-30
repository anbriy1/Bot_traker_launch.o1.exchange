from __future__ import annotations

import html
import logging
import threading

import requests

from config import Settings
from token_parser import format_duration, format_growth, format_usd, growth_percent

log = logging.getLogger("o1-launch-alerts")


class TelegramNotifier:
    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._lock = threading.Lock()

    def send_test_message(self) -> None:
        message = "o1 Launch bot connected and working."
        self._post(self.settings.telegram_chat_id, message)
        if self.settings.telegram_growth_chat_id != self.settings.telegram_chat_id:
            self._post(self.settings.telegram_growth_chat_id, message)

    def send_new_token(
        self,
        *,
        name: str,
        symbol: str,
        market_cap: float | None,
        address: str,
        link: str,
        launched: str,
    ) -> None:
        symbol_line = f"\n💎 Symbol: {html.escape(symbol)}" if symbol else ""
        message = (
            "🚀 New token on o1 Launchpad\n"
            f"🪙 Name: <b>{html.escape(name)}</b>"
            f"{symbol_line}\n"
            f"💰 MC: {format_usd(market_cap)}\n"
            f"⏱ Launched: {html.escape(launched)}\n\n"
            f"CA:\n<code>{html.escape(address)}</code>\n"
            f"{html.escape(link)}"
        )
        self._post(self.settings.telegram_chat_id, message)
        log.info("[TELEGRAM] New token alert sent: %s", address)

    def send_growth_alert(
        self,
        *,
        name: str,
        symbol: str,
        initial_mc: float | None,
        current_mc: float | None,
        address: str,
        link: str,
        seconds_to_threshold: float,
        threshold: float,
    ) -> None:
        percent = growth_percent(initial_mc, current_mc)
        symbol_line = f"\n💎 {html.escape(symbol)}" if symbol else ""
        threshold_label = format_usd(threshold).replace("$", "")
        message = (
            "🚀 TOKEN GREW\n"
            f"🪙 {html.escape(name)}"
            f"{symbol_line}\n\n"
            f"💰 Initial MC: {format_usd(initial_mc)}\n"
            f"💰 Current MC: {format_usd(current_mc)}\n\n"
            f"📈 Growth: {format_growth(percent)}\n\n"
            f"⏱ Time to ${threshold_label}: {format_duration(seconds_to_threshold)}\n\n"
            f"CA:\n<code>{html.escape(address)}</code>\n"
            f"{html.escape(link)}"
        )
        self._post(self.settings.telegram_growth_chat_id, message)
        log.info("[TELEGRAM] Growth alert sent: %s", address)

    def _post(self, chat_id: str, text: str) -> None:
        with self._lock:
            response = self.session.post(
                f"{self.settings.telegram_api_base}/bot{self.settings.telegram_token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=(10, 60),
            )
        if not response.ok:
            try:
                details = response.json().get("description", response.text)
            except ValueError:
                details = response.text
            raise requests.HTTPError(f"{response.status_code}: {details}", response=response)
