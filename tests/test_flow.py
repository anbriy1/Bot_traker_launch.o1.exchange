from __future__ import annotations

import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import requests

from config import Settings
from growth import should_send_growth
from repository import TokenRecord, TokenRepository, utc_now
from scanner import Scanner
from token_parser import growth_percent as parser_growth
from tracker import Tracker

ADDRESS = "0x1111111111111111111111111111111111111111"


def settings(**overrides) -> Settings:
    values = dict(
        api_key="key",
        api_url="https://api.launch.o1.exchange/v1/tokens",
        chain_id="8453",
        telegram_token="token",
        telegram_chat_id="new-chat",
        telegram_growth_chat_id="growth-chat",
        telegram_api_base="https://api.telegram.org",
        poll_seconds=30,
        track_interval_seconds=10,
        growth_mc_threshold=10000,
        growth_confirmation_seconds=0,
        max_tracking_time_minutes=30,
        list_limit=50,
        max_concurrent_detail=2,
        state_file=Path("seen_tokens.json"),
        database_path=Path("tokens.db"),
        initial_scan="send_all",
        test_message_on_start=False,
        log_level="INFO",
    )
    values.update(overrides)
    return Settings(**values)


def sample_token(mc: float, address: str = ADDRESS) -> dict:
    return {
        "token": {"address": address, "name": "TOKEN NAME", "symbol": "SYMBOL"},
        "url": f"https://launch.o1.exchange/token/{address}",
        "market_data": {"market_cap": {"usd": mc}},
        "launch": {"created_at": "2026-08-30T19:00:00.000Z"},
    }


class FakeNotifier:
    def __init__(self) -> None:
        self.new: list[dict] = []
        self.growth: list[dict] = []
        self.fail_growth = False
        self.fail_new = False

    def send_new_token(self, **kwargs) -> None:
        if self.fail_new:
            raise requests.HTTPError("telegram new failed")
        self.new.append(kwargs)

    def send_growth_alert(self, **kwargs) -> None:
        if self.fail_growth:
            raise requests.HTTPError("telegram growth failed")
        self.growth.append(kwargs)


class FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "tokens.db"
        self.repo = TokenRepository(self.db)
        self.notifier = FakeNotifier()
        self.cfg = settings(database_path=self.db)
        self.scanner = Scanner(self.cfg, self.repo, self.notifier)
        self.client = MagicMock()
        self.tracker = Tracker(self.cfg, self.repo, self.client, self.notifier)

    def tearDown(self) -> None:
        self.repo.close()
        self.tmp.cleanup()

    def test_new_then_growth_once(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        self.assertEqual(len(self.notifier.new), 1)
        self.assertEqual(self.notifier.new[0]["address"], ADDRESS)
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.assertEqual(record.initial_mc, 2800)
        self.assertTrue(record.active)
        self.assertFalse(record.growth_alert_sent)

        self.tracker.run_once([sample_token(5000)])
        self.assertEqual(len(self.notifier.growth), 0)
        self.tracker.run_once([sample_token(9900)])
        self.assertEqual(len(self.notifier.growth), 0)
        self.tracker.run_once([sample_token(10100)])
        self.assertEqual(len(self.notifier.growth), 1)
        self.tracker.run_once([sample_token(15000)])
        self.assertEqual(len(self.notifier.growth), 1)
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.assertTrue(record.growth_alert_sent)
        self.assertFalse(record.active)
        self.assertEqual(self.notifier.growth[0]["current_mc"], 10100)

    def test_duplicate_new_is_ignored(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        self.scanner.process_list([sample_token(2800)])
        self.assertEqual(len(self.notifier.new), 1)

    def test_restart_keeps_active_and_sends_one_growth(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        self.repo.close()
        self.repo = TokenRepository(self.db)
        restored = self.repo.get(ADDRESS)
        assert restored is not None
        self.assertTrue(restored.active)
        self.assertEqual(restored.initial_mc, 2800)
        self.assertTrue(restored.new_alert_sent)
        tracker = Tracker(self.cfg, self.repo, self.client, self.notifier)
        tracker.run_once([sample_token(11000)])
        self.assertEqual(len(self.notifier.growth), 1)
        tracker.run_once([sample_token(20000)])
        self.assertEqual(len(self.notifier.growth), 1)

    def test_telegram_failure_does_not_mark_growth_sent(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        self.notifier.fail_growth = True
        self.tracker.run_once([sample_token(12000)])
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.assertFalse(record.growth_alert_sent)
        self.assertTrue(record.active)
        self.assertEqual(len(self.notifier.growth), 0)
        self.notifier.fail_growth = False
        self.tracker.run_once([sample_token(12000)])
        self.assertEqual(len(self.notifier.growth), 1)
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.assertTrue(record.growth_alert_sent)

    def test_startup_message_sent_to_both_chats(self) -> None:
        cfg = settings(database_path=self.db, telegram_chat_id="new-chat", telegram_growth_chat_id="growth-chat")

        class FakeResponse:
            ok = True
            text = "ok"

            @staticmethod
            def json():
                return {}

        class FakeSession:
            def __init__(self):
                self.calls = []

            def post(self, url: str, data: dict, timeout):
                self.calls.append({"url": url, "data": data, "timeout": timeout})
                return FakeResponse()

        session = FakeSession()
        notifier = TelegramNotifier(cfg, session=session)

        notifier.send_test_message()

        self.assertEqual(len(session.calls), 2)
        self.assertEqual([call["data"]["chat_id"] for call in session.calls], ["new-chat", "growth-chat"])
        self.assertEqual(session.calls[0]["data"]["text"], "o1 Launch bot connected and working.")

    def test_growth_claim_is_idempotent(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        hits = []

        def claim() -> None:
            hits.append(self.repo.try_claim_growth_alert(ADDRESS))

        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(1 for hit in hits if hit), 1)

    def test_confirmation_window(self) -> None:
        cfg = settings(database_path=self.db, growth_confirmation_seconds=20)
        tracker = Tracker(cfg, self.repo, self.client, self.notifier)
        self.scanner.process_list([sample_token(2800)])
        tracker.run_once([sample_token(11000)])
        self.assertEqual(len(self.notifier.growth), 0)
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.repo._conn.execute(
            "UPDATE tokens SET above_threshold_since = ? WHERE address = ?",
            ((utc_now() - timedelta(seconds=21)).isoformat(), ADDRESS),
        )
        self.repo._conn.commit()
        tracker.run_once([sample_token(11000)])
        self.assertEqual(len(self.notifier.growth), 1)

    def test_max_tracking_time_stops_without_growth(self) -> None:
        self.scanner.process_list([sample_token(2800)])
        self.repo._conn.execute(
            "UPDATE tokens SET first_seen = ? WHERE address = ?",
            ((utc_now() - timedelta(minutes=31)).isoformat(), ADDRESS),
        )
        self.repo._conn.commit()
        self.tracker.run_once([sample_token(5000)])
        record = self.repo.get(ADDRESS)
        assert record is not None
        self.assertFalse(record.active)
        self.assertFalse(record.growth_alert_sent)
        self.assertEqual(len(self.notifier.growth), 0)

    def test_growth_percent_zero_initial(self) -> None:
        self.assertIsNone(parser_growth(0, 10000))
        self.assertIsNone(parser_growth(None, 10000))
        self.assertAlmostEqual(parser_growth(2800, 10200) or 0, 264.2857, places=2)


class GrowthPureTests(unittest.TestCase):
    def test_should_send_false_below_threshold(self) -> None:
        token = TokenRecord(
            address=ADDRESS,
            name="N",
            symbol="S",
            token_url="",
            initial_mc=2800,
            current_mc=9900,
            highest_mc=9900,
            first_seen=datetime.now(timezone.utc),
            last_check=None,
            growth_alert_sent=False,
            growth_alert_sent_at=None,
            growth_alert_lock=False,
            threshold_reached_at=None,
            above_threshold_since=None,
            new_alert_sent=True,
            active=True,
        )
        self.assertFalse(should_send_growth(token, threshold=10000, confirmation_seconds=0))
        token.current_mc = 10100
        self.assertTrue(should_send_growth(token, threshold=10000, confirmation_seconds=0))
        token.growth_alert_sent = True
        self.assertFalse(should_send_growth(token, threshold=10000, confirmation_seconds=0))


if __name__ == "__main__":
    unittest.main()
