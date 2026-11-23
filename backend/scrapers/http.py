"""Polite HTTP fetching for scrapers: per-host rate limiting + User-Agent rotation."""

import asyncio
import logging
import random
import re
import time
from urllib.parse import urlparse

import httpx

from core.config import settings
from services.platforms.base import AdapterError

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Mobile Safari/537.36",
]

_BLOCK_MARKERS = ("captcha", "robot check", "access denied", "are you a human", "unusual traffic")


class HostRateLimiter:
    """Allows at most one request per `interval` seconds per host."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            elapsed = time.monotonic() - self._last.get(host, 0.0)
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self._last[host] = time.monotonic()


rate_limiter = HostRateLimiter(settings.scraper_rate_limit_seconds)


def browser_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
        "Cache-Control": "no-cache",
    }


async def fetch_html(url: str, *, timeout: float = 15.0, extra_headers: dict | None = None) -> str:
    """GET a page politely. Raises AdapterError when blocked or failing."""
    host = urlparse(url).netloc
    await rate_limiter.wait(host)
    headers = browser_headers() | (extra_headers or {})
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, http2=False) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise AdapterError(f"{host} request failed: {exc.__class__.__name__}") from exc

    if resp.status_code in (403, 429, 503, 529):
        raise AdapterError(f"{host} blocked the request (HTTP {resp.status_code})")
    if resp.status_code >= 400:
        raise AdapterError(f"{host} returned HTTP {resp.status_code}")

    text = resp.text
    head = text[:20000].lower()
    if any(marker in head for marker in _BLOCK_MARKERS) and len(text) < 20000:
        raise AdapterError(f"{host} showed a bot check (CAPTCHA)")
    return text


_PRICE_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def parse_price(text: str | None) -> float | None:
    """'₹1,29,999.00' -> 129999.0"""
    if not text:
        return None
    m = _PRICE_RE.search(text.replace("₹", " "))
    if not m:
        return None
    try:
        value = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 else None


def parse_int(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else None
