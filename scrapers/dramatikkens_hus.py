from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, parse_nb_date, to_datetime

log = logging.getLogger(__name__)


class DramatikkensHusScraper(BaseScraper):
    venue = "Dramatikkens Hus"
    venue_slug = "dramatikkens-hus"
    base_url = "https://www.dramatikkenshus.no"
    program_url = "https://www.dramatikkenshus.no/kalender"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        # Dramatikkens Hus calendar items live in <article> elements with date and title
        articles = soup.find_all("article")
        log.info("Dramatikkens Hus: %d articles", len(articles))
        shows: list[Show] = []
        seen: set[str] = set()
        for art in articles:
            link = art.find("a", href=re.compile(r"/kalender/[^/?#]+/?$"))
            if not link:
                continue
            href = link["href"]
            slug = href.rstrip("/").split("/")[-1]
            text = art.get_text("|", strip=True)
            # Date: look for "5. mai" pattern
            date_text = None
            for line in text.split("|"):
                if re.search(r"\d{1,2}\.\s*(jan|feb|mar|apr|mai|jun|jul|aug|sep|okt|nov|des)", line, re.I):
                    date_text = line
                    break
            d = parse_nb_date(date_text or "")
            if not d:
                continue
            title_el = art.find(["h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else None
            if not title:
                continue
            # Time
            time_text = ""
            for line in text.split("|"):
                if re.search(r"\d{1,2}[.:]\d{2}", line):
                    time_text = line
                    break
            tm = re.search(r"(\d{1,2})[.:](\d{2})", time_text)
            hour = int(tm.group(1)) if tm else 19
            minute = int(tm.group(2)) if tm else 0
            detail_url = urljoin(self.base_url, href) if href.startswith("/") else href
            img = art.find("img")
            image_url = img.get("src") if img else None
            sid = self.make_id(self.venue_slug, slug, str(d), str(hour))
            if sid in seen:
                continue
            seen.add(sid)
            shows.append(Show(
                id=sid,
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                start=to_datetime(d, hour=hour, minute=minute),
                ticket_url=detail_url,
                detail_url=detail_url,
                image_url=image_url,
            ))
        return shows
