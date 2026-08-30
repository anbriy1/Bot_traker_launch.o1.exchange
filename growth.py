from __future__ import annotations

from datetime import datetime, timedelta, timezone

from repository import TokenRecord


def should_send_growth(
    token: TokenRecord,
    *,
    threshold: float,
    confirmation_seconds: int,
    now: datetime | None = None,
) -> bool:
    if token.growth_alert_sent or not token.active:
        return False
    if token.current_mc is None or token.current_mc < threshold:
        return False
    if confirmation_seconds <= 0:
        return True
    if token.above_threshold_since is None:
        return False
    now = now or datetime.now(timezone.utc)
    since = token.above_threshold_since
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return now - since >= timedelta(seconds=confirmation_seconds)


def tracking_expired(token: TokenRecord, max_minutes: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    first_seen = token.first_seen
    if first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    return now - first_seen >= timedelta(minutes=max_minutes)
