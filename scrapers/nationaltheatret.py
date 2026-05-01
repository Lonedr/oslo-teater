from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, Show

log = logging.getLogger(__name__)


# Regex helpers — Nationaltheatret pages embed React Server Components data
# with backslash-escaped quotes. The patterns below operate on the raw HTML.

# productionId UUID appears just before the slug in the RSC stream:
#   "<UUID>",[],{...},"<slug>"
def _production_id_pattern(slug: str) -> re.Pattern[str]:
    return re.compile(
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
        r".{1,200}?" + re.escape(slug),
        re.DOTALL,
    )


# seasonIds appear after the literal "tessituraSeasonIds",[refs],<id>,<id>,...,"type"
SEASON_IDS_RE = re.compile(r'tessituraSeasonIds\\",\[[^\]]*\],([\d,]+),\\"type')

FIRST_PERF_RE = re.compile(r'firstPerformanceDate\\",\\"([0-9T:+\-]+)\\"')
LAST_PERF_RE = re.compile(r'lastPerformanceDate\\",\\"([0-9T:+\-]+)\\"')

API_URL = "https://www.nationaltheatret.no/api/trpc/calendar.getCalendar"


class NationaltheatretScraper(BaseScraper):
    venue = "Nationaltheatret"
    venue_slug = "nationaltheatret"
    base_url = "https://www.nationaltheatret.no"
    program_url = "https://www.nationaltheatret.no/program/"

    def fetch(self) -> list[Show]:
        r = self.get(self.program_url)
        soup = BeautifulSoup(r.text, "lxml")
        cards = soup.select('article[class*="programCard_"]')
        log.info("Nationaltheatret: found %d cards", len(cards))

        # Collect unique slugs
        slugs: list[str] = []
        seen: set[str] = set()
        for card in cards:
            link = card.find("a", href=True)
            if not link:
                continue
            href = link["href"].split("#")[0]
            if not href.startswith("/forestillinger/"):
                continue
            if href in seen:
                continue
            seen.add(href)
            slugs.append(href)

        log.info("Nationaltheatret: %d unique productions", len(slugs))

        shows: list[Show] = []
        for href in slugs:
            try:
                shows.extend(self._fetch_production(href))
            except Exception as e:
                log.warning("Nationaltheatret: failed %s: %s", href, e)
        log.info("Nationaltheatret: %d total performances", len(shows))
        return shows

    # ---- detail page + tRPC expansion ----------------------------------------

    def _fetch_production(self, slug_path: str) -> list[Show]:
        detail_url = urljoin(self.base_url, slug_path)
        slug = slug_path.rstrip("/").split("/")[-1]
        r = self.get(detail_url)
        html = r.text
        soup = BeautifulSoup(html, "lxml")

        # productionId
        m = _production_id_pattern(slug).search(html)
        if not m:
            log.warning("Nationaltheatret: no productionId for %s", slug)
            return []
        production_id = m.group(1)

        # seasonIds
        m_s = SEASON_IDS_RE.search(html)
        season_ids: list[int] = []
        if m_s:
            season_ids = [int(x) for x in m_s.group(1).split(",") if x]
        else:
            log.debug("Nationaltheatret: no seasonIds for %s", slug)

        # First/last performance dates — used to bound month scan
        first_iso = (FIRST_PERF_RE.search(html) or [None, None])[1] if FIRST_PERF_RE.search(html) else None
        last_iso = (LAST_PERF_RE.search(html) or [None, None])[1] if LAST_PERF_RE.search(html) else None
        first_dt = _parse_iso(first_iso) if first_iso else None
        last_dt = _parse_iso(last_iso) if last_iso else None

        # Base info: title, stage, image, description
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else slug.replace("-", " ").title()

        # The first vare-scener/<slug> link with non-empty text. Sub-pages like
        # /vare-scener/torshovteatret/torsdag-pa-torshov can render before the
        # canonical scene link, so we look for the first link with text.
        stage = None
        for a in soup.find_all("a", href=re.compile(r"vare-scener/")):
            txt = a.get_text(strip=True)
            if txt and txt.lower() not in {"les mer→", "les mer"}:
                stage = txt
                break

        image_url = None
        for img in soup.find_all("img"):
            src = img.get("src")
            if src and "cdn.sanity.io" in src:
                # Strip ?w= etc params for cleaner URLs
                image_url = src.split("?")[0]
                break

        description = None
        rm = soup.select_one('[class*="readMore"]')
        if rm:
            description = rm.get_text(" ", strip=True)
            if len(description) > 300:
                description = description[:297] + "…"

        ticket_url = detail_url + "#billetter"

        # Determine month range. Default 0..12 if dates unknown.
        if first_dt and last_dt:
            today = date.today()
            ref_month = today.replace(day=1)
            first_month = first_dt.replace(day=1)
            last_month = last_dt.replace(day=1)
            start_offset = max(0, _months_between(ref_month, first_month))
            end_offset = _months_between(ref_month, last_month)
        else:
            start_offset, end_offset = 0, 12

        # Cap at reasonable range
        start_offset = max(0, start_offset)
        end_offset = min(end_offset, 24)

        # Collect all performance datetimes from API
        performances: list[tuple[datetime, dict]] = []
        for offset in range(start_offset, end_offset + 1):
            try:
                month_data = self._call_calendar_api(production_id, season_ids, offset)
            except Exception as e:
                log.debug("Nationaltheatret: API offset=%d failed for %s: %s", offset, slug, e)
                continue
            for date_str, occurrences in (month_data or {}).items():
                for occ in occurrences:
                    dt = _parse_iso(occ.get("dateTime"))
                    if dt:
                        performances.append((dt, occ))

        # Dedupe by datetime
        performances = sorted({(dt, json.dumps(occ, sort_keys=True)): (dt, occ) for dt, occ in performances}.values())

        if not performances:
            # Fallback: emit one Show with first/last range so listing is not empty
            if first_dt:
                return [
                    Show(
                        id=self.make_id(self.venue_slug, slug, str(first_dt)),
                        title=title,
                        venue=self.venue,
                        venue_slug=self.venue_slug,
                        stage=stage,
                        start=first_dt.replace(tzinfo=None),
                        end=last_dt.replace(tzinfo=None) if last_dt else None,
                        description=description,
                        image_url=image_url,
                        ticket_url=ticket_url,
                        detail_url=detail_url,
                    )
                ]
            return []

        shows: list[Show] = []
        for dt, occ in performances:
            ticket_path = (occ.get("ticketing") or {}).get("href")
            occ_ticket = urljoin(self.base_url, ticket_path) if ticket_path else ticket_url
            sold_out = occ.get("salesAvailability") == 0
            naive_dt = dt.replace(tzinfo=None)
            shows.append(
                Show(
                    id=self.make_id(self.venue_slug, slug, dt.isoformat()),
                    title=title,
                    venue=self.venue,
                    venue_slug=self.venue_slug,
                    stage=stage,
                    start=naive_dt,
                    description=description,
                    image_url=image_url,
                    ticket_url=occ_ticket,
                    detail_url=detail_url,
                    sold_out=sold_out,
                )
            )
        return shows

    def _call_calendar_api(
        self, production_id: str, season_ids: list[int], month_offset: int
    ) -> dict:
        payload = {
            "0": {
                "json": {
                    "productionId": production_id,
                    "monthOffset": month_offset,
                    "seasonIds": season_ids,
                }
            }
        }
        params = {"batch": "1", "input": json.dumps(payload, separators=(",", ":"))}
        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        r = self.session.get(url, timeout=20)
        r.raise_for_status()
        data = r.json()
        if not data or "result" not in data[0]:
            return {}
        return data[0]["result"]["data"]["json"].get("dates") or {}


# ---- module helpers ----------------------------------------------------------


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        # fromisoformat handles "2026-06-04T19:30:00+02:00" on Python 3.11+; older
        # versions need the colon-removing trick.
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            # Strip the colon in the timezone offset for older Python
            if len(s) >= 6 and s[-3] == ":":
                s2 = s[:-3] + s[-2:]
                return datetime.fromisoformat(s2)
        except ValueError:
            pass
    return None


def _months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)
