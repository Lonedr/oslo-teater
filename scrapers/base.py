from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

import requests
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0 Safari/537.36 OsloTeaterAggregator/0.1"
    ),
    "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.7",
}

NB_MONTHS = {
    "januar": 1, "jan": 1,
    "februar": 2, "feb": 2,
    "mars": 3, "mar": 3,
    "april": 4, "apr": 4,
    "mai": 5,
    "juni": 6, "jun": 6,
    "juli": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "desember": 12, "des": 12,
}


class Show(BaseModel):
    id: str
    title: str
    venue: str
    venue_slug: str
    start: datetime
    end: Optional[datetime] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    ticket_url: str
    detail_url: Optional[str] = None
    stage: Optional[str] = None
    genre: Optional[str] = None
    sold_out: bool = False
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class BaseScraper(ABC):
    venue: str = ""
    venue_slug: str = ""
    base_url: str = ""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def get(self, url: str, **kwargs) -> requests.Response:
        log.debug("GET %s", url)
        r = self.session.get(url, timeout=30, **kwargs)
        r.raise_for_status()
        return r

    @abstractmethod
    def fetch(self) -> list[Show]:
        ...

    def make_id(self, *parts: str) -> str:
        joined = "|".join(p for p in parts if p)
        return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def parse_nb_date(text: str, fallback_year: Optional[int] = None) -> Optional[date]:
    """Parse Norwegian dates like '5. september 2026', '5. sep 2026', '5/9-2026', '2026-09-05'."""
    if not text:
        return None
    text = text.strip().lower()
    # ISO
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    # "5. september 2026" or "5 september 2026"
    m = re.search(r"(\d{1,2})\.?\s+([a-zæøå]+)(?:\s+(\d{4}))?", text)
    if m:
        day = int(m.group(1))
        month_name = m.group(2)
        year = int(m.group(3)) if m.group(3) else (fallback_year or _guess_year(month_name))
        if month_name in NB_MONTHS:
            try:
                return date(year, NB_MONTHS[month_name], day)
            except ValueError:
                pass
    # "5/9-2026" or "05.09.2026"
    m = re.match(r"(\d{1,2})[./](\d{1,2})[-./](\d{4})", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    return None


def parse_nb_date_range(text: str) -> tuple[Optional[date], Optional[date]]:
    """Parse '26. mars til 5. september 2026', '23. april–2. mai 2026', '03. sep 05. des'."""
    if not text:
        return None, None
    t = re.sub(r"\s+", " ", text).strip()
    # Find year hint
    year_hint = None
    ym = re.search(r"(20\d{2})", t)
    if ym:
        year_hint = int(ym.group(1))

    # Split on "til", "–", "—", "-" (but be careful with date separators)
    parts = re.split(r"\s+til\s+|\s*[–—]\s*|\s+-\s+", t, maxsplit=1)
    if len(parts) == 2:
        a, b = parts
        # Year may only appear in one of them
        d2 = parse_nb_date(b, fallback_year=year_hint)
        d1 = parse_nb_date(a, fallback_year=d2.year if d2 else year_hint)
        return d1, d2
    # Single date
    d = parse_nb_date(t, fallback_year=year_hint)
    return d, None


def _guess_year(month_name: str) -> int:
    """Guess year: if month is in past relative to today, assume next year."""
    today = date.today()
    m = NB_MONTHS.get(month_name)
    if not m:
        return today.year
    if m < today.month - 2:  # more than 2 months ago — assume next year
        return today.year + 1
    return today.year


def to_datetime(d: Optional[date], hour: int = 19, minute: int = 0) -> Optional[datetime]:
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, hour, minute)


_pw_browser = None


def _pw():
    """Lazy import + cache the Playwright browser instance for the process."""
    global _pw_browser
    if _pw_browser is None:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        _pw_browser = (pw, browser)
    return _pw_browser


def fetch_rendered(url: str, wait_until: str = "networkidle", settle_ms: int = 1000, timeout_ms: int = 30000) -> str:
    """Fetch a JS-rendered page via Playwright and return the post-render HTML."""
    _, browser = _pw()
    ctx = browser.new_context(locale="nb-NO", user_agent=DEFAULT_HEADERS["User-Agent"])
    page = ctx.new_page()
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        if settle_ms:
            page.wait_for_timeout(settle_ms)
        html = page.content()
        return html
    finally:
        ctx.close()


def close_browser():
    global _pw_browser
    if _pw_browser is not None:
        pw, browser = _pw_browser
        browser.close()
        pw.stop()
        _pw_browser = None
