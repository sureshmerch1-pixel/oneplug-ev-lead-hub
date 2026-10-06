
import os, re, sqlite3, hashlib
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(APP_DIR, "leads.db"))
SYNC_MINUTES = int(os.environ.get("SYNC_MINUTES", "30"))
USER_AGENT = os.environ.get("USER_AGENT", "OnePlugLeadHub/1.0 (+business lead monitoring)")

app = Flask(__name__)

EV_TERMS = [
    "ev charging", "electric vehicle charging", "ev charger", "charging station",
    "charge point", "charging infrastructure", "cpo", "fast charger"
]
INTENT_TERMS = [
    "tender", "rfp", "eoi", "expression of interest", "requirement", "required",
    "looking for", "seeking", "partner", "install", "installation", "establish",
    "operate", "maintain", "bid", "auction", "procurement", "supply"
]
PRIORITY_LOCATIONS = [
    "tamil nadu", "coimbatore", "chennai", "salem", "trichy", "tiruchirappalli",
    "madurai", "hosur", "krishnagiri", "vellore", "erode", "tiruppur",
    "karnataka", "bengaluru", "bangalore", "mysuru", "mysore", "tumakuru"
]

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    );
    CREATE TABLE IF NOT EXISTS sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        source_type TEXT NOT NULL DEFAULT 'rss',
        enabled INTEGER NOT NULL DEFAULT 1,
        last_sync TEXT DEFAULT '',
        last_result TEXT DEFAULT ''
    );
    """)
    conn.commit()
    seed(conn)
    conn.close()

def seed(conn):
    seeds = [
        {
            "title":"Establish, operate & maintain EV charging point — Coimbatore Railway Station",
            "company":"Southern Railway",
            "location":"Coimbatore, Tamil Nadu",
            "category":"Tender / Railway",
            "intent":"Operator required for EV charging point; 5-year period; 60 sq.m.",
            "priority":"A+++",
            "status":"New",
            "source_name":"TenderDetail",
            "source_url":"https://www.tenderdetail.com/State-tenders/tamil-nadu-tenders/ev-charging-station-tenders",
            "lead_url":"https://www.tenderdetail.com/State-tenders/tamil-nadu-tenders/ev-charging-station-tenders",
            "deadline":"2026-10-20",
            "notes":"Verify tender documents and eligibility before bidding."
        },
        {
            "title":"Establish, operate & maintain EV charging point — Elamanur Railway Station",
            "company":"Southern Railway",
            "location":"Elamanur, Tamil Nadu",
            "category":"Tender / Railway",
            "intent":"Operator required for EV charging point; 5-year period; 100 sq.m.",
            "priority":"A+++",
            "status":"New",
            "source_name":"TenderDetail",
            "source_url":"https://www.tenderdetail.com/Indian-Tenders/TenderNotice/57614118/602097584a0930f76df81aefa3e13ec4",
            "lead_url":"https://www.tenderdetail.com/Indian-Tenders/TenderNotice/57614118/602097584a0930f76df81aefa3e13ec4",
            "deadline":"2026-10-08",
            "notes":"Urgent: verify current closing time and submission requirements."
        },
        {
            "title":"EV infrastructure partnership opportunity",
            "company":"RoadNest",
            "location":"Gundlupet / South India",
            "category":"Private Partnership",
            "intent":"Publicly invites EV infrastructure partners for highway hospitality network.",
            "priority":"A+++",
            "status":"New",
            "source_name":"RoadNest",
            "source_url":"https://roadnest.in/partners/",
            "lead_url":"https://roadnest.in/partners/",
            "notes":"Strong private-sector highway hospitality lead."
        },
        {
            "title":"Highway recharge / wayside site partnership — Trichy",
            "company":"PATH Recharge",
            "location":"Trichy, Tamil Nadu",
            "category":"Travel Lounge / WSA",
            "intent":"EV charging is part of planned highway amenity offering.",
            "priority":"A++",
            "status":"New",
            "source_name":"PATH Recharge",
            "source_url":"https://www.pathrecharge.com/",
            "lead_url":"https://www.pathrecharge.com/",
            "notes":"Approach as charging infrastructure/operator partner."
        },
        {
            "title":"Travel lounge expansion partnership",
            "company":"Travlounge",
            "location":"South India",
            "category":"Travel Lounge",
            "intent":"Highway lounge model includes EV fast charging and partner expansion.",
            "priority":"A++",
            "status":"New",
            "source_name":"Travlounge",
            "source_url":"https://www.travlounge.com/",
            "lead_url":"https://www.travlounge.com/",
            "notes":"Target new locations, franchise/land partner developments and additional charging capacity."
        },
    ]
    for x in seeds:
        add_lead(conn, x)

def uid_for(title, url):
    raw = (title.strip().lower() + "|" + url.strip().lower()).encode()
    return hashlib.sha256(raw).hexdigest()[:24]

def add_lead(conn, x):
    title = (x.get("title") or "Untitled lead").strip()
    lead_url = (x.get("lead_url") or x.get("source_url") or "").strip()
    if not lead_url:
        return False
    uid = uid_for(title, lead_url)
    fields = {
        "uid": uid, "title": title, "company": x.get("company",""),
        "location": x.get("location",""), "category": x.get("category",""),
        "intent": x.get("intent",""), "priority": x.get("priority","B"),
        "status": x.get("status","New"), "source_name": x.get("source_name",""),
        "source_url": x.get("source_url",""), "lead_url": lead_url,
        "published_at": x.get("published_at",""), "deadline": x.get("deadline",""),
        "notes": x.get("notes",""),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    try:
        conn.execute("""
        INSERT INTO leads(uid,title,company,location,category,intent,priority,status,
        source_name,source_url,lead_url,published_at,deadline,notes,created_at)
        VALUES(:uid,:title,:company,:location,:category,:intent,:priority,:status,
        :source_name,:source_url,:lead_url,:published_at,:deadline,:notes,:created_at)
        """, fields)
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def score_text(text):
    t = re.sub(r"\s+", " ", (text or "").lower())
    ev = sum(1 for k in EV_TERMS if k in t)
    intent = sum(1 for k in INTENT_TERMS if k in t)
    loc = sum(1 for k in PRIORITY_LOCATIONS if k in t)
    score = ev*4 + intent*2 + loc*3
    if ev == 0 or intent == 0:
        return 0, "C"
    priority = "A+++" if score >= 15 else "A++" if score >= 11 else "A+" if score >= 8 else "A" if score >= 6 else "B"
    return score, priority

def location_hint(text):
    lower = (text or "").lower()
    hits = [x for x in PRIORITY_LOCATIONS if x in lower]
    return ", ".join(dict.fromkeys(h.title() for h in hits[:3]))

def sync_rss(source):
    feed = feedparser.parse(source["url"], request_headers={"User-Agent": USER_AGENT})
    new_count = 0
    conn = db()
    for e in feed.entries[:100]:
        title = getattr(e, "title", "") or ""
        summary = getattr(e, "summary", "") or ""
        link = getattr(e, "link", "") or source["url"]
        text = BeautifulSoup(title + " " + summary, "html.parser").get_text(" ", strip=True)
        score, priority = score_text(text)
        if score == 0:
            continue
        if add_lead(conn, {
            "title": title[:500],
            "location": location_hint(text),
            "category": "Auto-discovered",
            "intent": text[:900],
            "priority": priority,
            "source_name": source["name"],
            "source_url": source["url"],
            "lead_url": link,
            "published_at": getattr(e, "published", "") or getattr(e, "updated", ""),
            "notes": f"Auto-added from RSS. Match score: {score}. Verify requirement before outreach."
        }):
            new_count += 1
    conn.close()
    return new_count

def sync_html(source):
    r = requests.get(source["url"], timeout=20, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    new_count = 0
    conn = db()
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(source["url"], a["href"])
        title = a.get_text(" ", strip=True)
        parent = a.parent.get_text(" ", strip=True) if a.parent else title
        text = (title + " " + parent)[:3000]
        if not title or href in seen:
            continue
        seen.add(href)
        score, priority = score_text(text)
        if score == 0:
            continue
        if add_lead(conn, {
            "title": title[:500],
            "location": location_hint(text),
            "category": "Auto-discovered",
            "intent": parent[:900],
            "priority": priority,
            "source_name": source["name"],
            "source_url": source["url"],
            "lead_url": href,
            "notes": f"Auto-added from public webpage. Match score: {score}. Verify source terms and requirement."
        }):
            new_count += 1
    conn.close()
    return new_count

def sync_all():
    conn = db()
    sources = conn.execute("SELECT * FROM sources WHERE enabled=1").fetchall()
    conn.close()
    total = 0
    for s in sources:
        result = ""
        try:
            if s["source_type"] == "rss":
                n = sync_rss(s)
            elif s["source_type"] == "html":
                n = sync_html(s)
            else:
                n = 0
                result = "Unsupported source type"
            total += n
            result = result or f"OK — {n} new lead(s)"
        except Exception as e:
            result = f"Error: {str(e)[:180]}"
        conn = db()
        conn.execute("UPDATE sources SET last_sync=?, last_result=? WHERE id=?",
                     (datetime.now(timezone.utc).isoformat(timespec="seconds"), result, s["id"]))
        conn.commit()
        conn.close()
    return total

@app.route("/")
def index():
    return render_template("index.html")

@app.get("/api/leads")
def leads():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()]
    conn.close()
    return jsonify(rows)

@app.post("/api/leads")
def create_lead():
    data = request.get_json(force=True)
    conn = db()
    ok = add_lead(conn, data)
    conn.close()
    return jsonify({"ok": ok}), 201 if ok else 409

@app.patch("/api/leads/<int:lead_id>")
def update_lead(lead_id):
    data = request.get_json(force=True)
    allowed = {"status","priority","notes","company","location","category","deadline"}
    sets, values = [], []
    for k,v in data.items():
        if k in allowed:
            sets.append(f"{k}=?"); values.append(v)
    if not sets: return jsonify({"ok":False}), 400
    values.append(lead_id)
    conn = db()
    conn.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id=?", values)
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.delete("/api/leads/<int:lead_id>")
def delete_lead(lead_id):
    conn = db()
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.get("/api/sources")
def sources():
    conn = db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM sources ORDER BY id DESC").fetchall()]
    conn.close()
    return jsonify(rows)

@app.post("/api/sources")
def create_source():
    d = request.get_json(force=True)
    conn = db()
    try:
        conn.execute("INSERT INTO sources(name,url,source_type,enabled) VALUES(?,?,?,1)",
                     (d["name"].strip(), d["url"].strip(), d.get("source_type","rss")))
        conn.commit()
        return jsonify({"ok":True}), 201
    except sqlite3.IntegrityError:
        return jsonify({"ok":False,"error":"Source URL already exists"}), 409
    finally:
        conn.close()

@app.patch("/api/sources/<int:source_id>")
def update_source(source_id):
    d = request.get_json(force=True)
    enabled = 1 if d.get("enabled") else 0
    conn = db()
    conn.execute("UPDATE sources SET enabled=? WHERE id=?", (enabled, source_id))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.delete("/api/sources/<int:source_id>")
def delete_source(source_id):
    conn = db()
    conn.execute("DELETE FROM sources WHERE id=?", (source_id,))
    conn.commit(); conn.close()
    return jsonify({"ok":True})

@app.post("/api/sync")
def api_sync():
    return jsonify({"ok":True, "new_leads":sync_all()})

@app.get("/health")
def health():
    return jsonify({"ok":True})

init_db()
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(sync_all, "interval", minutes=SYNC_MINUTES, id="lead_sync", replace_existing=True)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8000")), debug=False)
