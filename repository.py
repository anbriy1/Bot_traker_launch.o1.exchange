from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class TokenRecord:
    address: str
    name: str
    symbol: str
    token_url: str
    initial_mc: float | None
    current_mc: float | None
    highest_mc: float | None
    first_seen: datetime
    last_check: datetime | None
    growth_alert_sent: bool
    growth_alert_sent_at: datetime | None
    growth_alert_lock: bool
    threshold_reached_at: datetime | None
    above_threshold_since: datetime | None
    new_alert_sent: bool
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> TokenRecord:
        return cls(
            address=row["address"],
            name=row["name"],
            symbol=row["symbol"] or "",
            token_url=row["token_url"] or "",
            initial_mc=row["initial_mc"],
            current_mc=row["current_mc"],
            highest_mc=row["highest_mc"],
            first_seen=parse_dt(row["first_seen"]) or utc_now(),
            last_check=parse_dt(row["last_check"]),
            growth_alert_sent=bool(row["growth_alert_sent"]),
            growth_alert_sent_at=parse_dt(row["growth_alert_sent_at"]),
            growth_alert_lock=bool(row["growth_alert_lock"]),
            threshold_reached_at=parse_dt(row["threshold_reached_at"]),
            above_threshold_since=parse_dt(row["above_threshold_since"]),
            new_alert_sent=bool(row["new_alert_sent"]),
            active=bool(row["active"]),
        )


class TokenRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                address TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                symbol TEXT,
                token_url TEXT,
                initial_mc REAL,
                current_mc REAL,
                highest_mc REAL,
                first_seen TEXT NOT NULL,
                last_check TEXT,
                growth_alert_sent INTEGER NOT NULL DEFAULT 0,
                growth_alert_sent_at TEXT,
                growth_alert_lock INTEGER NOT NULL DEFAULT 0,
                threshold_reached_at TEXT,
                above_threshold_since TEXT,
                new_alert_sent INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def migrate_seen_json(self, state_file: Path) -> int:
        if not state_file.exists():
            return 0
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            ids = data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return 0
        imported = 0
        now = iso(utc_now())
        with self._lock:
            for raw in ids:
                address = str(raw)
                try:
                    cursor = self._conn.execute(
                        """
                        INSERT OR IGNORE INTO tokens (
                            address, name, symbol, token_url, first_seen, last_check,
                            new_alert_sent, growth_alert_sent, active
                        ) VALUES (?, ?, '', '', ?, ?, 1, 0, 0)
                        """,
                        (address, address, now, now),
                    )
                    imported += cursor.rowcount
                except sqlite3.Error:
                    continue
            self._conn.commit()
        return imported

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS n FROM tokens").fetchone()
        return int(row["n"] if row else 0)

    def get(self, address: str) -> TokenRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tokens WHERE address = ?", (address,)).fetchone()
        return TokenRecord.from_row(row) if row else None

    def insert_discovered(
        self,
        *,
        address: str,
        name: str,
        symbol: str,
        token_url: str,
        market_cap: float | None,
        first_seen: datetime,
        active: bool,
        new_alert_sent: bool,
    ) -> bool:
        now = iso(first_seen)
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO tokens (
                    address, name, symbol, token_url, initial_mc, current_mc, highest_mc,
                    first_seen, last_check, new_alert_sent, growth_alert_sent, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    address,
                    name,
                    symbol,
                    token_url,
                    market_cap,
                    market_cap,
                    market_cap,
                    now,
                    now,
                    int(new_alert_sent),
                    int(active),
                ),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def mark_new_alert_sent(self, address: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tokens SET new_alert_sent = 1 WHERE address = ?",
                (address,),
            )
            self._conn.commit()

    def list_pending_new_alerts(self) -> list[TokenRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tokens WHERE new_alert_sent = 0"
            ).fetchall()
        return [TokenRecord.from_row(row) for row in rows]

    def list_active(self) -> list[TokenRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tokens WHERE active = 1 AND growth_alert_sent = 0"
            ).fetchall()
        return [TokenRecord.from_row(row) for row in rows]

    def apply_market_cap(
        self,
        address: str,
        market_cap: float | None,
        checked_at: datetime,
        threshold: float,
        name: str | None = None,
        symbol: str | None = None,
    ) -> TokenRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tokens WHERE address = ?", (address,)).fetchone()
            if row is None:
                return None
            record = TokenRecord.from_row(row)
            highest = record.highest_mc
            if market_cap is not None:
                highest = market_cap if highest is None else max(highest, market_cap)
            above_since = record.above_threshold_since
            threshold_at = record.threshold_reached_at
            if market_cap is not None and market_cap >= threshold:
                if above_since is None:
                    above_since = checked_at
                if threshold_at is None:
                    threshold_at = checked_at
            else:
                above_since = None
            self._conn.execute(
                """
                UPDATE tokens
                SET current_mc = ?,
                    highest_mc = ?,
                    last_check = ?,
                    above_threshold_since = ?,
                    threshold_reached_at = ?,
                    name = COALESCE(NULLIF(?, ''), name),
                    symbol = COALESCE(NULLIF(?, ''), symbol)
                WHERE address = ?
                """,
                (
                    market_cap if market_cap is not None else record.current_mc,
                    highest,
                    iso(checked_at),
                    iso(above_since),
                    iso(threshold_at),
                    name or "",
                    symbol or "",
                    address,
                ),
            )
            self._conn.commit()
        return self.get(address)

    def update_identity(self, address: str, name: str, symbol: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tokens SET name = ?, symbol = ? WHERE address = ?",
                (name, symbol, address),
            )
            self._conn.commit()

    def deactivate(self, address: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE tokens SET active = 0 WHERE address = ?", (address,))
            self._conn.commit()

    def try_claim_growth_alert(self, address: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE tokens
                SET growth_alert_lock = 1
                WHERE address = ?
                  AND growth_alert_sent = 0
                  AND growth_alert_lock = 0
                  AND active = 1
                """,
                (address,),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def mark_growth_sent(self, address: str, sent_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE tokens
                SET growth_alert_sent = 1,
                    growth_alert_lock = 0,
                    growth_alert_sent_at = ?,
                    active = 0
                WHERE address = ?
                """,
                (iso(sent_at), address),
            )
            self._conn.commit()

    def release_growth_lock(self, address: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE tokens
                SET growth_alert_lock = 0
                WHERE address = ? AND growth_alert_sent = 0
                """,
                (address,),
            )
            self._conn.commit()
