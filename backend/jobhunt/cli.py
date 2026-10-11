"""CLI: init-db, import-cv, search, digest, health, export."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jobhunt import run as orchestrator
from jobhunt.config import load_settings
from jobhunt.cv import build_profile, extract_text, profile_to_dict
from jobhunt.db import Store, connect, migrate
from jobhunt.security import redact_pii_for_logs


def cmd_init_db(args):
    s = load_settings(args.config)
    conn = connect(s.db_path)
    v = migrate(conn)
    conn.close()
    print(f"database ready: {s.db_path} (schema v{v})")


def cmd_import_cv(args):
    s = load_settings(args.config)
    text, meta = extract_text(args.cv)
    prof = build_profile(text, name_hint=args.name or "")
    # user-supplied preferences override / extend extraction
    if args.country:
        prof.country = args.country
    if args.city:
        prof.city = args.city
    if args.target_countries:
        prof.target_countries = [c.strip() for c in args.target_countries.split(",")]
    if args.titles:
        prof.target_titles = [t.strip() for t in args.titles.split(",")]
    if args.arrangements:
        prof.work_arrangements = [a.strip() for a in args.arrangements.split(",")]

    print("== Extracted (stated in CV) ==")
    print(f"  name: {prof.name} | email: {prof.email} | experience: {prof.experience_years}y")
    print(f"  skills: {', '.join(prof.skills_extracted) or 'none found'}")
    print(f"  education: {', '.join(prof.education) or 'none found'} | languages: {', '.join(prof.languages)}")
    print("== Inferred (related, review before use) ==")
    print(f"  {', '.join(prof.skills_inferred) or 'none'}")
    if meta.get("injection_flag"):
        print("!! CV text contains instruction-like patterns; treated as data only.")
    if meta.get("ocr_used"):
        print("(OCR was used on a scanned PDF; verify extracted fields.)")

    if not args.yes:
        ans = input("Save this profile? [y/N] ").strip().lower()
        if ans != "y":
            print("not saved.")
            return
    conn = connect(s.db_path)
    migrate(conn)
    d = profile_to_dict(prof)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO candidate_profiles
           (name,email,phone,country,city,target_countries,work_arrangements,
            skills_extracted,skills_inferred,education,experience_years,languages,
            target_titles,employment_types,salary_expectation,summary,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["name"], d["email"], d["phone"], d["country"], d["city"],
         json.dumps(d["target_countries"]), json.dumps(d["work_arrangements"]),
         json.dumps(d["skills_extracted"]), json.dumps(d["skills_inferred"]),
         json.dumps(d["education"]), d["experience_years"], json.dumps(d["languages"]),
         json.dumps(d["target_titles"]), json.dumps(d["employment_types"]),
         d["salary_expectation"], d["summary"], now, now),
    )
    conn.commit()
    conn.close()
    print("profile saved. Edit it any time by re-running import-cv.")


def cmd_search(args):
    s = load_settings(args.config)
    print("starting research run...")
    summary = orchestrator.run_search(s)
    print(f"run #{summary['run_id']}: {summary['status']} — "
          f"{summary['found']} listings, {summary['new']} new, "
          f"{summary['verified']} verified, {summary['duplicates']} duplicates")
    if summary["sources_failed"]:
        print("failed sources:")
        for name, err in summary["sources_failed"].items():
            print(f"  - {name}: {redact_pii_for_logs(err)[:160]}")


def cmd_digest(args):
    s = load_settings(args.config)
    md = orchestrator.build_digest(s, limit=args.limit)
    out = s.digest_dir / f"digest-{datetime.now().date().isoformat()}.md"
    out.write_text(md)
    print(md)
    print(f"\nsaved to {out}")


def cmd_health(args):
    s = load_settings(args.config)
    conn = connect(s.db_path)
    migrate(conn)
    store = Store(conn)
    print(f"{'source':<22}{'health':<10}{'last success'}")
    for row in store.list_sources():
        print(f"{row['name']:<22}{row['health']:<10}{row['last_success_at'] or '-'}")
    conn.close()


def cmd_export(args):
    s = load_settings(args.config)
    conn = connect(s.db_path)
    migrate(conn)
    store = Store(conn)
    rows = store.list_jobs(limit=1000)
    path = Path(args.out)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "employer", "location", "remote_type", "employment_type",
                    "match_score", "eligibility", "verification", "apply_url", "source_url"])
        for r in rows:
            w.writerow([r["title"], r["employer"], r["location"], r["remote_type"],
                        r["employment_type"], r["match_score"], r["eligibility_status"],
                        r["verification_status"], r["apply_url"], r["source_url"]])
    conn.close()
    print(f"exported {len(rows)} jobs to {path}")


def main():
    ap = argparse.ArgumentParser(prog="jobhunt", description="Autonomous AI Job Hunting Agent")
    ap.add_argument("--config", default=None, help="path to config.yaml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init-db", help="create/migrate the database")

    p = sub.add_parser("import-cv", help="extract a candidate profile from a CV")
    p.add_argument("cv", help="path to CV (.pdf/.docx/.txt)")
    p.add_argument("--name", default="")
    p.add_argument("--country", default="")
    p.add_argument("--city", default="")
    p.add_argument("--target-countries", default="")
    p.add_argument("--titles", default="", help="comma-separated target job titles")
    p.add_argument("--arrangements", default="", help="comma-separated: remote,hybrid,onsite")
    p.add_argument("--yes", action="store_true", help="save without confirmation")

    sub.add_parser("search", help="run one full research pass now")
    p = sub.add_parser("digest", help="print today's digest markdown")
    p.add_argument("--limit", type=int, default=25)
    sub.add_parser("health", help="show source health")
    p = sub.add_parser("export", help="export jobs to CSV")
    p.add_argument("--out", default="jobs-export.csv")

    args = ap.parse_args()
    {"init-db": cmd_init_db, "import-cv": cmd_import_cv, "search": cmd_search,
     "digest": cmd_digest, "health": cmd_health, "export": cmd_export}[args.cmd](args)


if __name__ == "__main__":
    main()
