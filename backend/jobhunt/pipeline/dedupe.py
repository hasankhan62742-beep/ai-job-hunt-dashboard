"""Duplicate detection.

Two listings are duplicates when they share a canonical_id (same source +
same title/employer/location fingerprint). Cross-source duplicates are
detected by (employer, title, location) fingerprint and reported so the
pipeline keeps the official-source record.
"""
from __future__ import annotations

from ..models import Job


def dedupe(jobs: list[Job]) -> tuple[list[Job], list[dict]]:
    """Returns (unique_jobs, duplicate_reports)."""
    seen: dict[str, Job] = {}
    cross: dict[str, Job] = {}
    unique: list[Job] = []
    reports: list[dict] = []
    for job in jobs:
        if job.canonical_id in seen:
            reports.append({"kept": seen[job.canonical_id].canonical_id,
                            "dropped": job.canonical_id, "reason": "same-source duplicate"})
            continue
        seen[job.canonical_id] = job
        xkey = f"{job.employer.strip().lower()}|{job.title.strip().lower()}|{job.location.strip().lower()}"
        if xkey in cross:
            reports.append({"kept": cross[xkey].canonical_id,
                            "dropped": job.canonical_id, "reason": "cross-source duplicate"})
            continue
        cross[xkey] = job
        unique.append(job)
    return unique, reports
