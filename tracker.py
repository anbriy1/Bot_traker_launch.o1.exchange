from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

import requests

from config import Settings
from growth import should_send_growth, tracking_expired
from o1_client import O1ApiError, O1Client
from repository import TokenRecord, TokenRepository, utc_now
from telegram_notifier import TelegramNotifier
from token_parser import is_contract_address, market_cap_usd, token_id, token_name, token_symbol

log = logging.getLogger("o1-launch-alerts")


class Tracker:
    def __init__(
        self,
        settings: Settings,
        repo: TokenRepository,
        client: O1Client,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.client = client
        self.notifier = notifier

    def run_once(self, listed_tokens: list[dict[str, Any]] | None = None) -> None:
        listed_tokens = listed_tokens or []
        listed_by_id = {token_id(item): item for item in listed_tokens}
        checked_at = utc_now()
        remaining: list[TokenRecord] = []

        for token in self.repo.list_active():
            if tracking_expired(token, self.settings.max_tracking_time_minutes, checked_at):
                self.repo.deactivate(token.address)
                log.info("[TRACKER] Tracking stopped: %s (max time)", token.address)
                continue
            payload = listed_by_id.get(token.address)
            if payload is not None:
                self._apply_payload(token.address, payload, checked_at)
            else:
                remaining.append(token)

        if remaining:
            self._refresh_missing(remaining, checked_at)

        self._evaluate_growth()

    def _apply_payload(self, address: str, payload: dict[str, Any], checked_at: datetime) -> None:
        mc = market_cap_usd(payload)
        updated = self.repo.apply_market_cap(
            address,
            mc,
            checked_at,
            self.settings.growth_mc_threshold,
            name=token_name(payload),
            symbol=token_symbol(payload),
        )
        if updated is not None:
            log.info("[TRACKER] Updated MC: %s -> %s", address, updated.current_mc)

    def _refresh_missing(self, tokens: list[TokenRecord], checked_at: datetime) -> None:
        workers = min(self.settings.max_concurrent_detail, len(tokens))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._fetch_detail, token.address): token.address
                for token in tokens
                if is_contract_address(token.address)
            }
            for future in as_completed(futures):
                address = futures[future]
                try:
                    payload = future.result()
                except O1ApiError as exc:
                    if exc.status == 404:
                        log.warning("[TRACKER] Token missing from API: %s", address)
                        self.repo.apply_market_cap(
                            address, None, checked_at, self.settings.growth_mc_threshold
                        )
                    else:
                        log.warning("[API] Detail failed for %s: %s", address, exc)
                    continue
                if payload:
                    self._apply_payload(address, payload, checked_at)

    def _fetch_detail(self, address: str) -> dict[str, Any]:
        return self.client.fetch_token_detail(address)

    def _evaluate_growth(self) -> None:
        now = datetime.now(timezone.utc)
        for token in self.repo.list_active():
            if not should_send_growth(
                token,
                threshold=self.settings.growth_mc_threshold,
                confirmation_seconds=self.settings.growth_confirmation_seconds,
                now=now,
            ):
                continue
            if token.current_mc is not None and token.current_mc >= self.settings.growth_mc_threshold:
                log.info("[GROWTH] Threshold reached: %s mc=%s", token.address, token.current_mc)
            if not self.repo.try_claim_growth_alert(token.address):
                continue
            reached = token.threshold_reached_at or now
            first_seen = token.first_seen
            if first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            if reached.tzinfo is None:
                reached = reached.replace(tzinfo=timezone.utc)
            try:
                self.notifier.send_growth_alert(
                    name=token.name,
                    symbol=token.symbol,
                    initial_mc=token.initial_mc,
                    current_mc=token.current_mc,
                    address=token.address,
                    link=token.token_url,
                    seconds_to_threshold=(reached - first_seen).total_seconds(),
                    threshold=self.settings.growth_mc_threshold,
                )
            except requests.RequestException as exc:
                log.warning("[TELEGRAM] Growth alert failed for %s: %s", token.address, exc)
                self.repo.release_growth_lock(token.address)
                continue
            self.repo.mark_growth_sent(token.address, now)
            log.info("[TRACKER] Tracking stopped: %s (growth sent)", token.address)
