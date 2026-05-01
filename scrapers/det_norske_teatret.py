from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, fetch_rendered

log = logging.getLogger(__name__)

# Listing-card category prefixes that we want stripped from the title.
CATEGORY_PREFIXES = re.compile(
    r"^(?:FOR\s+BARN|FOR\s+UNGDOM|MUSIKAL|FRAMSYNING|SCENEKUNST|"
    r"DANS|KONSERT|DRAMATIKK|TURNÉ|PREMIERE|GJESTESPEL|GJESTESPILL)\s+",
    re.I,
)


class DetNorskeTeatretScraper(BaseScraper):
    venue = "Det Norske Teatret"
    venue_slug = "det-norske-teatret"
    base_url = "https://www.detnorsketeatret.no"
    program_url = "https://www.detnorsketeatret.no/framsyningar"

    def fetch(self) -> list[Show]:
        # Listing is JS-rendered; detail pages are static (server-rendered with JSON-LD).
        listing_html = fetch_rendered(self.program_url, settle_ms=2000)
        soup = BeautifulSoup(listing_html, "lxml")
        cards = soup.select("article.block-play-entry, article.block-entry")
        log.info("Det Norske: %d listing cards", len(cards))
        slugs: list[str] = []
        seen: set[str] = set()
        for card in cards:
            link = card.select_one('a[href*="/framsyningar/"]')
            if not link:
                continue
            m = re.search(r"/framsyningar/([^/?#]+)", link["href"])
            if not m:
                continue
            slug = m.group(1)
            if slug in seen or slug == "":
                continue
            seen.add(slug)
            slugs.append(slug)

        shows: list[Show] = []
        for slug in slugs:
            try:
                shows.extend(self._fetch_detail(slug))
            except Exception:
                log.exception("Det Norske detail %s failed", slug)
        log.info("Det Norske: %d performances across %d productions", len(shows), len(slugs))
        return shows

    def _fetch_detail(self, slug: str) -> list[Show]:
        url = f"{self.base_url}/framsyningar/{slug}"
        r = self.get(url)
        soup = BeautifulSoup(r.text, "lxml")
        events = self._extract_theater_events(soup)
        if not events:
            return []
        out: list[Show] = []
        # Cleaned-up title fallback from the first event
        for ev in events:
            try:
                start_dt = self._iso(ev.get("startDate"))
                end_dt = self._iso(ev.get("endDate"))
            except Exception:
                continue
            if not start_dt:
                continue
            title = self._clean_title(ev.get("name") or slug.replace("-", " ").title())
            offer = ev.get("offers") or {}
            if isinstance(offer, list):
                offer = offer[0] if offer else {}
            ticket_url = offer.get("url") or url
            image = ev.get("image") or {}
            if isinstance(image, list):
                image = image[0] if image else {}
            image_url = image.get("url") if isinstance(image, dict) else None
            location = ev.get("location") or {}
            if isinstance(location, list):
                location = location[0] if location else {}
            stage = None
            if isinstance(location, dict):
                loc_name = location.get("name") or ""
                # "Det Norske Teatret - Hovudscenen" → "Hovudscenen"
                if "-" in loc_name:
                    stage = loc_name.split("-", 1)[1].strip()
                else:
                    stage = loc_name.strip() or None
            description = ev.get("description")
            out.append(Show(
                id=self.make_id(self.venue_slug, slug, start_dt.isoformat()),
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                stage=stage,
                start=start_dt,
                end=end_dt,
                description=description,
                image_url=image_url,
                ticket_url=ticket_url,
                detail_url=url,
            ))
        return out

    def _extract_theater_events(self, soup: BeautifulSoup) -> list[dict]:
        events: list[dict] = []
        for s in soup.find_all("script", type="application/ld+json"):
            if not s.string:
                continue
            try:
                data = json.loads(s.string)
            except Exception:
                continue
            for d in self._iter_objects(data):
                if d.get("@type") == "TheaterEvent":
                    events.append(d)
        return events

    @staticmethod
    def _iter_objects(data):
        if isinstance(data, list):
            for item in data:
                yield from DetNorskeTeatretScraper._iter_objects(item)
        elif isinstance(data, dict):
            yield data
            graph = data.get("@graph")
            if isinstance(graph, list):
                for item in graph:
                    yield from DetNorskeTeatretScraper._iter_objects(item)

    @staticmethod
    def _iso(value):
        if not value:
            return None
        # Drop the timezone offset; we store naive local datetimes elsewhere
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt

    @staticmethod
    def _clean_title(title: str) -> str:
        title = re.sub(r"\s+", " ", title or "").strip()
        # Listing cards (not used now, but be safe) sometimes prepend ALL-CAPS category.
        new = CATEGORY_PREFIXES.sub("", title)
        return new or title
