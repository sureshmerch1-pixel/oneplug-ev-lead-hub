import os
import re
import hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# ============================================================
# ONEPLUG EV LEAD HUB
# Strict lead-intent version
# Keeps tenders / RFP / EOI / vendor requirement / installation
# Rejects generic partnership and EV-news articles.
# ============================================================

APP_DIR = os.path.dirname(os.path.abspath(__file__))

DATABASE_URL = os.environ.get("DATABASE_URL")

# Local fallback for development only
if not DATABASE_URL:
    local_db = os.environ.get(
        "DATABASE_PATH",
        os.path.join(APP_DIR, "leads.db")
    )
    DATABASE_URL = f"sqlite:///{local_db}"

# Some providers may still issue postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

SYNC_MINUTES = int(os.environ.get("SYNC_MINUTES", "30"))

USER_AGENT = os.environ.get(
    "USER_AGENT",
    "OnePlugLeadHub/2.0 (+EV charging procurement lead monitoring)"
)

engine_kwargs = {
    "pool_pre_ping": True
}

if DATABASE_URL.startswith("sqlite:"):
    engine_kwargs["connect_args"] = {
        "check_same_thread": False
    }

engine = create_engine(
    DATABASE_URL,
    future=True,
    **engine_kwargs
)

app = Flask(__name__)


# ============================================================
# FILTER SETTINGS
# ============================================================

# Must contain EV charging context
EV_TERMS = [
    "ev charging",
    "electric vehicle charging",
    "ev charger",
    "ev chargers",
    "charging station",
    "charging stations",
    "charging infrastructure",
    "charge point",
    "charge points",
    "fast charger",
    "fast charging station",
    "public charging station",
    "evcs"
]

# These are true buying / tender / installation signals.
# "partner" is intentionally NOT included.
STRONG_INTENT_TERMS = [
    "tender",
    "tender notice",
    "inviting tender",
    "invites tender",
    "invitation for tender",

    "rfp",
    "request for proposal",

    "eoi",
    "expression of interest",

    "rfq",
    "request for quotation",
    "quotation invited",
    "inviting quotation",
    "invites quotation",

    "requirement",
    "required",
    "requirement for ev charging",
    "ev charger required",
    "charging station required",

    "vendor required",
    "vendor requirement",
    "empanelment of vendors",
    "vendor empanelment",

    "supplier required",
    "installer required",
    "installation required",
    "contractor required",
    "operator required",
    "cpo required",

    "inviting bids",
    "invites bids",
    "invitation for bid",
    "bid submission",
    "bidder",
    "bidding document",

    "procurement",
    "procure",
    "purchase order",

    "supply and installation",
    "supply, installation",
    "supply installation",
    "installation and commissioning",
    "supply and commissioning",

    "establish operate maintain",
    "establish, operate and maintain",
    "operate and maintain",
    "operation and maintenance",
    "operation & maintenance",
    "o&m",

    "design supply installation",
    "design, supply, installation",

    "lease for ev charging",
    "license for ev charging",
    "space for ev charging",
    "site for ev charging station",

    "looking for vendor",
    "looking for supplier",
    "looking for installer",
    "looking for cpo",
    "seeking vendor",
    "seeking supplier",
    "seeking installer"
]

# Extra-strong procurement terms
HARD_PROCUREMENT_TERMS = [
    "tender",
    "rfp",
    "request for proposal",
    "eoi",
    "expression of interest",
    "rfq",
    "request for quotation",
    "quotation invited",
    "inviting bids",
    "invites bids",
    "invitation for bid",
    "procurement",
    "vendor required",
    "operator required",
    "supplier required",
    "installer required",
    "supply and installation",
    "installation and commissioning",
    "establish, operate and maintain",
    "operate and maintain"
]

# Generic news / partnership language that should NOT become a lead
NEWS_NOISE_TERMS = [
    "partners with",
    "partner with",
    "partner to",
    "partnership",
    "strategic partnership",
    "announces partnership",
    "announce partnership",

    "collaboration",
    "collaborates with",
    "collaborated with",

    "signs mou",
    "signed mou",
    "memorandum of understanding",

    "strategic alliance",
    "alliance with",

    "launches",
    "launched",
    "launch of",

    "roll out",
    "rollout",
    "rolls out",

    "expands network",
    "expand network",
    "expansion of network",

    "inaugurates",
    "inaugurated",
    "opens new charging",
    "opened new charging",

    "announces new charging",
    "announced new charging",

    "investment",
    "raises funding",
    "funding round",

    "market report",
    "industry report",
    "market growth"
]

# Location weighting for OnePlug focus
PRIORITY_LOCATIONS = [
    "tamil nadu",
    "tamilnadu",
    "coimbatore",
    "chennai",
    "salem",
    "trichy",
    "tiruchirappalli",
    "madurai",
    "hosur",
    "krishnagiri",
    "vellore",
    "erode",
    "tiruppur",
    "karur",
    "dindigul",
    "kanchipuram",
    "sriperumbudur",

    "karnataka",
    "bengaluru",
    "bangalore",
    "mysuru",
    "mysore",
    "tumakuru",
    "hubballi",
    "mangaluru"
]


# ============================================================
# DATABASE HELPERS
# ============================================================

def rows_as_dicts(result):
    return [dict(row) for row in result.mappings().all()]


def init_db():
    postgres_statements = [
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            company TEXT DEFAULT '',
            location TEXT DEFAULT '',
            category TEXT DEFAULT '',
            intent TEXT DEFAULT '',
            priority TEXT DEFAULT 'B',
            status TEXT DEFAULT 'New',
            source_name TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            lead_url TEXT NOT NULL,
            published_at TEXT DEFAULT '',
            deadline TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'rss',
            enabled INTEGER NOT NULL DEFAULT 1,
            last_sync TEXT DEFAULT '',
            last_result TEXT DEFAULT ''
        )
        """
    ]

    if DATABASE_URL.startswith("sqlite:"):
        statements = [
            postgres_statements[0].replace(
                "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                "INTEGER PRIMARY KEY AUTOINCREMENT"
            ),
            postgres_statements[1].replace(
                "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
                "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
        ]
    else:
        statements = postgres_statements

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))

    seed_confirmed_leads()

    # Remove old partnership/news rows from earlier versions
    cleanup_old_noise_leads()


def seed_confirmed_leads():
    """
    Only seed true tender/installation requirement examples.
    No generic partnership leads are seeded.
    """

    seeds = [
        {
            "title": "Establish, operate & maintain EV charging point — Coimbatore Railway Station",
            "company": "Southern Railway",
            "location": "Coimbatore, Tamil Nadu",
            "category": "Tender / Railway",
            "intent": (
                "Requirement to establish, operate and maintain "
                "an EV charging point."
            ),
            "priority": "A+++",
            "status": "New",
            "source_name": "TenderDetail",
            "source_url": (
                "https://www.tenderdetail.com/State-tenders/"
                "tamil-nadu-tenders/ev-charging-station-tenders"
            ),
            "lead_url": (
                "https://www.tenderdetail.com/State-tenders/"
                "tamil-nadu-tenders/ev-charging-station-tenders"
            ),
            "deadline": "2026-10-20",
            "notes": (
                "Verify tender documents, closing time and eligibility "
                "before bidding."
            )
        },
        {
            "title": "Establish, operate & maintain EV charging point — Elamanur Railway Station",
            "company": "Southern Railway",
            "location": "Elamanur, Tamil Nadu",
            "category": "Tender / Railway",
            "intent": (
                "Requirement to establish, operate and maintain "
                "an EV charging point."
            ),
            "priority": "A+++",
            "status": "New",
            "source_name": "TenderDetail",
            "source_url": (
                "https://www.tenderdetail.com/Indian-Tenders/"
                "TenderNotice/57614118/602097584a0930f76df81aefa3e13ec4"
            ),
            "lead_url": (
                "https://www.tenderdetail.com/Indian-Tenders/"
                "TenderNotice/57614118/602097584a0930f76df81aefa3e13ec4"
            ),
            "deadline": "2026-10-08",
            "notes": (
                "Verify current tender deadline and submission "
                "requirements."
            )
        }
    ]

    for item in seeds:
        add_lead(item)


def uid_for(title_value, url):
    raw = (
        title_value.strip().lower()
        + "|"
        + url.strip().lower()
    ).encode()

    return hashlib.sha256(raw).hexdigest()[:24]


def add_lead(data):
    title_value = (
        data.get("title")
        or "Untitled lead"
    ).strip()

    lead_url = (
        data.get("lead_url")
        or data.get("source_url")
        or ""
    ).strip()

    if not lead_url:
        return False

    fields = {
        "uid": uid_for(title_value, lead_url),
        "title": title_value,
        "company": data.get("company", ""),
        "location": data.get("location", ""),
        "category": data.get("category", ""),
        "intent": data.get("intent", ""),
        "priority": data.get("priority", "B"),
        "status": data.get("status", "New"),
        "source_name": data.get("source_name", ""),
        "source_url": data.get("source_url", ""),
        "lead_url": lead_url,
        "published_at": data.get("published_at", ""),
        "deadline": data.get("deadline", ""),
        "notes": data.get("notes", ""),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat(timespec="seconds")
    }

    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO leads(
                        uid,
                        title,
                        company,
                        location,
                        category,
                        intent,
                        priority,
                        status,
                        source_name,
                        source_url,
                        lead_url,
                        published_at,
                        deadline,
                        notes,
                        created_at
                    )
                    VALUES(
                        :uid,
                        :title,
                        :company,
                        :location,
                        :category,
                        :intent,
                        :priority,
                        :status,
                        :source_name,
                        :source_url,
                        :lead_url,
                        :published_at,
                        :deadline,
                        :notes,
                        :created_at
                    )
                """),
                fields
            )

        return True

    except IntegrityError:
        # Duplicate lead
        return False


# ============================================================
# LEAD CLASSIFICATION
# ============================================================

def normalize(value):
    return re.sub(
        r"\s+",
        " ",
        (value or "").lower()
    ).strip()


def classify_text(value):
    """
    Returns:
        (score, priority, reason)

    A lead must contain:
    1. EV charging context
    2. Strong procurement / installation intent

    Partnership/news language is rejected unless the same text
    also contains a hard procurement term such as tender / RFP.
    """

    t = normalize(value)

    ev_matches = [
        term
        for term in EV_TERMS
        if term in t
    ]

    intent_matches = [
        term
        for term in STRONG_INTENT_TERMS
        if term in t
    ]

    hard_matches = [
        term
        for term in HARD_PROCUREMENT_TERMS
        if term in t
    ]

    noise_matches = [
        term
        for term in NEWS_NOISE_TERMS
        if term in t
    ]

    location_matches = [
        term
        for term in PRIORITY_LOCATIONS
        if term in t
    ]

    # Must mention EV charging
    if not ev_matches:
        return 0, "C", "No EV charging context"

    # Must contain true buyer / tender / installation intent
    if not intent_matches:
        return 0, "C", "No strong procurement intent"

    # Reject normal partnership/news articles
    # unless they also contain hard procurement language.
    if noise_matches and not hard_matches:
        return 0, "C", "Rejected as partnership/news"

    score = (
        len(ev_matches) * 4
        + len(intent_matches) * 7
        + len(hard_matches) * 6
        + len(location_matches) * 3
    )

    if score >= 30:
        priority = "A+++"

    elif score >= 22:
        priority = "A++"

    elif score >= 15:
        priority = "A+"

    else:
        priority = "A"

    reason = (
        "Matched: "
        + ", ".join(
            list(dict.fromkeys(
                intent_matches + location_matches
            ))[:8]
        )
    )

    return score, priority, reason


def location_hint(value):
    lower = normalize(value)

    hits = [
        term
        for term in PRIORITY_LOCATIONS
        if term in lower
    ]

    readable = []

    for hit in hits[:3]:
        readable.append(
            hit.title()
        )

    return ", ".join(
        dict.fromkeys(readable)
    )


# ============================================================
# CLEAN OLD PARTNERSHIP / NEWS LEADS
# ============================================================

def cleanup_old_noise_leads():
    """
    Deletes old non-manual leads that would no longer pass the
    stricter filter.

    Manual leads are never deleted automatically.
    """

    with engine.connect() as conn:
        rows = rows_as_dicts(
            conn.execute(
                text("""
                    SELECT
                        id,
                        title,
                        intent,
                        notes,
                        source_name
                    FROM leads
                """)
            )
        )

    ids_to_delete = []

    for row in rows:
        # Never delete manually-entered leads automatically
        if row.get("source_name") == "Manual":
            continue

        combined = " ".join([
            row.get("title") or "",
            row.get("intent") or "",
            row.get("notes") or ""
        ])

        score, _, _ = classify_text(combined)

        if score == 0:
            ids_to_delete.append(
                row["id"]
            )

    if ids_to_delete:
        with engine.begin() as conn:
            for lead_id in ids_to_delete:
                conn.execute(
                    text(
                        "DELETE FROM leads WHERE id=:id"
                    ),
                    {"id": lead_id}
                )


# ============================================================
# RSS / WEBSITE SYNC
# ============================================================

def sync_rss(source):
    feed = feedparser.parse(
        source["url"],
        request_headers={
            "User-Agent": USER_AGENT
        }
    )

    new_count = 0

    for entry in feed.entries[:100]:

        title_value = (
            getattr(
                entry,
                "title",
                ""
            )
            or ""
        )

        summary = (
            getattr(
                entry,
                "summary",
                ""
            )
            or ""
        )

        link = (
            getattr(
                entry,
                "link",
                ""
            )
            or source["url"]
        )

        combined = BeautifulSoup(
            title_value
            + " "
            + summary,
            "html.parser"
        ).get_text(
            " ",
            strip=True
        )

        score, priority, reason = classify_text(
            combined
        )

        if score == 0:
            continue

        published = (
            getattr(
                entry,
                "published",
                ""
            )
            or getattr(
                entry,
                "updated",
                ""
            )
            or ""
        )

        created = add_lead({
            "title": title_value[:500],
            "location": location_hint(
                combined
            ),
            "category": "Auto-discovered",
            "intent": combined[:900],
            "priority": priority,
            "status": "New",
            "source_name": source["name"],
            "source_url": source["url"],
            "lead_url": link,
            "published_at": published,
            "notes": (
                f"Auto-added. Match score: {score}. "
                f"{reason}. "
                "Open the original source and verify "
                "eligibility/deadline before outreach."
            )
        })

        if created:
            new_count += 1

    return new_count


def sync_html(source):
    response = requests.get(
        source["url"],
        timeout=20,
        headers={
            "User-Agent": USER_AGENT
        }
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    new_count = 0
    seen = set()

    for a in soup.find_all(
        "a",
        href=True
    ):

        href = urljoin(
            source["url"],
            a["href"]
        )

        title_value = a.get_text(
            " ",
            strip=True
        )

        if not title_value:
            continue

        if href in seen:
            continue

        seen.add(href)

        parent_text = (
            a.parent.get_text(
                " ",
                strip=True
            )
            if a.parent
            else title_value
        )

        combined = (
            title_value
            + " "
            + parent_text
        )[:4000]

        score, priority, reason = classify_text(
            combined
        )

        if score == 0:
            continue

        created = add_lead({
            "title": title_value[:500],
            "location": location_hint(
                combined
            ),
            "category": "Auto-discovered",
            "intent": parent_text[:900],
            "priority": priority,
            "status": "New",
            "source_name": source["name"],
            "source_url": source["url"],
            "lead_url": href,
            "notes": (
                f"Auto-added from public webpage. "
                f"Match score: {score}. "
                f"{reason}. "
                "Verify the requirement before contacting."
            )
        })

        if created:
            new_count += 1

    return new_count


def sync_all():
    with engine.connect() as conn:
        sources = rows_as_dicts(
            conn.execute(
                text("""
                    SELECT *
                    FROM sources
                    WHERE enabled=1
                """)
            )
        )

    total = 0

    for source in sources:

        result_message = ""

        try:
            if source["source_type"] == "rss":
                count = sync_rss(
                    source
                )

            elif source["source_type"] == "html":
                count = sync_html(
                    source
                )

            else:
                count = 0
                result_message = (
                    "Unsupported source type"
                )

            total += count

            if not result_message:
                result_message = (
                    f"OK — {count} "
                    "new qualified lead(s)"
                )

        except Exception as exc:
            result_message = (
                "Error: "
                + str(exc)[:180]
            )

        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE sources
                    SET
                        last_sync=:last_sync,
                        last_result=:last_result
                    WHERE id=:id
                """),
                {
                    "last_sync": datetime.now(
                        timezone.utc
                    ).isoformat(
                        timespec="seconds"
                    ),
                    "last_result": result_message,
                    "id": source["id"]
                }
            )

    return total


# ============================================================
# WEB ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template(
        "index.html"
    )


@app.get("/api/leads")
def get_leads():
    with engine.connect() as conn:
        rows = rows_as_dicts(
            conn.execute(
                text("""
                    SELECT *
                    FROM leads
                    ORDER BY id DESC
                """)
            )
        )

    return jsonify(
        rows
    )


@app.post("/api/leads")
def create_lead():
    data = request.get_json(
        force=True
    )

    ok = add_lead(
        data
    )

    return jsonify({
        "ok": ok
    }), 201 if ok else 409


@app.patch("/api/leads/<int:lead_id>")
def update_lead(lead_id):
    data = request.get_json(
        force=True
    )

    allowed = {
        "status",
        "priority",
        "notes",
        "company",
        "location",
        "category",
        "deadline"
    }

    chosen = {
        key: value
        for key, value
        in data.items()
        if key in allowed
    }

    if not chosen:
        return jsonify({
            "ok": False
        }), 400

    assignments = ", ".join(
        f"{key}=:{key}"
        for key in chosen
    )

    chosen["id"] = lead_id

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                UPDATE leads
                SET {assignments}
                WHERE id=:id
                """
            ),
            chosen
        )

    return jsonify({
        "ok": True
    })


@app.delete("/api/leads/<int:lead_id>")
def delete_lead(lead_id):
    with engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM leads WHERE id=:id"
            ),
            {
                "id": lead_id
            }
        )

    return jsonify({
        "ok": True
    })


@app.get("/api/sources")
def get_sources():
    with engine.connect() as conn:
        rows = rows_as_dicts(
            conn.execute(
                text("""
                    SELECT *
                    FROM sources
                    ORDER BY id DESC
                """)
            )
        )

    return jsonify(
        rows
    )


@app.post("/api/sources")
def create_source():
    data = request.get_json(
        force=True
    )

    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO sources(
                        name,
                        url,
                        source_type,
                        enabled
                    )
                    VALUES(
                        :name,
                        :url,
                        :source_type,
                        1
                    )
                """),
                {
                    "name": data[
                        "name"
                    ].strip(),
                    "url": data[
                        "url"
                    ].strip(),
                    "source_type": data.get(
                        "source_type",
                        "rss"
                    )
                }
            )

        return jsonify({
            "ok": True
        }), 201

    except IntegrityError:
        return jsonify({
            "ok": False,
            "error": (
                "Source URL already exists"
            )
        }), 409


@app.patch("/api/sources/<int:source_id>")
def update_source(source_id):
    data = request.get_json(
        force=True
    )

    enabled = (
        1
        if data.get("enabled")
        else 0
    )

    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE sources
                SET enabled=:enabled
                WHERE id=:id
            """),
            {
                "enabled": enabled,
                "id": source_id
            }
        )

    return jsonify({
        "ok": True
    })


@app.delete("/api/sources/<int:source_id>")
def delete_source(source_id):
    with engine.begin() as conn:
        conn.execute(
            text("""
                DELETE FROM sources
                WHERE id=:id
            """),
            {
                "id": source_id
            }
        )

    return jsonify({
        "ok": True
    })


@app.post("/api/sync")
def api_sync():
    new_leads = sync_all()

    return jsonify({
        "ok": True,
        "new_leads": new_leads
    })


@app.post("/api/cleanup")
def api_cleanup():
    """
    Optional button/API use:
    re-check old non-manual leads against the strict filter.
    """

    before = 0
    after = 0

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) AS c FROM leads"
            )
        ).mappings().first()

        before = result["c"]

    cleanup_old_noise_leads()

    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT COUNT(*) AS c FROM leads"
            )
        ).mappings().first()

        after = result["c"]

    return jsonify({
        "ok": True,
        "removed": before - after,
        "remaining": after
    })


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT 1"
                )
            )

        return jsonify({
            "ok": True,
            "database": "connected",
            "filter_mode": "strict_procurement_only"
        })

    except Exception as exc:
        return jsonify({
            "ok": False,
            "database": "error",
            "detail": str(exc)[:160]
        }), 500


# ============================================================
# STARTUP
# ============================================================

init_db()

scheduler = BackgroundScheduler(
    daemon=True
)

scheduler.add_job(
    sync_all,
    "interval",
    minutes=SYNC_MINUTES,
    id="lead_sync",
    replace_existing=True
)

scheduler.start()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                "8000"
            )
        ),
        debug=False
    )
