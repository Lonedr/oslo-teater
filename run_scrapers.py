#!/usr/bin/env python3
"""Run all scrapers and write a unified shows.json file consumed by the static site."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scrapers import load_all_scrapers
from scrapers.base import close_browser

CUTOFF = datetime.now() - timedelta(days=1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run")


def main() -> int:
    scraper_classes = load_all_scrapers()
    all_shows: list[dict] = []
    venues: dict[str, dict] = {}
    errors: list[dict] = []

    for cls in scraper_classes:
        scraper = cls()
        log.info("Running %s …", cls.__name__)
        try:
            shows = scraper.fetch()
            # Drop past shows (no end date that's already past, or start that's well in the past)
            future = [s for s in shows if (s.end or s.start) >= CUTOFF]
            log.info("  → %d shows (%d after dropping past)", len(shows), len(future))
            shows = future
            for s in shows:
                all_shows.append(json.loads(s.model_dump_json()))
            venues[scraper.venue_slug] = {
                "slug": scraper.venue_slug,
                "name": scraper.venue,
                "url": scraper.base_url,
                "show_count": len(shows),
            }
        except Exception as exc:
            log.exception("  ✗ %s failed", cls.__name__)
            errors.append({"scraper": cls.__name__, "error": str(exc)})
            venues[scraper.venue_slug] = {
                "slug": scraper.venue_slug,
                "name": scraper.venue,
                "url": scraper.base_url,
                "show_count": 0,
                "error": str(exc),
            }

    # Sort by start date
    all_shows.sort(key=lambda s: s["start"])

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "show_count": len(all_shows),
        "venues": list(venues.values()),
        "shows": all_shows,
        "errors": errors,
    }

    out_path = Path(__file__).parent / "data" / "shows.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    # Also write a copy into site/ so GitHub Pages can serve it relative to the static page
    site_path = Path(__file__).parent / "site" / "shows.json"
    site_path.write_text(json.dumps(out, ensure_ascii=False, default=str))

    log.info("Wrote %d shows from %d venues to %s", len(all_shows), len(venues), out_path)
    if errors:
        log.warning("%d scrapers errored", len(errors))
    close_browser()
    return 0


if __name__ == "__main__":
    sys.exit(main())
