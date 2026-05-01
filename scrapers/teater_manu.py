from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, NB_MONTHS, Show, _guess_year

log = logging.getLogger(__name__)


class TeaterManuScraper(BaseScraper):
    """Teater Manu turnerer (tegnspråkteater). Detaljsiden har en tabell med
    `<tr class="show-row">` per spilledato — vi emitterer én Show per Oslo-rad."""

    venue = "Teater Manu"
    venue_slug = "teater-manu"
    base_url = "https://teatermanu.no"
    program_url = "https://teatermanu.no/produksjoner/"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        teasers = soup.select(".production-teaser")
        log.info("Teater Manu: %d teasers", len(teasers))

        slugs: list[tuple[str, str]] = []
        seen: set[str] = set()
        for t in teasers:
            link = t.find("a", href=re.compile(r"/produksjoner/[^/]+/"))
            if not link:
                continue
            href = link["href"]
            slug = href.rstrip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)
            title_el = t.find(["h1", "h2", "h3", "h4"])
            title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()
            slugs.append((slug, title))

        shows: list[Show] = []
        for slug, title in slugs:
            try:
                shows.extend(self._fetch_production(slug, title))
            except Exception as e:
                log.warning("Teater Manu: failed %s: %s", slug, e)
        log.info("Teater Manu: %d Oslo performances", len(shows))
        return shows

    def _fetch_production(self, slug: str, title: str) -> list[Show]:
        url = f"{self.base_url}/produksjoner/{slug}/"
        r = self.get(url)
        soup = BeautifulSoup(r.text, "lxml")

        img = soup.find("img")
        image_url = img.get("src") if img else None
        if image_url and image_url.startswith("/"):
            image_url = urljoin(self.base_url, image_url)

        desc_el = soup.select_one(".lead, .ingress, .summary, p.intro")
        description = desc_el.get_text(" ", strip=True) if desc_el else None

        shows: list[Show] = []
        seen_dt: set[datetime] = set()
        for row in soup.select("tr.show-row"):
            city_el = row.select_one(".show-city")
            if not city_el or "oslo" not in city_el.get_text(strip=True).lower():
                continue

            day_el = row.select_one(".show-day")
            time_el = row.select_one(".show-time")
            if not day_el or not time_el:
                continue
            day_text = day_el.get_text(" ", strip=True).lower()  # "tir 05. mai"
            time_text = time_el.get_text(" ", strip=True).lower()  # "kl 19:00"

            # Day: extract day-of-month + month name
            m_day = re.search(r"(\d{1,2})\.\s*([a-zæøå]+)", day_text)
            if not m_day:
                continue
            day = int(m_day.group(1))
            month_name = m_day.group(2)[:3]  # normalise "mai" / "jun" / "jul"
            month = NB_MONTHS.get(month_name) or NB_MONTHS.get(m_day.group(2))
            if not month:
                continue
            year = _guess_year(month_name)

            m_time = re.search(r"(\d{1,2})[.:](\d{2})", time_text)
            hour = int(m_time.group(1)) if m_time else 19
            minute = int(m_time.group(2)) if m_time else 0
            if hour == 0 and minute == 0:
                # "kl 00:00" appears as a placeholder; default to 19:00
                hour, minute = 19, 0

            try:
                dt = datetime(year, month, day, hour, minute)
            except ValueError:
                continue
            if dt in seen_dt:
                continue
            seen_dt.add(dt)

            venue_el = row.select_one(".show-venue")
            stage = venue_el.get_text(" ", strip=True) if venue_el else None

            ticket_link = row.select_one(".show-link a, a.ticket, a.cta")
            ticket_url = ticket_link["href"] if ticket_link and ticket_link.get("href") else url

            shows.append(Show(
                id=self.make_id(self.venue_slug, slug, dt.isoformat()),
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                stage=stage,
                start=dt,
                description=description,
                image_url=image_url,
                ticket_url=ticket_url,
                detail_url=url,
            ))
        return shows
