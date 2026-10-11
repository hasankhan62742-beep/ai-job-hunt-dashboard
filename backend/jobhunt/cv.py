"""CV ingestion: PDF / DOCX / TXT -> structured CandidateProfile.

Rules:
- Extracted facts (stated in the CV) and inferred skills are kept separate.
- Never invent qualifications. Empty/corrupt/encrypted/oversized files are rejected.
- Retrieved text is untrusted data; prompt-injection patterns are flagged, not obeyed.
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import CandidateProfile
from .security import looks_like_instruction, sanitize_untrusted_text

MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_SKILL_BANK = [
    "python", "sql", "machine learning", "deep learning", "xgboost", "scikit-learn",
    "tensorflow", "pytorch", "pandas", "numpy", "nlp", "computer vision", "yolov8",
    "llm", "rag", "langchain", "fastapi", "streamlit", "docker", "git", "aws",
    "gcp", "azure", "mlops", "airflow", "spark", "power bi", "tableau", "excel",
    "statistics", "a/b testing", "forecasting", "churn", "recommendation",
    "javascript", "typescript", "react", "node", "flutter", "java", "c++",
    "n8n", "make.com", "zapier", "twilio", "whatsapp api", "supabase", "faiss",
    "hugging face", "groq", "openai", "gemini", "whisper", "opencv", "lstm",
]

_INFERRED_MAP = {
    "xgboost": ["gradient boosting", "ensemble methods"],
    "scikit-learn": ["classical ml", "model evaluation"],
    "pandas": ["data wrangling", "eda"],
    "fastapi": ["rest apis", "backend development"],
    "yolov8": ["object detection"],
    "langchain": ["llm apps", "prompt engineering"],
    "n8n": ["workflow automation"],
    "power bi": ["dashboards", "data visualization"],
    "sql": ["data querying"],
}

_DEGREE_RES = [
    (re.compile(r"\b(ph\.?d|doctorate)\b", re.I), "PhD"),
    (re.compile(r"\b(m\.?s\.?c|m\.?s\.?|mba|m\.?phil)\b", re.I), "Master's"),
    (re.compile(r"\b(b\.?s\.?c|b\.?s\.?|bachelor|b\.?tech|bs[\s(])", re.I), "Bachelor's"),
]

_LANG_HINTS = ["english", "urdu", "arabic", "french", "german", "spanish",
               "hindi", "punjabi", "saraiki"]


class CVError(Exception):
    pass


def extract_text(path: str | Path) -> tuple[str, dict]:
    """Returns (text, meta). Raises CVError on bad input."""
    p = Path(path)
    if not p.exists():
        raise CVError(f"file not found: {p}")
    if p.stat().st_size > MAX_BYTES:
        raise CVError(f"file too large ({p.stat().st_size} bytes > {MAX_BYTES})")
    suffix = p.suffix.lower()
    meta = {"filename": p.name, "size": p.stat().st_size, "type": suffix,
            "ocr_used": False, "injection_flag": False}
    if suffix == ".txt":
        text = p.read_text(errors="replace")
    elif suffix == ".pdf":
        text = _pdf_text(p, meta)
    elif suffix == ".docx":
        text = _docx_text(p)
    else:
        raise CVError(f"unsupported type {suffix}; use PDF, DOCX or TXT")
    if not text.strip():
        raise CVError("no readable text found (empty or image-only PDF without OCR)")
    text = sanitize_untrusted_text(text, max_len=60000)
    meta["injection_flag"] = looks_like_instruction(text)
    return text, meta


def _pdf_text(p: Path, meta: dict) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise CVError("pypdf not installed; install requirements.txt") from e
    try:
        reader = PdfReader(str(p))
    except Exception as e:
        raise CVError(f"could not read PDF: {e}") from e
    if reader.is_encrypted:
        raise CVError("encrypted PDF; please supply an unencrypted copy")
    parts = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(parts)
    if not text.strip():
        text = _ocr_pdf(p, meta)  # scanned PDF fallback
    return text


def _ocr_pdf(p: Path, meta: dict) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return ""
    try:
        images = convert_from_path(str(p), dpi=200)
        text = "\n".join(pytesseract.image_to_string(img) for img in images)
        if text.strip():
            meta["ocr_used"] = True
        return text
    except Exception:
        return ""


def _docx_text(p: Path) -> str:
    try:
        from docx import Document
    except ImportError as e:
        raise CVError("python-docx not installed; install requirements.txt") from e
    try:
        doc = Document(str(p))
    except Exception as e:
        raise CVError(f"could not read DOCX: {e}") from e
    return "\n".join(par.text for par in doc.paragraphs)


def build_profile(text: str, name_hint: str = "") -> CandidateProfile:
    """Deterministic extraction. Inferred skills are labeled, never merged."""
    lowered = text.lower()
    prof = CandidateProfile()

    m = re.search(r"([A-Z][a-z]+(?: [A-Z][a-z]+){1,3})", text[:400])
    prof.name = name_hint or (m.group(1) if m else "")
    em = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    prof.email = em.group(0) if em else ""
    ph = re.search(r"(\+?\d[\d\s\-()]{7,}\d)", text)
    prof.phone = ph.group(1).strip() if ph else ""

    prof.skills_extracted = sorted({s for s in _SKILL_BANK if s in lowered})
    inferred: set[str] = set()
    for s in prof.skills_extracted:
        inferred.update(_INFERRED_MAP.get(s, []))
    prof.skills_inferred = sorted(inferred - set(prof.skills_extracted))

    prof.education = sorted({label for rx, label in _DEGREE_RES if rx.search(text)})
    yrs = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience", lowered)
    if yrs:
        prof.experience_years = max(float(y) for y in yrs)
    prof.languages = [L.title() for L in _LANG_HINTS if L in lowered]
    return prof


def profile_to_dict(prof: CandidateProfile) -> dict:
    return {
        "name": prof.name, "email": prof.email, "phone": prof.phone,
        "country": prof.country, "city": prof.city,
        "target_countries": prof.target_countries,
        "work_arrangements": prof.work_arrangements,
        "skills_extracted": prof.skills_extracted,
        "skills_inferred": prof.skills_inferred,
        "education": prof.education, "experience_years": prof.experience_years,
        "languages": prof.languages, "target_titles": prof.target_titles,
        "employment_types": prof.employment_types,
        "salary_expectation": prof.salary_expectation, "summary": prof.summary,
    }


def profile_from_dict(d: dict) -> CandidateProfile:
    return CandidateProfile(
        name=d.get("name", ""), email=d.get("email", ""), phone=d.get("phone", ""),
        country=d.get("country", ""), city=d.get("city", ""),
        target_countries=d.get("target_countries", []),
        work_arrangements=d.get("work_arrangements", ["remote", "hybrid", "onsite"]),
        skills_extracted=d.get("skills_extracted", []),
        skills_inferred=d.get("skills_inferred", []),
        education=d.get("education", []),
        experience_years=d.get("experience_years"),
        languages=d.get("languages", []),
        target_titles=d.get("target_titles", []),
        employment_types=d.get("employment_types", []),
        salary_expectation=d.get("salary_expectation", ""),
        summary=d.get("summary", ""),
    )
