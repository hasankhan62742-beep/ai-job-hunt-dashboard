"""Autonomous research orchestration.

Candidate Profile -> Discovery -> Normalization -> Dedupe -> Verification
-> Match/Eligibility -> Persistence -> Digest.

Deterministic code does validation, dedupe, policy and status assignment.
Idempotent: re-running a search only adds genuinely new or changed listings.
Checkpoints: search_runs rows record every run (ok / partial / failed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .config import Settings
from .cv import profile_from_dict
from .db import Store, connect, migrate
from .models import CandidateProfile, utcnow
from .pipeline.dedupe import dedupe
from .pipeline.match import score_job
from .pipeline.normalize import normalize
from .pipeline.verify import verify
from .security import redact_pii_for_logs
from .sources.registry import build_adapters, run_all


def load_profile(store: Store) -> CandidateProfile | None:
    cur = store.conn.cursor()
    cur.execute("SELECT * FROM candidate_profiles ORDER BY id DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return None
    return profile_from_dict({
        "name": row["name"], "email": row["email"], "phone": row["phone"],
        "country": row["country"], "city": row["city"],
        "target_countries": json.loads(row["target_countries"] or "[]"),
        "work_arrangements": json.loads(row["work_arrangements"] or '["remote"]'),
        "skills_extracted": json.loads(row["skills_extracted"] or "[]"),
        "skills_inferred": json.loads(row["skills_inferred"] or "[]"),
        "education": json.loads(row["education"] or "[]"),
        "experience_years": row["experience_years"],
        "languages": json.loads(row["languages"] or "[]"),
        "target_titles": json.loads(row["target_titles"] or "[]"),
        "employment_types": json.loads(row["employment_types"] or "[]"),
        "salary_expectation": row["salary_expectation"] or "",
        "summary": row["summary"] or "",
    })


def run_search(settings: Settings, check_live_verify: bool = True) -> dict:
    """Full research run. Returns a summary dict."""
    conn = connect(settings.db_path)
    migrate(conn)
    store = Store(conn)
    started = utcnow().isoformat()

    profile = load_profile(store)
    adapters = build_adapters(settings)
    results, failures = run_all(adapters, settings.max_jobs_per_source)

    ok_names, failed_names = [], {}
    for sc in settings.sources:
        healthy = sc.name in results
        store.upsert_source(sc.name, sc.type, sc.label, sc.coverage, sc.docs_url,
                            "ok" if healthy else "failed", started)
        if healthy:
            ok_names.append(sc.name)
        else:
            failed_names[sc.name] = failures.get(sc.name, "")

    raw_jobs = [rj for jobs in results.values() for rj in jobs]
    jobs = [normalize(rj) for rj in raw_jobs]
    unique, dup_reports = dedupe(jobs)

    verified = 0
    to_verify = unique[:settings.verify_max_per_run] if settings.verify_new_listings else []
    for job in to_verify:
        is_new = store.get_job(job.canonical_id) is None
        if is_new or check_live_verify:
            verify(job, timeout=15, check_live=check_live_verify)
            verified += 1
        store.add_verification_event(job.canonical_id, job.verification_checked_at,
                                     job.verification_status.value,
                                     job.verification_evidence, job.source_url)

    new_count = 0
    for job in unique:
        if profile:
            score_job(job, profile)
        row = {
            "canonical_id": job.canonical_id, "title": job.title, "employer": job.employer,
            "source_name": job.source_name, "source_url": job.source_url,
            "original_posting_url": job.original_posting_url, "apply_url": job.apply_url,
            "employer_website": job.employer_website, "location": job.location,
            "country": job.country, "remote_type": job.remote_type.value,
            "employment_type": job.employment_type, "salary_min": job.salary_min,
            "salary_max": job.salary_max, "salary_currency": job.salary_currency,
            "deadline": job.deadline, "description_text": job.description_text[:8000],
            "contact_email": job.contact_email, "contact_phone": job.contact_phone,
            "contact_evidence_url": job.contact_evidence_url,
            "verification_status": job.verification_status.value,
            "verification_evidence": job.verification_evidence,
            "verification_checked_at": job.verification_checked_at,
            "match_score": job.match_score,
            "match_breakdown": json.dumps(job.match_breakdown),
            "eligibility_status": job.eligibility_status.value,
            "eligibility_notes": json.dumps(job.eligibility_notes),
            "discovered_at": job.discovered_at, "last_verified_at": job.last_verified_at,
            "content_hash": job.content_hash, "is_active": 1 if job.is_active else 0,
        }
        if store.upsert_job(row):
            new_count += 1

    status = "ok" if not failures else ("partial" if ok_names else "failed")
    run_id = store.record_run(started, utcnow().isoformat(), status, ok_names,
                              {k: redact_pii_for_logs(v) for k, v in failures.items()},
                              len(unique), new_count)
    store.add_audit("agent", "search_run",
                    f"run={run_id} found={len(unique)} new={new_count} failed={list(failures)}")
    conn.close()
    return {"run_id": run_id, "status": status, "found": len(unique),
            "new": new_count, "duplicates": len(dup_reports),
            "verified": verified, "sources_ok": ok_names, "sources_failed": failures}


def build_digest(settings: Settings, limit: int = 25) -> str:
    """Markdown digest of the newest, best-matching listings."""
    conn = connect(settings.db_path)
    migrate(conn)
    store = Store(conn)
    rows = store.list_jobs(
        "is_active = 1 AND verification_status != 'POTENTIALLY_SUSPICIOUS'",
        order="match_score DESC, discovered_at DESC", limit=limit)
    cur = store.conn.cursor()
    cur.execute("SELECT * FROM search_runs ORDER BY id DESC LIMIT 1")
    last = cur.fetchone()
    conn.close()

    lines = [f"# Job Hunt Digest — {datetime.now().date().isoformat()}", ""]
    if last:
        lines.append(f"Last run: #{last['id']} ({last['status']}) — "
                     f"{last['jobs_found']} listings, {last['jobs_new']} new.")
        if last["sources_failed"] and last["sources_failed"] != "{}":
            failed = json.loads(last["sources_failed"])
            lines.append(f"Source failures: {', '.join(failed)} (coverage limited).")
        lines.append("")
    if not rows:
        lines.append("No matching listings yet. Run `search` first, or widen target titles.")
        return "\n".join(lines)
    for r in rows:
        why = ""
        try:
            bd = json.loads(r["match_breakdown"] or "{}")
            matched = (bd.get("skills") or {}).get("matched", [])
            if matched:
                why = f" — matches your skills: {', '.join(matched[:5])}"
        except json.JSONDecodeError:
            pass
        lines.append(f"## {r['title']} @ {r['employer']}")
        lines.append(f"- Location: {r['location'] or 'n/a'} ({r['remote_type']})")
        lines.append(f"- Match: **{r['match_score']}** | Eligibility: {r['eligibility_status']}")
        lines.append(f"- Verification: {r['verification_status']}{why}")
        lines.append(f"- Apply: {r['apply_url'] or r['source_url']}")
        lines.append("")
    return "\n".join(lines)
