from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, parse_nb_date, to_datetime

log = logging.getLogger(__name__)


class DetAndreTeatretScraper(BaseScraper):
    venue = "Det Andre Teatret"
    venue_slug = "det-andre-teatret"
    base_url = "https://detandreteatret.no"
    program_url = "https://detandreteatret.no/program"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        # Find each day group: a .day-header followed by a .col-wrap containing .show-card elements
        day_headers = soup.select(".day-header")
        log.info("Det Andre Teatret: %d day groups", len(day_headers))
        shows: list[Show] = []
        seen: set[str] = set()
        for dh in day_headers:
            date_el = dh.select_one(".day-header__title b")
            date_text = date_el.get_text(strip=True) if date_el else None
            d = parse_nb_date(date_text or "")
            if not d:
                continue
            # Cards live in the next sibling .col-wrap (with class "lazy")
            day_wrap = dh.find_parent(class_="col-wrap")
            if not day_wrap:
                continue
            cards_wrap = day_wrap.find_next_sibling(class_="col-wrap")
            cards = cards_wrap.select(".show-card") if cards_wrap else []
            for card in cards:
                show = self._parse_card(card, d)
                if show and show.id not in seen:
                    seen.add(show.id)
                    shows.append(show)
        return shows

    def _parse_card(self, card, day) -> Show | None:
        link = card.select_one('a.link-cover[href*="/forestillinger/"]')
        if not link:
            return None
        href = link["href"]
        title_el = card.select_one(".show-card__container__content__top__title h3, .show-card__container__content__top__title")
        title = title_el.get_text(strip=True) if title_el else None
        if not title:
            return None
        subtitle_el = card.select_one(".show-card__container__content__top__subtitle")
        subtitle = subtitle_el.get_text(" ", strip=True) if subtitle_el else None
        info_el = card.select_one(".show-card__container__content__bottom__info")
        time_text = info_el.get_text("|", strip=True) if info_el else ""
        tm = re.search(r"(\d{1,2}):(\d{2})", time_text)
        hour = int(tm.group(1)) if tm else 19
        minute = int(tm.group(2)) if tm else 0
        # Stage is line after time
        stage = None
        if info_el:
            lines = [l.strip() for l in info_el.get_text("|", strip=True).split("|") if l.strip()]
            if len(lines) >= 2:
                stage = lines[-1]
        ticket = card.select_one('.show-card__container__content__bottom__buttons a[href]')
        ticket_url = ticket["href"] if ticket else href
        if ticket_url and not ticket_url.startswith("http"):
            ticket_url = urljoin(self.base_url, ticket_url)
        # Tag (genre)
        tag = card.select_one('.show-card__container__image__tags .tag')
        genre = tag.get_text(strip=True) if tag else None
        # Image
        img = card.find("img")
        image_url = img.get("src") if img else None
        if image_url and image_url.startswith("/"):
            image_url = urljoin(self.base_url, image_url)
        # Use spilletid as part of id
        spill = ""
        try:
            qs = urlparse(href).query
            spill = next((v for k, v in (p.split("=", 1) for p in qs.split("&") if "=" in p) if k == "spilletid"), "")
        except Exception:
            pass
        sid = self.make_id(self.venue_slug, href, str(day), str(hour), spill)
        return Show(
            id=sid,
            title=title,
            venue=self.venue,
            venue_slug=self.venue_slug,
            stage=stage,
            start=to_datetime(day, hour=hour, minute=minute),
            description=subtitle,
            image_url=image_url,
            ticket_url=ticket_url,
            detail_url=href,
            genre=genre,
        )
