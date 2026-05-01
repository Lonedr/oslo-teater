from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, fetch_rendered, to_datetime

log = logging.getLogger(__name__)

# Nordic Black slugs end with DD-MM-YYYY
SLUG_DATE_RE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})$")


class NordicBlackScraper(BaseScraper):
    venue = "Nordic Black Theatre"
    venue_slug = "nordic-black"
    base_url = "https://nordicblacktheatre.no"
    program_url = "https://nordicblacktheatre.no/program"

    def fetch(self) -> list[Show]:
        html = fetch_rendered(self.program_url, wait_until="domcontentloaded", settle_ms=4000, timeout_ms=45000)
        soup = BeautifulSoup(html, "lxml")
        # Each show: <a href="/program/{slug-DD-MM-YYYY}?view=...">
        anchors = soup.select('a[href*="/program/"]')
        log.info("Nordic Black: %d /program/ anchors", len(anchors))
        shows: list[Show] = []
        seen: set[str] = set()
        for a in anchors:
            href = a["href"]
            m = re.match(r"(?:https?://[^/]+)?/program/([^/?#]+)", href)
            if not m:
                continue
            slug = m.group(1)
            if slug in seen or slug == "":
                continue
            sd = SLUG_DATE_RE.search(slug)
            if not sd:
                continue
            seen.add(slug)
            start_date = None
            try:
                start_date = date(int(sd.group(3)), int(sd.group(2)), int(sd.group(1)))
            except ValueError:
                continue
            # Title text
            title_text = a.get_text(" ", strip=True)
            # The visible title may be in a child h-element
            heading = a.find(["h1", "h2", "h3", "h4"])
            if heading:
                title_text = heading.get_text(" ", strip=True)
            if not title_text:
                # Slug is human-readable — drop the trailing date
                base = SLUG_DATE_RE.sub("", slug).replace("-", " ").strip()
                title_text = base.title()
            title_text = re.sub(r"\s+", " ", title_text).strip()
            if title_text.lower() in {"les mer", "kjøp billett", "se forestilling"}:
                # Re-derive from slug
                base = SLUG_DATE_RE.sub("", slug).replace("-", " ").strip()
                title_text = base.title()

            # Time hint — look for "kl 19:00" or similar in surrounding text
            parent_text = a.parent.get_text(" ", strip=True) if a.parent else ""
            tm = re.search(r"(?:kl\.?\s*)?(\d{1,2})[:.](\d{2})", parent_text)
            hour = int(tm.group(1)) if tm else 19
            minute = int(tm.group(2)) if tm else 0

            detail_url = urljoin(self.base_url, href.split("?")[0]) if href.startswith("/") else href.split("?")[0]
            img = a.find("img")
            image_url = img.get("src") if img else None
            if image_url and image_url.startswith("//"):
                image_url = "https:" + image_url

            shows.append(Show(
                id=self.make_id(self.venue_slug, slug),
                title=title_text,
                venue=self.venue,
                venue_slug=self.venue_slug,
                start=to_datetime(start_date, hour=hour, minute=minute),
                ticket_url=detail_url,
                detail_url=detail_url,
                image_url=image_url,
            ))
        return shows
