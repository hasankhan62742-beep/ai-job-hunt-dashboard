"""Core data model: enums and dataclasses.

Statuses follow the master spec exactly so that verification and eligibility
are evidence-based and never overstated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class VerificationStatus(str, Enum):
    OFFICIAL_SOURCE_CONFIRMED = "OFFICIAL_SOURCE_CONFIRMED"
    REPUTABLE_THIRD_PARTY_FOUND = "REPUTABLE_THIRD_PARTY_FOUND"
    ACTIVE_STATUS_UNCONFIRMED = "ACTIVE_STATUS_UNCONFIRMED"
    EXPIRED_OR_CLOSED = "EXPIRED_OR_CLOSED"
    POTENTIALLY_SUSPICIOUS = "POTENTIALLY_SUSPICIOUS"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class EligibilityStatus(str, Enum):
    ELIGIBLE_BASED_ON_AVAILABLE_EVIDENCE = "ELIGIBLE_BASED_ON_AVAILABLE_EVIDENCE"
    POSSIBLY_ELIGIBLE = "POSSIBLY_ELIGIBLE"
    MISSING_REQUIRED_QUALIFICATION = "MISSING_REQUIRED_QUALIFICATION"
    WORK_AUTHORIZATION_UNCONFIRMED = "WORK_AUTHORIZATION_UNCONFIRMED"
    NOT_ELIGIBLE_BASED_ON_STATED_REQUIREMENTS = "NOT_ELIGIBLE_BASED_ON_STATED_REQUIREMENTS"


class RemoteType(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class ApplicationStatus(str, Enum):
    SAVED = "Saved"
    PLANNED = "Planned"
    READY_TO_APPLY = "Ready to Apply"
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    CLOSED = "Closed"


@dataclass
class RawJob:
    """Un-normalized listing straight from a source adapter."""

    source_name: str
    title: str
    employer: str
    source_url: str  # URL on the source itself (board page / API record)
    original_posting_url: str = ""  # employer's own posting, when known
    apply_url: str = ""
    location: str = ""
    description_html: str = ""
    employment_type: str = ""
    salary_text: str = ""
    posted_at: str = ""  # raw, as the source gave it
    extra: dict = field(default_factory=dict)


@dataclass
class Job:
    """Normalized, deduplicated, verified job record."""

    canonical_id: str
    title: str
    employer: str
    source_name: str
    source_url: str
    original_posting_url: str = ""
    apply_url: str = ""
    employer_website: str = ""
    location: str = ""
    country: str = ""
    remote_type: RemoteType = RemoteType.UNKNOWN
    employment_type: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    deadline: str = ""
    description_text: str = ""
    contact_email: str = ""  # only when publicly published & verified
    contact_phone: str = ""  # only when publicly published & verified
    contact_evidence_url: str = ""
    verification_status: VerificationStatus = VerificationStatus.ACTIVE_STATUS_UNCONFIRMED
    verification_evidence: str = ""
    verification_checked_at: str = ""
    match_score: float = 0.0
    match_breakdown: dict = field(default_factory=dict)
    eligibility_status: EligibilityStatus = EligibilityStatus.POSSIBLY_ELIGIBLE
    eligibility_notes: list = field(default_factory=list)
    discovered_at: str = field(default_factory=lambda: utcnow().isoformat())
    last_verified_at: str = ""
    content_hash: str = ""
    is_active: bool = True


@dataclass
class CandidateProfile:
    name: str = ""
    email: str = ""
    phone: str = ""
    country: str = ""
    city: str = ""
    target_countries: list = field(default_factory=list)
    work_arrangements: list = field(default_factory=lambda: ["remote", "hybrid", "onsite"])
    skills_extracted: list = field(default_factory=list)  # stated in CV
    skills_inferred: list = field(default_factory=list)  # related, clearly labeled
    education: list = field(default_factory=list)
    experience_years: float | None = None
    languages: list = field(default_factory=list)
    target_titles: list = field(default_factory=list)
    employment_types: list = field(default_factory=list)  # full-time, contract, internship...
    salary_expectation: str = ""
    summary: str = ""
