"""Normalization: RawJob -> Job. Deterministic, no LLM needed."""
from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import urlparse

from ..models import Job, RawJob, RemoteType, utcnow
from ..security import sanitize_untrusted_text

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_REMOTE_RES = [
    (re.compile(r"\bremote\b", re.I), RemoteType.REMOTE),
    (re.compile(r"\bhybrid\b", re.I), RemoteType.HYBRID),
    (re.compile(r"\bon[\s-]?site\b", re.I), RemoteType.ONSITE),
]
_SALARY_RE = re.compile(
    r"(?P<cur>\$|€|£|PKR|Rs\.?|AED|SAR|QAR)?\s?"
    r"(?P<lo>\d{1,3}(?:[,\d]{0,9})(?:\.\d+)?)\s*(?P<lok>[kK])?"
    r"(?:\s*[-–—to]+\s*(?P<cur2>\$|€|£|PKR|Rs\.?|AED|SAR|QAR)?\s?"
    r"(?P<hi>\d{1,3}(?:[,\d]{0,9})(?:\.\d+)?)\s*(?P<hik>[kK])?)?"
)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def detect_remote(location: str, text: str = "") -> RemoteType:
    blob = f"{location} {text}"
    for pattern, rtype in _REMOTE_RES:
        if pattern.search(blob):
            return rtype
    return RemoteType.UNKNOWN


def parse_salary(text: str) -> tuple[float | None, float | None, str]:
    if not text:
        return None, None, ""
    m = _SALARY_RE.search(text.replace(",", ""))
    if not m:
        return None, None, ""
    def num(v, k):
        if not v:
            return None
        n = float(v)
        return n * 1000 if k else n
    lo = num(m.group("lo"), m.group("lok"))
    hi = num(m.group("hi"), m.group("hik")) or lo
    cur = (m.group("cur") or m.group("cur2") or "").strip()
    return lo, hi, cur


def canonical_url(url: str) -> str:
    """Lowercase host, strip tracking params and fragments."""
    if not url:
        return ""
    try:
        p = urlparse(url)
    except ValueError:
        return url
    drop = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "gh_src", "ref", "fbclid", "gclid"}
    qs = "&".join(f"{k}={v}" for k, v in
                  (kv.split("=", 1) if "=" in kv else (kv, "")
                   for kv in p.query.split("&") if kv)
                  if k.lower() not in drop)
    rebuilt = p._replace(netloc=p.netloc.lower(), query=qs, fragment="")
    return rebuilt.geturl()


def content_fingerprint(title: str, employer: str, location: str) -> str:
    blob = "|".join(x.strip().lower() for x in (title, employer, location))
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def canonical_id(source_name: str, fingerprint: str) -> str:
    return f"{source_name}:{fingerprint}"


def normalize(raw: RawJob) -> Job:
    desc = sanitize_untrusted_text(html_to_text(raw.description_html))
    remote = detect_remote(raw.location, desc)
    lo, hi, cur = parse_salary(raw.salary_text or desc[:500])
    fp = content_fingerprint(raw.title, raw.employer, raw.location)
    src_url = canonical_url(raw.source_url)
    job = Job(
        canonical_id=canonical_id(raw.source_name, fp),
        title=raw.title.strip(),
        employer=raw.employer.strip() or raw.source_name,
        source_name=raw.source_name,
        source_url=src_url,
        original_posting_url=canonical_url(raw.original_posting_url) or src_url,
        apply_url=canonical_url(raw.apply_url) or src_url,
        location=raw.location.strip(),
        remote_type=remote,
        employment_type=raw.employment_type.strip(),
        salary_min=lo, salary_max=hi, salary_currency=cur,
        description_text=desc,
        content_hash=fp,
    )
    host = ""
    try:
        host = urlparse(job.original_posting_url).netloc
    except ValueError:
        pass
    job.employer_website = f"https://{host}" if host else ""
    return job
