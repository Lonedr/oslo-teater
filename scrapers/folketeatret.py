from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, NB_MONTHS, Show, fetch_rendered

log = logging.getLogger(__name__)


# Regex for individual performances on detail pages. Each <div class="line ..."> holds
# one performance with weekday, date, optional time, and optional subtitle.
_LINE_RE = re.compile(
    r'<div class="line\s+(?P<cls>[^"]*)"[^>]*>.*?'
    r'<span class="title">\s*\w+\s*-\s*'
    r'(?P<day>\d{1,2})\.\s*(?P<mon>[a-zæøå]+)\s*(?P<year>\d{4})'
    r'.*?kl\.\s*(?P<h>\d{1,2})[.:](?P<m>\d{2})',
    re.DOTALL | re.IGNORECASE,
)
_SOLD_OUT_RE = re.compile(r'tickets-label[^"]*sold-out', re.IGNORECASE)


class FolketeatretScraper(BaseScraper):
    venue = "Folketeateret"
    venue_slug = "folketeateret"
    base_url = "https://folketeateret.no"
    program_url = "https://folketeateret.no/forestillinger/program"

    def fetch(self) -> list[Show]:
        html = fetch_rendered(self.program_url, settle_ms=1500)
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("div.article__main")
        log.info("Folketeateret: %d cards", len(cards))

        # Collect production cards (slug -> base info)
        productions: dict[str, dict] = {}
        for card in cards:
            link = card.select_one('a[href*="/forestilling/"]')
            if not link:
                continue
            href = link["href"]
            slug = href.rstrip("/").split("/")[-1]
            if slug in productions:
                continue
            title_el = card.find(["h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()
            pretitle_el = card.select_one(".pretitle")
            genre = pretitle_el.get_text(" ", strip=True) if pretitle_el else None
            img = card.find("img")
            image_url = img.get("src") if img else None
            if image_url and image_url.startswith("/"):
                image_url = urljoin(self.base_url, image_url)
            detail_url = urljoin(self.base_url, href) if href.startswith("/") else href
            productions[slug] = {
                "title": title,
                "genre": genre,
                "image_url": image_url,
                "detail_url": detail_url,
            }

        shows: list[Show] = []
        for slug, info in productions.items():
            try:
                shows.extend(self._fetch_production(slug, info))
            except Exception as e:
                log.warning("Folketeateret: failed %s: %s", slug, e)
        log.info("Folketeateret: %d total performances", len(shows))
        return shows

    def _fetch_production(self, slug: str, info: dict) -> list[Show]:
        r = self.get(info["detail_url"])
        html = r.text
        shows: list[Show] = []
        seen_dt: set[datetime] = set()
        for m in _LINE_RE.finditer(html):
            mon = m.group("mon").lower()
            month = NB_MONTHS.get(mon)
            if not month:
                continue
            try:
                dt = datetime(
                    int(m.group("year")), month, int(m.group("day")),
                    int(m.group("h")), int(m.group("m")),
                )
            except ValueError:
                continue
            if dt in seen_dt:
                continue
            seen_dt.add(dt)
            # Sold-out indicator within this line block
            block = html[m.start():m.start() + 2000]
            sold_out = bool(_SOLD_OUT_RE.search(block))
            shows.append(Show(
                id=self.make_id(self.venue_slug, slug, dt.isoformat()),
                title=info["title"],
                venue=self.venue,
                venue_slug=self.venue_slug,
                start=dt,
                genre=info["genre"],
                image_url=info["image_url"],
                ticket_url=info["detail_url"],
                detail_url=info["detail_url"],
                sold_out=sold_out,
            ))
        return shows
