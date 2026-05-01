from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show

log = logging.getLogger(__name__)


class RiksteatretScraper(BaseScraper):
    """Riksteatret turnerer hele landet. Vi henter detaljside for hver produksjon
    og emitterer én Show per spilledato i Oslo (Nydalen, Vega Scene, etc.)."""

    venue = "Riksteatret"
    venue_slug = "riksteatret"
    base_url = "https://www.riksteatret.no"
    program_url = "https://www.riksteatret.no/"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        slugs: list[str] = []
        seen: set[str] = set()
        for a in soup.select('a[href^="/repertoar/"]'):
            slug = a["href"].rstrip("/").split("/")[-1]
            if not slug or slug in seen or slug == "repertoar":
                continue
            seen.add(slug)
            slugs.append(slug)

        log.info("Riksteatret: %d productions", len(slugs))
        shows: list[Show] = []
        for slug in slugs:
            try:
                shows.extend(self._fetch_production(slug))
            except Exception as e:
                log.warning("Riksteatret: failed %s: %s", slug, e)
        log.info("Riksteatret: %d Oslo performances", len(shows))
        return shows

    def _fetch_production(self, slug: str) -> list[Show]:
        url = f"{self.base_url}/repertoar/{slug}/"
        r = self.get(url)
        soup = BeautifulSoup(r.text, "lxml")

        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()

        img = soup.find("img")
        image_url = img.get("src") if img else None
        if image_url and image_url.startswith("/"):
            image_url = urljoin(self.base_url, image_url)

        # Description: first paragraph after the lead
        desc_el = soup.select_one(".lead, .ingress, .summary")
        description = desc_el.get_text(" ", strip=True) if desc_el else None

        shows: list[Show] = []
        seen_dt: set[datetime] = set()
        for item in soup.select("li.nav-program__item"):
            descr = item.select_one(".item__descr")
            if not descr:
                continue
            descr_text = descr.get_text(" ", strip=True)
            if not re.search(r"\b[Oo]slo\b|Nydalen", descr_text):
                continue

            date_el = item.select_one(".item__date")
            if not date_el:
                continue
            datetime_attr = date_el.get("datetime", "")
            # Format: "05.06.2026 18:00"
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})\s+(\d{1,2}):(\d{2})", datetime_attr)
            if not m:
                continue
            try:
                dt = datetime(
                    int(m.group(3)), int(m.group(2)), int(m.group(1)),
                    int(m.group(4)), int(m.group(5)),
                )
            except ValueError:
                continue
            if dt in seen_dt:
                continue
            seen_dt.add(dt)

            # Stage: venue name from descr, e.g. "Oslo / Nydalen | Riksteatret" or "Oslo / Vega Scene | Vega Scene"
            stage = None
            descr_h = descr.find(["h2", "h3"])
            descr_p = descr.find("p")
            if descr_h and descr_p:
                # h2 text is "Oslo / Nydalen"; p is venue
                stage = descr_p.get_text(" ", strip=True) or None

            # Ticket link
            ticket_link = item.select_one('a[href*="ticket"], a[class*="ticket"], a.cta, .item__link a')
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
