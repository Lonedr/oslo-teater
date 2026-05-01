# Teater i Oslo

Aggregert oversikt over teaterforestillinger i Osloområdet. Python-scrapere kjører
daglig via GitHub Actions, henter forestillinger fra hvert teater, lagrer dem i
`data/shows.json` og en statisk HTML-side viser dem med filtrering, søk og
iCal-eksport. Hver forestilling lenker direkte til teatrets egen billettside.

## Status per teater

Alle 11 teatre er implementert. Listing-sider rendres med Playwright når de er
JS-baserte; detaljsider hentes med vanlige `requests` der det er mulig.

| Teater | Listing | Detaljsider | Datakilde for datoer |
|---|---|---|---|
| Nationaltheatret | requests | requests + tRPC API | `calendar.getCalendar` API per måned — én rad per spilling |
| Det Norske Teatret | Playwright | requests | JSON-LD `TheaterEvent` per forestilling — én rad per spilling |
| Oslo Nye Teater | Playwright | requests + Ticketmaster | Per-show events fra Ticketmaster — én rad per spilling |
| Black Box teater | requests | — | Header-kalender med eksakte tider |
| Den Norske Opera & Ballett | Playwright | requests | `li.event` på detaljside — én rad per spilling |
| Dramatikkens Hus | requests | — | Alle kalenderoppføringer; arkiv filtreres bort |
| Riksteatret | requests | requests | Turné — `nav-program__item` filtrert på Oslo (Nydalen, Vega Scene) |
| Det Andre Teatret | requests | — | Program gruppert per dag, med eksakte tider |
| Teater Manu | requests | requests | Turné — `tr.show-row` filtrert på `.show-city` = Oslo |
| Nordic Black Theatre | Playwright | — | Dato hentes fra slug (DD-MM-YYYY) |
| Folketeateret | Playwright | requests | `<div class="line">`-oppføringer på detaljside — én rad per spilling |

## Lokal utvikling

```bash
# Sett opp Python-miljø
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Installer Chromium for Playwright (kreves av JS-baserte scrapere)
python -m playwright install chromium

# Kjør scraperne
python run_scrapers.py

# Test frontend lokalt
cd site && python3 -m http.server 8000
# Åpne http://localhost:8000
```

## Prosjektstruktur

```
oslo-teater/
├── scrapers/
│   ├── base.py              # Show-modell, BaseScraper, dato-parsing
│   ├── nationaltheatret.py  # En modul per teater
│   ├── black_box.py
│   └── ...
├── run_scrapers.py          # Orkestrator — kjører alle, skriver shows.json
├── site/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── shows.json           # Genereres av orkestrator
├── data/shows.json          # Speilkopi for git-historikk
├── .github/workflows/scrape.yml
└── requirements.txt
```

## Datamodell

Hver forestilling har feltene:

```python
{
  "id": "stable-hash",
  "title": "Gi meg hånden",
  "venue": "Nationaltheatret",
  "venue_slug": "nationaltheatret",
  "stage": "Hovedscenen",
  "start": "2026-03-26T19:00:00",
  "end":   "2026-09-05T19:00:00",  # Optional
  "description": "...",
  "image_url": "https://...",
  "ticket_url": "https://nationaltheatret.no/forestillinger/...#billetter",
  "detail_url": "https://nationaltheatret.no/forestillinger/...",
  "genre": null,
  "scraped_at": "2026-05-01T..."
}
```

## Legge til en ny scraper

1. Lag `scrapers/<teater>.py`:
   ```python
   from .base import BaseScraper, Show, parse_nb_date_range, to_datetime
   from bs4 import BeautifulSoup

   class MittTeaterScraper(BaseScraper):
       venue = "Mitt Teater"
       venue_slug = "mitt-teater"
       base_url = "https://mitt-teater.no"

       def fetch(self) -> list[Show]:
           soup = BeautifulSoup(self.get(self.base_url + "/program").text, "lxml")
           shows = []
           for card in soup.select(".show-card"):
               # parse og lag Show-objekter
               ...
           return shows
   ```
2. Registrer scraperen i `scrapers/__init__.py` (i `load_all_scrapers()`).
3. Kjør `python run_scrapers.py` lokalt og verifiser.

## Hvordan bruke Playwright i en scraper

`scrapers/base.py` eksponerer `fetch_rendered(url)` som returnerer post-render HTML:

```python
from .base import BaseScraper, Show, fetch_rendered

class MittTeaterScraper(BaseScraper):
    def fetch(self) -> list[Show]:
        html = fetch_rendered(self.program_url, settle_ms=2000)
        ...
```

Browser-instansen gjenbrukes på tvers av alle scrapere i samme orkestrator-kjøring,
så det er rimelig effektivt selv med flere JS-baserte scrapere.

## Deployment via GitHub Pages

1. Push prosjektet til et GitHub-repo.
2. I repo Settings → Pages → Source: **GitHub Actions**.
3. Workflowen kjører hver dag kl 05:00 UTC, oppdaterer `shows.json` og
   redeployer Pages.
4. Trigger manuelt fra Actions-fanen ved behov (`workflow_dispatch`).

## Robusthet

- Hver scraper kjøres isolert; én som feiler stopper ikke de andre.
- Forestillinger med utløpt sluttdato filtreres bort i orkestratoren.
- Skraperne forsøker å være motstandsdyktige mot mindre HTML-endringer
  (bruker klasse-prefiks som `[class*="programCard_"]` mot CSS-modules-hasher).

## Etterord

Når en av sidene endres i layout, vil scraperen kunne knekke. Sjekk
`debug_html/` (lokalt) eller logs fra GitHub Actions-runnen for å se hva som
skjedde, og oppdater den aktuelle scraperen.

## Lisens

MIT.
