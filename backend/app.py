"""AI Job Hunt Dashboard — backend API.

- POST /api/analyze  — CV upload -> server-side text extraction -> LLM
                       analysis (profile, gaps, roadmap). The LLM NEVER invents
                       job listings; jobs come only from /api/jobs.
- GET  /api/jobs     — REAL listings from verified sources (Greenhouse, Lever,
                       RemoteOK public APIs — free, no key).
- POST /api/search   — trigger a fresh research run (background).
- GET  /api/sources  — source health.
- GET  /api/health   — liveness (also reports the active LLM provider).

LLM providers (first configured wins, or set LLM_PROVIDER=groq|gemini|anthropic):
- Groq (free tier, no card: https://console.groq.com): GROQ_API_KEY
- Gemini (Google AI Studio — free tier): GEMINI_API_KEY
- Anthropic: ANTHROPIC_API_KEY
Keys live ONLY here (env vars), never in the frontend.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import requests
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from jobhunt import run as orchestrator
from jobhunt.config import load_settings
from jobhunt.cv import CVError, build_profile, extract_text, profile_to_dict
from jobhunt.db import Store, connect, migrate

BASE = Path(__file__).resolve().parent
settings = load_settings(str(BASE / "config.yaml"))
# NOTE: no module-level DB connection — SQLite connections are thread-bound,
# so each request gets its own via the get_store dependency below.
with connect(settings.db_path) as _c:
    migrate(_c)

app = FastAPI(title="AI Job Hunt Dashboard API")
app.add_middleware(
    CORSMiddleware,
    # Comma-separated in production, e.g.
    # FRONTEND_ORIGIN=https://your-app.vercel.app
    allow_origins=[o.strip() for o in
                   os.environ.get("FRONTEND_ORIGIN",
                                  "http://localhost:5173,http://127.0.0.1:5173").split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store():
    c = connect(settings.db_path)
    try:
        yield Store(c)
    finally:
        c.close()

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "auto").strip().lower()  # auto|groq|anthropic|gemini
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
MAX_CV_BYTES = 10 * 1024 * 1024

ANALYZE_PROMPT = """You are an expert AI recruiter and career coach.

The user's resume text is below. Analyze it in depth and return markdown with
exactly these sections:

## Profile Analysis
Core strengths, technical skills, domain expertise, transferable skills,
experience level, and suitable job titles.

## Skill Gaps & Resume Tips
Skill gaps, resume improvements, interview prep areas, useful certifications.

## 30-Day Application Roadmap
Week-by-week plan with daily targets and concrete strategies.

CRITICAL RULES:
- Analyze ONLY the resume. Do NOT invent, suggest, or list job openings,
  companies, salaries, or apply links. Job listings come from a separate
  verified system.
- Never invent experience, skills, or qualifications not in the resume.
- Be specific and actionable.

Resume:
---
{cv_text}
---
"""


def active_llm() -> str | None:
    """Which LLM provider is usable right now (None = CV analysis disabled)."""
    if LLM_PROVIDER == "groq":
        return "groq" if GROQ_KEY else None
    if LLM_PROVIDER == "anthropic":
        return "anthropic" if ANTHROPIC_KEY else None
    if LLM_PROVIDER == "gemini":
        return "gemini" if GEMINI_KEY else None
    # auto: prefer whichever key exists (free-first order)
    if GROQ_KEY:
        return "groq"
    if GEMINI_KEY:
        return "gemini"
    if ANTHROPIC_KEY:
        return "anthropic"
    return None


def _llm_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="No LLM API key is set on the server (GROQ_API_KEY, GEMINI_API_KEY "
               "or ANTHROPIC_API_KEY). Add one to enable CV analysis — "
               "job listings (/api/jobs) work without it.",
    )


def call_groq(prompt: str, file_b64: str | None = None,
              mime: str = "application/pdf") -> str:
    """Groq via its OpenAI-compatible API (free tier, no card required)."""
    if file_b64:
        model = GROQ_VISION_MODEL
        content: str | list[dict] = [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{file_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        model = GROQ_MODEL
        content = prompt
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_KEY}",
                     "content-type": "application/json"},
            json={"model": model,
                  "messages": [{"role": "user", "content": content}],
                  "max_tokens": 4000, "temperature": 0.3},
            timeout=120,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"LLM provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"LLM provider error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error"):
        err = data["error"]
        msg = err.get("message", "LLM error") if isinstance(err, dict) else str(err)
        raise HTTPException(status_code=502, detail=msg)
    try:
        text = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="LLM returned no text.")
    return text


def call_anthropic(prompt: str, file_b64: str | None = None,
                   mime: str = "application/pdf") -> str:
    content: list[dict] = []
    if file_b64:
        block_type = "document" if mime == "application/pdf" else "image"
        content.append({f"type": block_type,
                        "source": {"type": "base64", "media_type": mime, "data": file_b64}})
    content.append({"type": "text", "text": prompt})
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": ANTHROPIC_MODEL, "max_tokens": 4000,
                  "messages": [{"role": "user", "content": content}]},
            timeout=120,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"LLM provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"LLM provider error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error"):
        raise HTTPException(status_code=502, detail=data["error"].get("message", "LLM error"))
    return "\n".join(b.get("text", "") for b in data.get("content", []))


def call_gemini(prompt: str, file_b64: str | None = None,
                mime: str = "application/pdf") -> str:
    """Google Gemini via AI Studio API (free tier available)."""
    parts: list[dict] = []
    if file_b64:
        parts.append({"inlineData": {"mimeType": mime, "data": file_b64}})
    parts.append({"text": prompt})
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    try:
        r = requests.post(url, params={"key": GEMINI_KEY},
                          json={"contents": [{"parts": parts}]}, timeout=120)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"LLM provider unreachable: {e}")
    if r.status_code != 200:
        raise HTTPException(status_code=502,
                            detail=f"LLM provider error {r.status_code}: {r.text[:300]}")
    data = r.json()
    if data.get("error"):
        raise HTTPException(status_code=502,
                            detail=data["error"].get("message", "LLM error"))
    texts = []
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            if part.get("text"):
                texts.append(part["text"])
    if not texts:
        raise HTTPException(status_code=502, detail="LLM returned no text.")
    return "\n".join(texts)


def run_analysis(prompt: str, file_b64: str | None = None,
                 mime: str = "application/pdf") -> str:
    provider = active_llm()
    if provider == "groq":
        return call_groq(prompt, file_b64, mime)
    if provider == "gemini":
        return call_gemini(prompt, file_b64, mime)
    if provider == "anthropic":
        return call_anthropic(prompt, file_b64, mime)
    raise _llm_unavailable()


@app.get("/api/health")
def health():
    provider = active_llm()
    return {"ok": True, "llm_configured": provider is not None,
            "llm_provider": provider}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), store: Store = Depends(get_store)):
    data = await file.read()
    if len(data) > MAX_CV_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB).")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=415,
                            detail="Only PDF or image CVs are accepted.")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        if suffix == ".pdf":
            text, meta = extract_text(tmp_path)
            analysis = run_analysis(ANALYZE_PROMPT.format(cv_text=text[:30000]))
            prof = build_profile(text)
        else:
            import base64
            b64 = base64.b64encode(data).decode()
            media = {"png": "image/png", "jpg": "image/jpeg",
                     "jpeg": "image/jpeg", "webp": "image/webp"}[suffix[1:]]
            # vision: image + same rules (no invented jobs)
            analysis = run_analysis(
                ANALYZE_PROMPT.format(cv_text="[resume image attached — read it visually]"),
                file_b64=b64, mime=media)
            prof = build_profile("")
            meta = {"ocr_used": False, "injection_flag": False}
    except CVError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        # TEMPORARY DEBUG — remove after diagnosing the live 500
        import traceback
        raise HTTPException(
            status_code=500,
            detail="DEBUG-TRACEBACK:\n" + traceback.format_exc()[-3000:],
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    d = profile_to_dict(prof)
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    store.conn.execute(
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
         d["salary_expectation"], d["summary"], now, now))
    store.conn.commit()
    return {"analysis": analysis, "profile": d,
            "ocr_used": meta.get("ocr_used", False)}


@app.get("/api/jobs")
def jobs(store: Store = Depends(get_store), q: str = Query(""), verification: str = Query(""),
         min_score: float = Query(0), limit: int = Query(50, le=200)):
    where, params = ["is_active = 1"], []
    if q:
        where.append("(LOWER(title) LIKE ? OR LOWER(employer) LIKE ?)")
        params += [f"%{q.lower()}%", f"%{q.lower()}%"]
    if verification:
        where.append("verification_status = ?")
        params.append(verification)
    where.append("match_score >= ?")
    params.append(min_score)
    rows = store.list_jobs(" AND ".join(where), order="match_score DESC, discovered_at DESC",
                           limit=limit, params=tuple(params))
    out = []
    for r in rows:
        try:
            bd = json.loads(r["match_breakdown"] or "{}")
            notes = json.loads(r["eligibility_notes"] or "[]")
        except json.JSONDecodeError:
            bd, notes = {}, []
        skills = ((bd.get("skills") or {}).get("matched") or [])[:6]
        why = f"Matches your skills: {', '.join(skills)}." if skills else ""
        out.append({
            "id": r["canonical_id"], "title": r["title"], "company": r["employer"],
            "location": r["location"] or "n/a", "remote_type": r["remote_type"],
            "employment_type": r["employment_type"], "score": r["match_score"],
            "verification": r["verification_status"],
            "verification_evidence": (r["verification_evidence"] or "")[:300],
            "eligibility": r["eligibility_status"], "eligibility_notes": notes,
            "why": why, "link": r["apply_url"] or r["source_url"],
            "source": r["source_name"],
            "salary": f"{r['salary_currency']} {r['salary_min']:,.0f}–{r['salary_max']:,.0f}"
                      if r["salary_min"] else "",
        })
    return {"jobs": out, "count": len(out)}


@app.post("/api/search")
def trigger_search():
    def _run():
        try:
            orchestrator.run_search(settings)
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@app.get("/api/sources")
def sources(store: Store = Depends(get_store)):
    return {"sources": [
        {"name": r["name"], "label": r["label"], "coverage": r["coverage"],
         "docs": r["docs_url"], "health": r["health"],
         "last_success": r["last_success_at"]}
        for r in store.list_sources()]}


@app.get("/api/profile")
def get_profile(store: Store = Depends(get_store)):
    cur = store.conn.cursor()
    cur.execute("SELECT * FROM candidate_profiles ORDER BY id DESC LIMIT 1")
    r = cur.fetchone()
    if not r:
        return {"profile": None}
    return {"profile": {k: r[k] for k in r.keys()}}
