from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from token_parser import token_list

log = logging.getLogger("o1-launch-alerts")

RETRYABLE = {429, 500, 502, 503, 504}


class O1ApiError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class O1Client:
    def __init__(self, api_url: str, api_key: str, chain_id: str, list_limit: int) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.chain_id = chain_id
        self.list_limit = min(100, max(1, list_limit))
        parsed = urlparse(self.api_url)
        self._base = f"{parsed.scheme}://{parsed.netloc}"
        self.session = requests.Session()
        retry = Retry(
            total=0,
            connect=2,
            read=2,
            backoff_factor=0.5,
            status_forcelist=(),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=8)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self._lock = threading.Lock()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "X-API-Key": api_key,
                "x-api-key": api_key,
                "Accept": "application/json",
            }
        )

    def _sleep_backoff(self, attempt: int, retry_after: float | None) -> None:
        if retry_after is not None and retry_after > 0:
            delay = retry_after
        else:
            delay = min(30.0, (2 ** attempt) + random.uniform(0, 0.5))
        log.warning("[API] Retry in %.1ss (attempt %s)", delay, attempt + 1)
        time.sleep(delay)

    def _request(self, method: str, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                with self._lock:
                    response = self.session.request(method, url, params=params, timeout=20)
            except requests.Timeout as exc:
                last_error = exc
                log.warning("[API] Timeout %s", url.split("?")[0])
                self._sleep_backoff(attempt, None)
                continue
            except requests.RequestException as exc:
                last_error = exc
                log.warning("[API] Request failed: %s", exc)
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else None
                log.warning("[API] Rate limit 429 request_id=%s", response.headers.get("X-Request-Id", "-"))
                if attempt < 4:
                    self._sleep_backoff(attempt, wait)
                    continue
                raise O1ApiError("rate limited", status=429, retry_after=wait)

            if response.status_code in {502, 503, 504} and attempt < 4:
                log.warning("[API] Retry %s", response.status_code)
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 500 and attempt == 0:
                log.warning("[API] Retry 500")
                self._sleep_backoff(attempt, None)
                continue

            if response.status_code == 404:
                raise O1ApiError("not found", status=404)

            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                raise O1ApiError(str(exc), status=response.status_code) from exc

            try:
                return response.json()
            except ValueError as exc:
                raise O1ApiError("invalid json") from exc

        raise O1ApiError(f"request failed: {last_error}")

    def fetch_tokens(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            self.api_url,
            params={
                "chain_id": self.chain_id,
                "sort": "newest",
                "limit": self.list_limit,
            },
        )
        return token_list(payload)

    def fetch_token_detail(self, address: str) -> dict[str, Any]:
        url = f"{self._base}/v1/tokens/{self.chain_id}/{address}"
        payload = self._request("GET", url, params={"include": "market"})
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            return payload["data"]
        if isinstance(payload, dict):
            return payload
        raise O1ApiError("unexpected token detail payload")
