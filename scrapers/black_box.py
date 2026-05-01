from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, parse_nb_date, to_datetime

log = logging.getLogger(__name__)


class BlackBoxScraper(BaseScraper):
    venue = "Black Box teater"
    venue_slug = "black-box"
    base_url = "https://blackbox.no"
    program_url = "https://blackbox.no/"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        entries = soup.select(".header-calendar__entry")
        log.info("Black Box: %d calendar entries", len(entries))
        shows: list[Show] = []
        seen: set[str] = set()
        for entry in entries:
            day_el = entry.select_one(".header-calendar__entry__day")
            link = entry.select_one("a.header-calendar__entry__event")
            if not day_el or not link:
                continue
            day_text = day_el.get_text(" ", strip=True)
            day_text = re.sub(r"^(mandag|tirsdag|onsdag|torsdag|fredag|lørdag|søndag)\s+", "", day_text, flags=re.I)
            start_date = parse_nb_date(day_text)
            if not start_date:
                log.debug("Black Box: skip %r — no date", day_text)
                continue
            time_el = entry.select_one(".header-calendar__entry__event__time")
            hour, minute = 19, 0
            if time_el:
                tm = re.search(r"(\d{1,2})[.:](\d{2})", time_el.get_text())
                if tm:
                    hour, minute = int(tm.group(1)), int(tm.group(2))
            title_el = entry.select_one(".header-calendar__entry__event__title")
            title = None
            if title_el:
                # Prefer <i> if present (italic = show title)
                italic = title_el.find("i")
                if italic:
                    title = italic.get_text(strip=True)
                else:
                    title = title_el.get_text(" ", strip=True).split("\n")[0].strip()
            if not title:
                continue
            href = link["href"]
            detail_url = urljoin(self.base_url, href)
            location_el = entry.select_one(".header-calendar__entry__event__location")
            stage = location_el.get_text(" ", strip=True) if location_el else None
            sid = self.make_id(self.venue_slug, href, str(start_date), str(hour))
            if sid in seen:
                continue
            seen.add(sid)
            shows.append(Show(
                id=sid,
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                stage=stage,
                start=to_datetime(start_date, hour=hour, minute=minute),
                ticket_url=detail_url,
                detail_url=detail_url,
            ))
        return shows
