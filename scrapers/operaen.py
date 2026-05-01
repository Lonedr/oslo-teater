from __future__ import annotations

import logging
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (
    BaseScraper,
    Show,
    fetch_rendered,
    parse_nb_date,
    to_datetime,
    NB_MONTHS,
)

log = logging.getLogger(__name__)

WEEKDAY_RE = re.compile(
    r"^(?:mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag)\s+", re.I
)
TIME_RE = re.compile(r"(\d{1,2})[:.](\d{2})")
GENRE_HINTS = {
    "opera": "Opera",
    "ballett": "Ballett",
    "konsert": "Konsert",
    "danseteater": "Danseteater",
    "ballet": "Ballett",
}


class OperaenScraper(BaseScraper):
    venue = "Den Norske Opera & Ballett"
    venue_slug = "operaen"
    base_url = "https://operaen.no"
    program_url = "https://operaen.no/"

    def fetch(self) -> list[Show]:
        # Homepage is JS-rendered; gives us the full set of forestilling links
        listing_html = fetch_rendered(self.program_url, settle_ms=2000)
        soup = BeautifulSoup(listing_html, "lxml")
        anchors = soup.select('a[href*="/forestillinger/"]')
        slugs: list[tuple[str, str]] = []  # (slug, detail_url)
        seen: set[str] = set()
        for a in anchors:
            href = a["href"]
            m = re.search(r"/forestillinger/([^/?#]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen or not slug:
                continue
            seen.add(slug)
            detail_url = urljoin(self.base_url, href.split("?")[0])
            if not detail_url.endswith("/"):
                detail_url += "/"
            slugs.append((slug, detail_url))
        log.info("Operaen: %d unique forestilling slugs", len(slugs))

        shows: list[Show] = []
        for slug, detail_url in slugs:
            try:
                shows.extend(self._fetch_detail(slug, detail_url))
            except Exception:
                log.exception("Operaen detail %s failed", slug)
        log.info("Operaen: %d performances", len(shows))
        return shows

    def _fetch_detail(self, slug: str, url: str) -> list[Show]:
        r = self.get(url)
        soup = BeautifulSoup(r.text, "lxml")
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else slug.replace("-", " ").title()
        title = re.sub(r"\s+", " ", title).strip()
        if title.lower() in {"snart salgsstart!", "salgsstart"}:
            return []

        # Genre from slug
        genre = None
        for hint, label in GENRE_HINTS.items():
            if hint in slug:
                genre = label
                break

        # Image - look for og:image
        image_url = None
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image_url = og["content"]

        # Description - meta description
        description = None
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            description = md["content"].strip()

        events = soup.select("li.event")
        out: list[Show] = []
        seen_keys: set[str] = set()
        for li in events:
            date_el = li.select_one(".date")
            if not date_el:
                continue
            date_text = date_el.get_text(" ", strip=True)
            time_el = li.select_one(".playTime")
            time_text = time_el.get_text(" ", strip=True) if time_el else ""
            scene_el = li.select_one(".scene")
            stage = scene_el.get_text(" ", strip=True) if scene_el else None

            start_dt = self._parse_event_date(date_text, time_text)
            if not start_dt:
                continue

            ticket_a = li.select_one("a[href]")
            ticket_url = ticket_a["href"] if ticket_a else url
            if ticket_url.startswith("/"):
                ticket_url = urljoin(self.base_url, ticket_url)

            sold_out = bool(li.select_one(".salesStatus")) and "utsolgt" in li.get_text(" ", strip=True).lower()

            key = f"{start_dt.isoformat()}|{stage or ''}"
            if key in seen_keys:
                continue
            seen_keys.add(key)

            out.append(Show(
                id=self.make_id(self.venue_slug, slug, start_dt.isoformat()),
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                stage=stage,
                start=start_dt,
                description=description,
                genre=genre,
                image_url=image_url,
                ticket_url=ticket_url,
                detail_url=url,
                sold_out=sold_out,
            ))
        return out

    @staticmethod
    def _parse_event_date(date_text: str, time_text: str) -> datetime | None:
        # Strip weekday prefix: "Lørdag 6. juni" → "6. juni"
        cleaned = WEEKDAY_RE.sub("", date_text).strip()
        # Year may or may not be present
        d = parse_nb_date(cleaned)
        if not d:
            return None
        hour, minute = 19, 0
        if time_text:
            m = TIME_RE.search(time_text)
            if m:
                hour = int(m.group(1))
                minute = int(m.group(2))
        return to_datetime(d, hour=hour, minute=minute)
