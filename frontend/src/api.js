// Backend API client. All secrets stay server-side; the browser never
// talks to the LLM provider directly.
const BASE = "";

async function check(res) {
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      if (j.detail) msg = j.detail;
    } catch { /* keep default */ }
    throw new Error(msg);
  }
  return res.json();
}

export async function apiHealth() {
  return check(await fetch(`${BASE}/api/health`));
}

export async function analyzeCV(file) {
  const form = new FormData();
  form.append("file", file);
  return check(await fetch(`${BASE}/api/analyze`, { method: "POST", body: form }));
}

export async function fetchJobs({ q = "", verification = "", minScore = 0, limit = 60 } = {}) {
  const p = new URLSearchParams({ q, verification, min_score: minScore, limit });
  return check(await fetch(`${BASE}/api/jobs?${p}`));
}

export async function triggerSearch() {
  return check(await fetch(`${BASE}/api/search`, { method: "POST" }));
}

export async function fetchSources() {
  return check(await fetch(`${BASE}/api/sources`));
}
