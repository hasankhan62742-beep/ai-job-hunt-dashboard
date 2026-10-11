"""Explainable match scoring + eligibility assessment.

Default weights (configurable): skills 35, education 20, experience 15,
role relevance 15, location/work-arrangement 10, other preferences 5.

Match score never overrides a mandatory unmet requirement: eligibility is
reported separately and honestly.
"""
from __future__ import annotations

import re

from ..models import CandidateProfile, EligibilityStatus, Job, RemoteType

DEFAULT_WEIGHTS = {
    "skills": 0.35,
    "education": 0.20,
    "experience": 0.15,
    "role": 0.15,
    "location": 0.10,
    "other": 0.05,
}

_DEGREE_HINTS = {
    "bachelor": ["bachelor", "bs ", "b.s", "bsc", "undergraduate"],
    "master": ["master", "ms ", "m.s", "msc", "mba"],
    "phd": ["phd", "ph.d", "doctorate"],
}

_SPONSOR_HINTS = ["visa sponsorship", "sponsor", "work authorization",
                  "authorized to work", "require sponsorship"]


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9+#.]{2,}", text.lower()))


def skill_score(job: Job, profile: CandidateProfile) -> tuple[float, dict]:
    blob = _words(f"{job.title} {job.description_text}")
    matched, inferred = [], []
    for s in profile.skills_extracted:
        if s.lower() in blob or any(w in blob for w in s.lower().split()):
            matched.append(s)
    for s in profile.skills_inferred:
        if s.lower() in blob or any(w in blob for w in s.lower().split()):
            inferred.append(s)
    pool = max(len(profile.skills_extracted), 1)
    score = min(len(matched) / pool, 1.0)
    return score, {"matched": matched, "inferred_matched": inferred,
                   "total_profile_skills": len(profile.skills_extracted)}


def education_score(job: Job, profile: CandidateProfile) -> tuple[float, dict]:
    blob = job.description_text.lower()
    edu_blob = " ".join(profile.education).lower()
    if not any(h in blob for hs in _DEGREE_HINTS.values() for h in hs):
        return 1.0, {"required": "not stated", "note": "no degree requirement found"}
    for level, hints in (("phd", _DEGREE_HINTS["phd"]),
                         ("master", _DEGREE_HINTS["master"]),
                         ("bachelor", _DEGREE_HINTS["bachelor"])):
        if any(h in blob for h in hints):
            has = any(h in edu_blob for h in hints)
            return (1.0 if has else 0.0,
                    {"required": level, "candidate_has": has})
    return 0.5, {"required": "unclear"}


def experience_score(job: Job, profile: CandidateProfile) -> tuple[float, dict]:
    if profile.experience_years is None:
        return 0.5, {"note": "candidate experience unknown"}
    blob = job.description_text.lower()
    m = re.search(r"(\d+)\s*\+?\s*(years?|yrs?)", blob)
    if not m:
        return 0.7, {"required": "not stated"}
    req = int(m.group(1))
    if profile.experience_years >= req:
        return 1.0, {"required_years": req, "candidate_years": profile.experience_years}
    if profile.experience_years >= req - 1:
        return 0.5, {"required_years": req, "candidate_years": profile.experience_years,
                     "note": "slightly below stated requirement"}
    return 0.2, {"required_years": req, "candidate_years": profile.experience_years}


def role_score(job: Job, profile: CandidateProfile) -> tuple[float, dict]:
    title_words = _words(job.title)
    if not profile.target_titles:
        return 0.5, {"note": "no target titles set"}
    best, best_title = 0.0, ""
    for t in profile.target_titles:
        tw = _words(t)
        overlap = len(title_words & tw) / max(len(tw), 1)
        if overlap > best:
            best, best_title = overlap, t
    return best, {"closest_target_title": best_title, "overlap": round(best, 2)}


def location_score(job: Job, profile: CandidateProfile) -> tuple[float, dict]:
    blob = f"{job.location} {job.country}".lower()
    if job.remote_type == RemoteType.REMOTE:
        if "remote" in profile.work_arrangements:
            return 1.0, {"arrangement": "remote", "candidate_ok": True}
        return 0.3, {"arrangement": "remote", "candidate_ok": False,
                     "note": "candidate did not list remote"}
    if profile.target_countries and any(c.lower() in blob for c in profile.target_countries):
        return 1.0, {"arrangement": job.remote_type.value, "country_match": True}
    if job.remote_type == RemoteType.HYBRID and "hybrid" in profile.work_arrangements:
        return 0.6, {"arrangement": "hybrid", "note": "hybrid accepted but country not in targets"}
    return 0.4, {"arrangement": job.remote_type.value, "note": "country not in target list"}


def assess_eligibility(job: Job, profile: CandidateProfile, breakdown: dict) -> tuple[EligibilityStatus, list[str]]:
    notes: list[str] = []
    edu = breakdown.get("education", {})
    if edu.get("required") not in (None, "not stated", "unclear") and not edu.get("candidate_has"):
        notes.append(f"Requires {edu['required']} degree; not found in candidate profile.")
        return EligibilityStatus.MISSING_REQUIRED_QUALIFICATION, notes

    blob = job.description_text.lower()
    if any(h in blob for h in _SPONSOR_HINTS):
        if re.search(r"(no|without|not).{0,30}sponsor", blob):
            notes.append("Posting states no visa sponsorship.")
            if job.remote_type != RemoteType.REMOTE:
                return EligibilityStatus.NOT_ELIGIBLE_BASED_ON_STATED_REQUIREMENTS, notes
        else:
            notes.append("Work authorization / sponsorship requirement mentioned; confirm before applying.")
            return EligibilityStatus.WORK_AUTHORIZATION_UNCONFIRMED, notes

    if job.remote_type != RemoteType.REMOTE:
        job_blob = f"{job.location} {job.country}".lower()
        in_target = profile.target_countries and any(c.lower() in job_blob for c in profile.target_countries)
        if profile.target_countries and not in_target:
            notes.append("On-site/hybrid role outside candidate's target countries; "
                         "work authorization unconfirmed.")
            return EligibilityStatus.WORK_AUTHORIZATION_UNCONFIRMED, notes

    exp = breakdown.get("experience", {})
    if exp.get("required_years") and profile.experience_years is not None:
        if profile.experience_years < exp["required_years"] - 1:
            notes.append(f"Requires {exp['required_years']}+ years; candidate has {profile.experience_years}.")
            return EligibilityStatus.MISSING_REQUIRED_QUALIFICATION, notes

    if not notes:
        notes.append("No blocking requirement found in available evidence.")
    return EligibilityStatus.POSSIBLY_ELIGIBLE, notes


def score_job(job: Job, profile: CandidateProfile,
              weights: dict | None = None) -> Job:
    w = weights or DEFAULT_WEIGHTS
    s_skill, d_skill = skill_score(job, profile)
    s_edu, d_edu = education_score(job, profile)
    s_exp, d_exp = experience_score(job, profile)
    s_role, d_role = role_score(job, profile)
    s_loc, d_loc = location_score(job, profile)
    other = 0.7  # neutral until salary/preference evidence exists
    if profile.salary_expectation and (job.salary_min or job.salary_max):
        other = 0.8  # salary info available on both sides
    breakdown = {
        "skills": {"score": round(s_skill, 3), **d_skill},
        "education": {"score": round(s_edu, 3), **d_edu},
        "experience": {"score": round(s_exp, 3), **d_exp},
        "role": {"score": round(s_role, 3), **d_role},
        "location": {"score": round(s_loc, 3), **d_loc},
        "other": {"score": round(other, 3)},
        "weights": w,
    }
    total = (s_skill * w["skills"] + s_edu * w["education"] + s_exp * w["experience"]
             + s_role * w["role"] + s_loc * w["location"] + other * w["other"])
    job.match_score = round(total * 100, 1)
    job.match_breakdown = breakdown
    status, notes = assess_eligibility(job, profile, breakdown)
    job.eligibility_status = status
    job.eligibility_notes = notes
    return job
