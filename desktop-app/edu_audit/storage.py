"""SQLite storage for organizations, audit runs, pages and findings."""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "gosweb_audit.sqlite3"
ORGANIZATIONS_FILE = ROOT / "data" / "organizations.json"


def connect(db_path=None):
    path = Path(db_path or DEFAULT_DB).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def initialize(db_path=None):
    with connect(db_path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS organizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            kind TEXT NOT NULL CHECK(kind IN ('school','garden')),
            url TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            is_reference INTEGER NOT NULL DEFAULT 0,
            fact_sources_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES organizations(id),
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            finished_at TEXT,
            pages_count INTEGER NOT NULL DEFAULT 0,
            findings_json TEXT NOT NULL DEFAULT '[]',
            pages_json TEXT NOT NULL DEFAULT '[]',
            meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS ix_runs_org_id ON runs(org_id);
        CREATE INDEX IF NOT EXISTS ix_runs_created_at ON runs(created_at);
        """)
        # Lightweight schema migration for databases created by an earlier desktop build.
        columns = {row["name"] for row in db.execute("PRAGMA table_info(organizations)")}
        if "is_reference" not in columns:
            db.execute("ALTER TABLE organizations ADD COLUMN is_reference INTEGER NOT NULL DEFAULT 0")
            columns.add("is_reference")
        if "fact_sources_json" not in columns:
            db.execute("ALTER TABLE organizations ADD COLUMN fact_sources_json TEXT NOT NULL DEFAULT '[]'")


def seed_organizations(db_path=None, json_path=None):
    path = Path(json_path or ORGANIZATIONS_FILE)
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    with connect(db_path) as db:
        for item in data:
            kind = item.get("kind")
            if kind not in ("school", "garden"):
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO organizations(name,kind,url,source) VALUES(?,?,?,?)",
                (item["name"], kind, item["url"], item.get("source", "")),
            )
            count += cursor.rowcount
    return count


def list_organizations(db_path=None, kind=None, query=""):
    sql = "SELECT * FROM organizations WHERE enabled=1"
    params = []
    if kind in ("school", "garden"):
        sql += " AND kind=?"
        params.append(kind)
    sql += " ORDER BY kind, name"
    with connect(db_path) as db:
        rows = [dict(row) for row in db.execute(sql, params).fetchall()]
    normalized_query = _normalize_search(query)
    if normalized_query:
        tokens = normalized_query.split()
        rows = [row for row in rows
                if all(token in _normalize_search(row["name"]) for token in tokens)]
    for row in rows:
        try:
            row["fact_sources"] = json.loads(row.pop("fact_sources_json", "[]"))
        except (TypeError, ValueError):
            row["fact_sources"] = []
    return rows


def _normalize_search(value):
    """Normalize Russian text for literal, case-insensitive registry search."""
    value = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", value).strip()


def save_run(report, db_path=None):
    with connect(db_path) as db:
        cursor = db.execute(
            """INSERT INTO runs(org_id,status,created_at,finished_at,pages_count,findings_json,pages_json,meta_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                report["organization"]["id"], report["status"], report["created_at"],
                report.get("finished_at"), len(report.get("pages", [])),
                json.dumps(report.get("findings", []), ensure_ascii=False),
                json.dumps(report.get("pages", []), ensure_ascii=False),
                json.dumps(report.get("meta", {}), ensure_ascii=False),
            ),
        )
        report["id"] = cursor.lastrowid
        return cursor.lastrowid


def list_history(db_path=None, limit=100):
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT runs.id, organizations.name, organizations.kind, organizations.url,
                      runs.status, runs.created_at, runs.pages_count
               FROM runs JOIN organizations ON organizations.id=runs.org_id
               ORDER BY runs.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def list_latest_reports(db_path=None):
    """Load the latest completed audit for each enabled organization."""
    with connect(db_path) as db:
        rows = db.execute(
            """SELECT runs.id FROM runs
               JOIN organizations ON organizations.id=runs.org_id
               WHERE organizations.enabled=1 AND runs.status='completed'
                 AND runs.id=(SELECT MAX(latest.id) FROM runs latest
                              WHERE latest.org_id=runs.org_id AND latest.status='completed')
               ORDER BY organizations.kind, organizations.name"""
        ).fetchall()
    return [load_run(row["id"], db_path) for row in rows]


def load_run(run_id, db_path=None):
    with connect(db_path) as db:
        row = db.execute(
            """SELECT runs.*, organizations.name, organizations.kind, organizations.url
               FROM runs JOIN organizations ON organizations.id=runs.org_id
               WHERE runs.id=?""", (run_id,)
        ).fetchone()
    if not row:
        return None
    report = dict(row)
    report["organization"] = {
        "id": report.pop("org_id"), "name": report.pop("name"),
        "kind": report.pop("kind"), "url": report.pop("url"),
    }
    report["findings"] = json.loads(report.pop("findings_json"))
    report["pages"] = json.loads(report.pop("pages_json"))
    report["meta"] = json.loads(report.pop("meta_json"))
    return report


def set_reference(org_id, db_path=None):
    """Select one reference site per institution kind."""
    with connect(db_path) as db:
        org = db.execute("SELECT id, kind FROM organizations WHERE id=? AND enabled=1", (org_id,)).fetchone()
        if not org:
            raise ValueError("Учреждение не найдено.")
        db.execute("UPDATE organizations SET is_reference=0 WHERE kind=?", (org["kind"],))
        db.execute("UPDATE organizations SET is_reference=1 WHERE id=?", (org_id,))


def get_reference(kind, db_path=None):
    with connect(db_path) as db:
        row = db.execute(
            "SELECT * FROM organizations WHERE kind=? AND is_reference=1 AND enabled=1 LIMIT 1",
            (kind,),
        ).fetchone()
        return dict(row) if row else None


def latest_completed_run(org_id, db_path=None):
    with connect(db_path) as db:
        row = db.execute(
            "SELECT id FROM runs WHERE org_id=? AND status='completed' ORDER BY id DESC LIMIT 1",
            (org_id,),
        ).fetchone()
    return load_run(row["id"], db_path) if row else None



def set_fact_sources(org_id, urls, db_path=None):
    """Store up to five user-configured public HTTP source URLs."""
    from .crawler import normalize_url
    cleaned = []
    for value in urls:
        if not str(value).strip():
            continue
        url = normalize_url(str(value))
        if url not in cleaned:
            cleaned.append(url)
    if len(cleaned) > 5:
        raise ValueError("Можно указать не более пяти внешних источников.")
    with connect(db_path) as db:
        changed = db.execute(
            "UPDATE organizations SET fact_sources_json=? WHERE id=? AND enabled=1",
            (json.dumps(cleaned, ensure_ascii=False), org_id),
        ).rowcount
        if not changed:
            raise ValueError("Учреждение не найдено.")



def set_setting(key, value, db_path=None):
    """Persist local application settings as JSON in SQLite."""
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO app_settings(key,value_json) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (str(key), json.dumps(value, ensure_ascii=False)),
        )


def get_setting(key, db_path=None, default=None):
    with connect(db_path) as db:
        row = db.execute("SELECT value_json FROM app_settings WHERE key=?", (str(key),)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, ValueError):
        return default
