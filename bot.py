from __future__ import annotations

import logging
import threading
import time

import requests

from config import load_settings, require_config
from o1_client import O1ApiError, O1Client
from repository import TokenRepository
from scanner import Scanner
from telegram_notifier import TelegramNotifier
from tracker import Tracker

settings = load_settings()

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("o1-launch-alerts")


def scanner_loop(scanner: Scanner, client: O1Client, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            tokens = client.fetch_tokens()
            scanner.process_list(tokens)
        except (O1ApiError, requests.RequestException, ValueError, OSError) as exc:
            log.warning("[SCANNER] o1 polling failed: %s", exc)
        stop.wait(settings.poll_seconds)


def tracker_loop(tracker: Tracker, client: O1Client, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            listed = []
            try:
                listed = client.fetch_tokens()
            except (O1ApiError, requests.RequestException, ValueError) as exc:
                log.warning("[TRACKER] list refresh failed: %s", exc)
            tracker.run_once(listed)
        except (O1ApiError, requests.RequestException, ValueError, OSError) as exc:
            log.warning("[TRACKER] cycle failed: %s", exc)
        stop.wait(settings.track_interval_seconds)


def main() -> None:
    require_config(settings)
    repo = TokenRepository(settings.database_path)
    imported = repo.migrate_seen_json(settings.state_file)
    if imported:
        log.info("[SCANNER] Migrated %s ids from %s", imported, settings.state_file)
    client = O1Client(settings.api_url, settings.api_key, settings.chain_id, settings.list_limit)
    notifier = TelegramNotifier(settings, client.session)
    scanner = Scanner(settings, repo, notifier)
    tracker = Tracker(settings, repo, client, notifier)

    log.info("Watching %s every %ss; track every %ss", settings.api_url, settings.poll_seconds, settings.track_interval_seconds)
    if settings.telegram_growth_chat_id != settings.telegram_chat_id:
        log.info("NEW alerts -> chat %s; GROWTH alerts -> chat %s", settings.telegram_chat_id, settings.telegram_growth_chat_id)
    else:
        log.warning("TELEGRAM_GROWTH_CHAT_ID is unset; growth alerts use TELEGRAM_CHAT_ID")

    if settings.test_message_on_start:
        try:
            notifier.send_test_message()
            log.info("Telegram test message sent")
        except requests.RequestException as exc:
            log.error("Telegram test failed: %s", exc)

    stop = threading.Event()
    workers = [
        threading.Thread(target=scanner_loop, args=(scanner, client, stop), name="scanner", daemon=True),
        threading.Thread(target=tracker_loop, args=(tracker, client, stop), name="tracker", daemon=True),
    ]
    for worker in workers:
        worker.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down")
        stop.set()
        for worker in workers:
            worker.join(timeout=5)
        repo.close()


if __name__ == "__main__":
    main()
