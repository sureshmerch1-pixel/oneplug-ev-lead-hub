
# OnePlug EV Lead Hub

A lightweight EV-charging lead dashboard for OnePlug.

## What it does

- Keeps EV installation requirements, tenders and partnership opportunities in one place.
- Every lead has a clickable **Open lead** link to the original website.
- Auto-syncs configured sources on a schedule.
- Supports Google Alerts / RSS feeds.
- Supports simple public-webpage monitoring.
- Detects EV-charging + buyer/installation intent keywords.
- Gives higher priority to Tamil Nadu / Karnataka / Bengaluru terms.
- Deduplicates matching leads.
- Lets sales staff change status: New → Contacted → Qualified → Proposal → Won/Lost.
- Exports the lead table to CSV.
- Includes starter leads for Coimbatore Railway Station, Elamanur Railway Station, RoadNest, PATH Recharge and Travlounge.

## Important limitation

No software can reliably pull **all** internet leads automatically without source access. Some websites require login, CAPTCHA, paid API access, or prohibit scraping.

This app therefore uses:
1. RSS / Google Alerts where possible.
2. Official/public feeds and APIs when available.
3. Public webpage monitoring only where the site's terms permit it.
4. Manual entry for private/login-only leads.

Always open and verify an auto-discovered lead before contacting or bidding.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: http://localhost:8000

## Deploy

The project includes a Dockerfile. Deploy it on any Docker/Python host (Render, Railway, Fly.io, a VPS, AWS, Azure, GCP, etc.).

Set:
- `PORT` — normally supplied by the host.
- `SYNC_MINUTES=30` — how often feeds are checked.
- `DATABASE_PATH=/persistent/path/leads.db` — use a persistent disk in production.

For a multi-user production system, migrate SQLite to PostgreSQL and add login/roles.

## Best automatic source: Google Alerts RSS

Create Google Alerts such as:

- `"EV charging station required"`
- `"looking for EV charging partner"`
- `"EV charger installation requirement"`
- `"EV charging" tender Tamil Nadu`
- `"EV charging" RFP Tamil Nadu`
- `"EV charging" EOI Tamil Nadu`
- `"EV charging" tender Karnataka`
- `"EV charging" Bengaluru`
- `"EV charging" "wayside amenities"`
- `"EV charging" railway station Tamil Nadu`

Set delivery to RSS, copy the feed URL, and add it under **Auto Sources**.

## Data quality

The matching engine requires:
- at least one EV term (EV charging, EV charger, charging station, etc.), and
- at least one intent term (tender, RFP, EOI, requirement, looking for, partner, install, bid, auction, operate, maintain, etc.).

It adds location weight for Tamil Nadu and Karnataka terms.

## Security / compliance

- Do not store passwords or private portal credentials in source URLs.
- Prefer official feeds/APIs.
- Respect website terms, robots rules and applicable law.
- Paid tender portals may require licensed API access rather than scraping.
