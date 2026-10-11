"""SQLite persistence with versioned migrations."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 9  # == len(_MIGRATIONS); bump when adding a migration

_MIGRATIONS: list[str] = ["""
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
""", """
CREATE TABLE IF NOT EXISTS candidate_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, email TEXT, phone TEXT,
    country TEXT, city TEXT,
    target_countries TEXT, work_arrangements TEXT,
    skills_extracted TEXT, skills_inferred TEXT,
    education TEXT, experience_years REAL, languages TEXT,
    target_titles TEXT, employment_types TEXT,
    salary_expectation TEXT, summary TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
""", """
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    type TEXT NOT NULL, label TEXT, coverage TEXT,
    docs_url TEXT, access_requirements TEXT, rate_limit TEXT,
    last_success_at TEXT, last_verified_at TEXT, health TEXT
);
""", """
CREATE TABLE IF NOT EXISTS jobs (
    canonical_id TEXT PRIMARY KEY,
    title TEXT NOT NULL, employer TEXT NOT NULL,
    source_name TEXT NOT NULL, source_url TEXT NOT NULL,
    original_posting_url TEXT, apply_url TEXT, employer_website TEXT,
    location TEXT, country TEXT, remote_type TEXT, employment_type TEXT,
    salary_min REAL, salary_max REAL, salary_currency TEXT, deadline TEXT,
    description_text TEXT,
    contact_email TEXT, contact_phone TEXT, contact_evidence_url TEXT,
    verification_status TEXT NOT NULL, verification_evidence TEXT,
    verification_checked_at TEXT,
    match_score REAL, match_breakdown TEXT,
    eligibility_status TEXT, eligibility_notes TEXT,
    discovered_at TEXT NOT NULL, last_verified_at TEXT,
    content_hash TEXT, is_active INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_jobs_employer ON jobs(employer);
CREATE INDEX IF NOT EXISTS idx_jobs_verification ON jobs(verification_status);
CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score DESC);
""", """
CREATE TABLE IF NOT EXISTS verification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_canonical_id TEXT NOT NULL, checked_at TEXT NOT NULL,
    status TEXT NOT NULL, evidence TEXT, source_url TEXT,
    FOREIGN KEY(job_canonical_id) REFERENCES jobs(canonical_id)
);
CREATE INDEX IF NOT EXISTS idx_verif_job ON verification_events(job_canonical_id);
""", """
CREATE TABLE IF NOT EXISTS search_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL,
    sources_ok TEXT, sources_failed TEXT,
    jobs_found INTEGER DEFAULT 0, jobs_new INTEGER DEFAULT 0
);
""", """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_canonical_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Saved',
    notes TEXT, applied_at TEXT, follow_up_at TEXT, updated_at TEXT NOT NULL,
    FOREIGN KEY(job_canonical_id) REFERENCES jobs(canonical_id)
);
""", """
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL, sent_at TEXT NOT NULL,
    payload TEXT, status TEXT NOT NULL
);
""", """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT
);
"""]


def connect(db_path: str | Path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection) -> int:
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
    cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
    current = cur.fetchone()[0]
    for i in range(current, SCHEMA_VERSION):
        for stmt in _MIGRATIONS[i].strip().split(";\n"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        from datetime import datetime, timezone
        cur.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (i + 1, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return SCHEMA_VERSION


def _j(value: Any) -> str:
    return json.dumps(value or [])


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ---- jobs ----
    def upsert_job(self, job_row: dict) -> bool:
        """Insert or update. Returns True if the row is new."""
        cur = self.conn.cursor()
        cur.execute("SELECT content_hash FROM jobs WHERE canonical_id = ?", (job_row["canonical_id"],))
        existing = cur.fetchone()
        cols = ", ".join(job_row.keys())
        placeholders = ", ".join("?" for _ in job_row)
        updates = ", ".join(f"{c} = excluded.{c}" for c in job_row if c != "canonical_id")
        cur.execute(
            f"INSERT INTO jobs ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(canonical_id) DO UPDATE SET {updates}",
            tuple(job_row.values()),
        )
        self.conn.commit()
        return existing is None

    def get_job(self, canonical_id: str):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM jobs WHERE canonical_id = ?", (canonical_id,))
        return cur.fetchone()

    def list_jobs(self, where: str = "1=1", order: str = "match_score DESC",
                  limit: int = 100, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM jobs WHERE {where} ORDER BY {order} LIMIT ?", (*params, limit))
        return cur.fetchall()

    # ---- sources ----
    def upsert_source(self, name: str, type_: str, label: str, coverage: str,
                      docs_url: str, health: str, checked_at: str):
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO sources (name, type, label, coverage, docs_url, health, last_success_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET health=excluded.health,
               last_success_at=excluded.last_success_at""",
            (name, type_, label, coverage, docs_url, health, checked_at),
        )
        self.conn.commit()

    def list_sources(self):
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM sources ORDER BY name")
        return cur.fetchall()

    # ---- runs / events / applications ----
    def record_run(self, started_at: str, finished_at: str, status: str,
                   sources_ok: list, sources_failed: dict,
                   jobs_found: int, jobs_new: int) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO search_runs (started_at, finished_at, status, sources_ok,
               sources_failed, jobs_found, jobs_new) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (started_at, finished_at, status, _j(sources_ok),
             json.dumps(sources_failed), jobs_found, jobs_new),
        )
        self.conn.commit()
        return cur.lastrowid

    def add_verification_event(self, job_id: str, checked_at: str, status: str,
                               evidence: str, source_url: str):
        cur = self.conn.cursor()
        cur.execute(
            """INSERT INTO verification_events (job_canonical_id, checked_at, status, evidence, source_url)
               VALUES (?, ?, ?, ?, ?)""",
            (job_id, checked_at, status, evidence, source_url),
        )
        self.conn.commit()

    def add_audit(self, actor: str, action: str, detail: str = ""):
        from datetime import datetime, timezone
        cur = self.conn.cursor()
        cur.execute("INSERT INTO audit_events (at, actor, action, detail) VALUES (?, ?, ?, ?)",
                    (datetime.now(timezone.utc).isoformat(), actor, action, detail))
        self.conn.commit()

    # ---- application tracker ----
    def upsert_application(self, job_id: str, status: str = "Saved",
                           notes: str = "", follow_up_at: str = "") -> int:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM applications WHERE job_canonical_id = ?", (job_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE applications SET status=?, notes=?, follow_up_at=?, updated_at=?
                   WHERE id=?""",
                (status, notes, follow_up_at, now, row["id"]),
            )
            self.conn.commit()
            return row["id"]
        cur.execute(
            """INSERT INTO applications (job_canonical_id, status, notes, follow_up_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (job_id, status, notes, follow_up_at, now),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_applications(self):
        cur = self.conn.cursor()
        cur.execute(
            """SELECT a.*, j.title, j.employer, j.location, j.remote_type,
                      j.apply_url, j.match_score
               FROM applications a JOIN jobs j ON j.canonical_id = a.job_canonical_id
               ORDER BY a.updated_at DESC""")
        return cur.fetchall()

    def delete_application(self, app_id: int):
        self.conn.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        self.conn.commit()

    # ---- privacy / data deletion ----
    def clear_jobs(self):
        self.conn.execute("DELETE FROM verification_events")
        self.conn.execute("DELETE FROM applications")
        self.conn.execute("DELETE FROM jobs")
        self.conn.commit()

    def clear_profile(self):
        self.conn.execute("DELETE FROM candidate_profiles")
        self.conn.commit()
