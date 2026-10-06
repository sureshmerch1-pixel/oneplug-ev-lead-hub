
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



## Neon + Render setup (recommended free starter setup)

This version supports both:
- Neon PostgreSQL in production via `DATABASE_URL`.
- Local SQLite automatically when `DATABASE_URL` is not set.

### Neon
1. Create a Neon project.
2. Click **Connect**.
3. Copy the PostgreSQL connection string (pooled is fine).
4. Keep it private.

### GitHub
Upload this project's files to a GitHub repository.
Do not add the Neon password/connection string to GitHub.

### Render
1. New -> Web Service.
2. Connect your GitHub repository.
3. Runtime/Language: Docker.
4. Choose the Free instance if available.
5. Add environment variable:
   - Key: `DATABASE_URL`
   - Value: paste your full Neon connection string
6. Add:
   - Key: `SYNC_MINUTES`
   - Value: `30`
7. Health check path: `/health`
8. Create Web Service.

After deployment, visit:
`https://YOUR-SERVICE.onrender.com/health`

A successful setup returns JSON similar to:
`{"ok": true, "database": "connected"}`

Then open the service root URL to use the dashboard.

### Keep secrets private
Never paste the `DATABASE_URL` into source code, screenshots, public chats, or GitHub.
