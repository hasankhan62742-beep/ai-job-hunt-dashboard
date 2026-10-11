"""Original-source verification engine.

Evidence-based statuses only. We never claim a posting is officially
confirmed from a search snippet or a third-party board alone.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import requests

from ..models import Job, VerificationStatus, utcnow
from ..security import safe_url

_SUSPICIOUS = [
    r"pay (a |an )?(fee|deposit|registration)",
    r"(registration|application|processing|training).{0,25}fee",
    r"send.{0,30}(money|fee|payment)",
    r"whatsapp .{0,20}(apply|job|interview)",
    r"guaranteed (job|visa|income)",
    r"no (experience|interview) (needed|required).{0,40}earn",
    r"crypto.{0,20}(doubl|invest.+profit)",
]


def check_url_live(url: str, timeout: int = 15) -> tuple[bool, int, str]:
    """HEAD/GET the URL. Returns (reachable, status_code, note)."""
    if not safe_url(url):
        return False, 0, "unsafe or unresolvable URL (SSRF guard)"
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": "ai-jobhunt-agent/0.1"})
        if r.status_code in (405, 501):
            r = requests.get(url, timeout=timeout, allow_redirects=True,
                             headers={"User-Agent": "ai-jobhunt-agent/0.1"})
        return (200 <= r.status_code < 400), r.status_code, f"HTTP {r.status_code}"
    except requests.RequestException as e:
        return False, 0, f"{type(e).__name__}"


def looks_suspicious(text: str) -> str:
    for pat in _SUSPICIOUS:
        m = re.search(pat, text, re.I)
        if m:
            return f"matched scam pattern: {m.group(0)[:60]}"
    return ""


def verify(job: Job, timeout: int = 15, check_live: bool = True) -> Job:
    """Assign an evidence-based VerificationStatus. Mutates and returns job."""
    now = utcnow().isoformat()
    blob = f"{job.title} {job.description_text[:3000]}"
    scam_note = looks_suspicious(blob)
    if scam_note:
        job.verification_status = VerificationStatus.POTENTIALLY_SUSPICIOUS
        job.verification_evidence = scam_note
        job.verification_checked_at = now
        return job

    target = job.original_posting_url or job.apply_url or job.source_url
    official_host = bool(re.search(r"(greenhouse\.io|lever\.co|workday|taleo|ashby|careers?\.)",
                                   target, re.I))
    if check_live:
        ok, code, note = check_url_live(target, timeout=timeout)
        time.sleep(0.5)
    else:
        ok, code, note = False, 0, "live check skipped"

    if ok and official_host and job.source_name.startswith(("greenhouse", "lever")):
        job.verification_status = VerificationStatus.OFFICIAL_SOURCE_CONFIRMED
        job.verification_evidence = f"Employer ATS posting reachable ({note}): {target}"
    elif ok and official_host:
        job.verification_status = VerificationStatus.OFFICIAL_SOURCE_CONFIRMED
        job.verification_evidence = f"Official posting reachable ({note}): {target}"
    elif ok:
        job.verification_status = VerificationStatus.REPUTABLE_THIRD_PARTY_FOUND
        job.verification_evidence = f"Listing reachable on third-party board ({note}): {target}"
    elif code in (404, 410):
        job.verification_status = VerificationStatus.EXPIRED_OR_CLOSED
        job.verification_evidence = f"Posting URL returned {note}; likely closed/expired."
        job.is_active = False
    elif code == 0 and "unsafe" in note:
        job.verification_status = VerificationStatus.SOURCE_UNAVAILABLE
        job.verification_evidence = note
    else:
        job.verification_status = VerificationStatus.ACTIVE_STATUS_UNCONFIRMED
        job.verification_evidence = (
            f"Could not confirm status ({note}). Listing exists in source feed "
            f"but live status was not established; treat as unconfirmed."
        )
    job.verification_checked_at = now
    job.last_verified_at = now
    return job
