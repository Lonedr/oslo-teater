from __future__ import annotations

import logging
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .base import BaseScraper, Show, fetch_rendered, parse_nb_date, to_datetime

log = logging.getLogger(__name__)

OSLO_TZ = ZoneInfo("Europe/Oslo")

# Ticketmaster artist page embeds an "events" array. We extract title/id/start/venue/soldOut
# via a structural regex rather than parsing the entire page JSON.
_TM_EVENT_RE = re.compile(
    r'"title":"(?P<title>[^"]+)",'
    r'"id":"(?P<id>\d+)",'
    r'.*?"dates":\{[^}]*?"startDate":"(?P<start>[^"]+)"[^}]*?\}'
    r'.*?"url":"(?P<url>[^"]+)"'
    r'.*?"venue":\{"city":"[^"]*","name":"(?P<venue>[^"]+)"'
    r'.*?"soldOut":(?P<sold>true|false)',
    re.DOTALL,
)


class OsloNyeScraper(BaseScraper):
    venue = "Oslo Nye Teater"
    venue_slug = "oslo-nye"
    base_url = "https://oslonye.no"
    program_url = "https://oslonye.no/forestillinger/"

    def fetch(self) -> list[Show]:
        # Listing is JS-rendered; detail pages are static
        listing_html = fetch_rendered(self.program_url, settle_ms=1500)
        soup = BeautifulSoup(listing_html, "lxml")
        items = soup.select("div.item")
        log.info("Oslo Nye: %d listing items", len(items))
        slugs: list[tuple[str, str, str | None, str | None]] = []  # slug, detail_url, listing_image, listing_stage
        seen: set[str] = set()
        for item in items:
            link = item.select_one('a.img-link-cover[href*="/forestillinger/"]')
            if not link:
                continue
            detail_url = link["href"]
            slug = detail_url.rstrip("/").split("/")[-1]
            if slug in seen:
                continue
            seen.add(slug)
            stage_el = item.select_one(".location > div")
            stage = stage_el.get_text(strip=True).capitalize() if stage_el else None
            img_div = item.select_one(".image-cover")
            image_url = None
            if img_div and img_div.get("style"):
                m = re.search(r"url\(['\"]?([^'\")]+)['\"]?\)", img_div["style"])
                if m:
                    image_url = m.group(1)
            slugs.append((slug, detail_url, image_url, stage))

        shows: list[Show] = []
        for slug, detail_url, listing_image, listing_stage in slugs:
            try:
                shows.extend(self._fetch_detail(slug, detail_url, listing_image, listing_stage))
            except Exception:
                log.exception("Oslo Nye detail %s failed", slug)
        log.info("Oslo Nye: %d shows", len(shows))
        return shows

    def _fetch_detail(
        self,
        slug: str,
        url: str,
        listing_image: str | None,
        listing_stage: str | None,
    ) -> list[Show]:
        r = self.get(url)
        soup = BeautifulSoup(r.text, "lxml")

        title_el = soup.find("h1") or soup.select_one(".title")
        title = title_el.get_text(" ", strip=True) if title_el else slug.replace("-", " ").title()
        title = re.sub(r"\s+", " ", title).strip()

        premiere_text = siste_text = None
        for fg in soup.select(".form-group"):
            label = fg.find("label")
            ans = fg.find(class_="ans")
            if not label or not ans:
                continue
            ltxt = label.get_text(" ", strip=True).lower()
            atxt = ans.get_text(" ", strip=True)
            if "premieredato" in ltxt:
                premiere_text = atxt
            elif "siste spilledato" in ltxt:
                siste_text = atxt

        start_date = parse_nb_date(premiere_text or "")
        end_date = parse_nb_date(siste_text or "") if siste_text else None
        if not start_date:
            return []
        if end_date and end_date == start_date:
            end_date = None

        # Stage from form-group "scene"
        stage = listing_stage
        for fg in soup.select(".form-group"):
            label = fg.find("label")
            ans = fg.find(class_="ans")
            if not label or not ans:
                continue
            if "scene" in label.get_text(strip=True).lower():
                stage = ans.get_text(" ", strip=True) or stage
                break

        # Description: meta description
        description = None
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            description = md["content"].strip() or None

        image_url = listing_image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            image_url = og["content"]

        # Find a Ticketmaster artist link (per-show page lists individual events)
        artist_link = None
        for a in soup.select('a[href*="ticketmaster"]'):
            href = a.get("href", "")
            if "/artist/" in href and "alle-scener" not in href:
                artist_link = href
                break

        # Try to expand to per-occurrence shows via Ticketmaster
        if artist_link:
            try:
                tm_shows = self._fetch_ticketmaster(
                    artist_link, slug, title, stage, description, image_url, url
                )
                if tm_shows:
                    return tm_shows
            except Exception as e:
                log.debug("Oslo Nye: Ticketmaster expand failed for %s: %s", slug, e)

        # Fallback: single Show with run-period range
        ticket = soup.select_one('a[href*="ticketmaster"], a[href*="billett"], a.btn-buy, a[href*="tickets"]')
        ticket_url = ticket["href"] if ticket else url
        return [
            Show(
                id=self.make_id(self.venue_slug, slug),
                title=title,
                venue=self.venue,
                venue_slug=self.venue_slug,
                stage=stage,
                start=to_datetime(start_date),
                end=to_datetime(end_date) if end_date else None,
                description=description,
                image_url=image_url,
                ticket_url=ticket_url,
                detail_url=url,
            )
        ]

    def _fetch_ticketmaster(
        self,
        artist_url: str,
        slug: str,
        title: str,
        stage: str | None,
        description: str | None,
        image_url: str | None,
        detail_url: str,
    ) -> list[Show]:
        r = self.get(artist_url)
        html = r.text
        shows: list[Show] = []
        seen: set[str] = set()
        for m in _TM_EVENT_RE.finditer(html):
            event_id = m.group("id")
            if event_id in seen:
                continue
            seen.add(event_id)
            try:
                # startDate is e.g. "2026-09-16T19:00:00Z" (UTC). Convert to Europe/Oslo.
                start_iso = m.group("start").replace("Z", "+00:00")
                dt_utc = datetime.fromisoformat(start_iso)
                dt_local = dt_utc.astimezone(OSLO_TZ).replace(tzinfo=None)
            except ValueError:
                continue
            sold_out = m.group("sold") == "true"
            ticket_url = m.group("url")
            shows.append(
                Show(
                    id=self.make_id(self.venue_slug, slug, dt_local.isoformat()),
                    title=title,
                    venue=self.venue,
                    venue_slug=self.venue_slug,
                    stage=stage,
                    start=dt_local,
                    description=description,
                    image_url=image_url,
                    ticket_url=ticket_url,
                    detail_url=detail_url,
                    sold_out=sold_out,
                )
            )
        return shows
