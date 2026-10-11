import { useEffect, useRef, useState } from "react";
import { analyzeCV, apiHealth, fetchJobs, fetchSources, triggerSearch } from "./api.js";

// ---------------------------------------------------------------------------
// Honesty contract for this UI:
// - Job listings come ONLY from the backend's verified sources
//   (Greenhouse / Lever / RemoteOK public APIs). The AI never invents jobs.
// - The AI analyzes YOUR cv (profile, gaps, roadmap) — nothing else.
// ---------------------------------------------------------------------------

const sectionMeta = {
  summary: { title: "📊 Profile Analysis", short: "📊 Profile" },
  highFit: { title: "🎯 High Probability Roles (80–100)", short: "🎯 High Fit" },
  medFit: { title: "⚡ Medium Probability Roles (60–79)", short: "⚡ Medium" },
  stretch: { title: "🚀 Stretch Roles (<60)", short: "🚀 Stretch" },
  gaps: { title: "🔧 Skill Gaps & Resume Tips", short: "🔧 Gaps" },
  roadmap: { title: "📅 30-Day Application Roadmap", short: "📅 Roadmap" },
};

const VER_COLORS = {
  OFFICIAL_SOURCE_CONFIRMED: "#22c55e",
  REPUTABLE_THIRD_PARTY_FOUND: "#3b82f6",
  ACTIVE_STATUS_UNCONFIRMED: "#f59e0b",
  EXPIRED_OR_CLOSED: "#ef4444",
  POTENTIALLY_SUSPICIOUS: "#ef4444",
  SOURCE_UNAVAILABLE: "#64748b",
};

const VER_LABELS = {
  OFFICIAL_SOURCE_CONFIRMED: "✓ Official",
  REPUTABLE_THIRD_PARTY_FOUND: "Board listing",
  ACTIVE_STATUS_UNCONFIRMED: "? Unconfirmed",
  EXPIRED_OR_CLOSED: "✕ Closed",
  POTENTIALLY_SUSPICIOUS: "⚠ Suspicious",
  SOURCE_UNAVAILABLE: "— Unavailable",
};

const MAX_BYTES = 10 * 1024 * 1024;
const ACCEPTED = [".pdf", ".png", ".jpg", ".jpeg", ".webp"];

function ScoreBadge({ score }) {
  const n = parseInt(score, 10) || 0;
  const color = n >= 80 ? "#22c55e" : n >= 60 ? "#f59e0b" : "#ef4444";
  return (
    <span style={{ background: color, color: "#fff", borderRadius: "999px", padding: "2px 10px", fontWeight: 700, fontSize: "0.8rem", marginLeft: 6, whiteSpace: "nowrap" }}>
      {n}/100
    </span>
  );
}

function VerificationBadge({ status }) {
  const color = VER_COLORS[status] || "#64748b";
  return (
    <span title={status} style={{ background: `${color}22`, color, border: `1px solid ${color}`, borderRadius: "999px", padding: "2px 10px", fontWeight: 700, fontSize: "0.72rem", whiteSpace: "nowrap" }}>
      {VER_LABELS[status] || status}
    </span>
  );
}

function JobCard({ job, index }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 12, marginBottom: 10, overflow: "hidden", boxShadow: open ? "0 0 0 2px #6366f1" : "none" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", padding: "12px 16px", cursor: "pointer", gap: 8, background: "none", border: "none", textAlign: "left", font: "inherit" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
          <span style={{ color: "#6366f1", fontWeight: 700, fontSize: "0.85rem", minWidth: 22 }}>#{index + 1}</span>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 700, color: "#f1f5f9", fontSize: "0.95rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {job.title}
            </div>
            <div style={{ color: "#94a3b8", fontSize: "0.78rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {job.company} · {job.location}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <VerificationBadge status={job.verification} />
          {job.score > 0 && <ScoreBadge score={job.score} />}
          <span style={{ color: "#6366f1", fontSize: "1rem" }}>{open ? "▲" : "▼"}</span>
        </div>
      </button>
      {open && (
        <div style={{ padding: "0 16px 14px", borderTop: "1px solid #1e293b" }}>
          {job.salary && (
            <div style={{ color: "#22c55e", fontWeight: 600, fontSize: "0.85rem", marginTop: 10 }}>💰 {job.salary}</div>
          )}
          <div style={{ color: "#94a3b8", fontSize: "0.78rem", marginTop: 8 }}>
            Eligibility: <strong style={{ color: "#cbd5e1" }}>{job.eligibility.replace(/_/g, " ")}</strong>
          </div>
          {job.why && (
            <div style={{ color: "#cbd5e1", fontSize: "0.85rem", marginTop: 8, lineHeight: 1.6 }}>
              <strong style={{ color: "#94a3b8" }}>Why it fits: </strong>{job.why}
            </div>
          )}
          {job.verification_evidence && (
            <div style={{ color: "#64748b", fontSize: "0.75rem", marginTop: 6 }}>{job.verification_evidence}</div>
          )}
          {job.link && job.link !== "#" && (
            <a href={job.link} target="_blank" rel="noopener noreferrer"
              style={{ display: "inline-block", marginTop: 10, background: "#6366f1", color: "#fff", borderRadius: 8, padding: "6px 14px", fontSize: "0.82rem", fontWeight: 600, textDecoration: "none" }}>
              Apply Now →
            </a>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <h2 style={{ fontSize: "1rem", fontWeight: 700, color: "#a5b4fc", marginBottom: 12, letterSpacing: "0.04em", textTransform: "uppercase", borderBottom: "1px solid #1e293b", paddingBottom: 6 }}>
        {title}
      </h2>
      {children}
    </div>
  );
}

function MarkdownText({ text }) {
  const lines = text.split("\n");
  return (
    <div style={{ color: "#cbd5e1", fontSize: "0.88rem", lineHeight: 1.75 }}>
      {lines.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return <div key={i} style={{ height: 6 }} />;
        const isBullet = trimmed.startsWith("- ") || trimmed.startsWith("• ") || trimmed.startsWith("* ");
        const content = isBullet ? trimmed.slice(2) : trimmed;
        const rendered = content.split(/\*\*(.*?)\*\*/g).map((part, j) =>
          j % 2 === 1 ? <strong key={j} style={{ color: "#f1f5f9" }}>{part}</strong> : part
        );
        return isBullet ? (
          <div key={i} style={{ display: "flex", gap: 8, marginBottom: 2 }}>
            <span style={{ color: "#6366f1", marginTop: 2 }}>▸</span>
            <span>{rendered}</span>
          </div>
        ) : (
          <div key={i}>{rendered}</div>
        );
      })}
    </div>
  );
}

function parseResult(raw) {
  const sections = { summary: "", highFit: "", medFit: "", stretch: "", gaps: "", roadmap: "" };
  const markers = [
    { key: "summary", patterns: [/profile\s*analysis|core\s*strength|profile\s*summary/i] },
    { key: "gaps", patterns: [/skill\s*gap|resume\s*tip|improvement/i] },
    { key: "roadmap", patterns: [/30.day|week.*target|application.*strat/i] },
  ];
  const lines = raw.split("\n");
  let current = null;
  const chunks = {};
  for (const line of lines) {
    const stripped = line.replace(/#+\s*/, "").trim();
    const matched = markers.find((m) => m.patterns.some((p) => p.test(stripped)));
    if (matched) {
      current = matched.key;
      if (!chunks[current]) chunks[current] = [];
      continue;
    }
    if (current) {
      if (!chunks[current]) chunks[current] = [];
      chunks[current].push(line);
    }
  }
  for (const key of ["summary", "gaps", "roadmap"]) {
    sections[key] = (chunks[key] || []).join("\n").trim();
  }
  if (!sections.summary && !sections.gaps && !sections.roadmap) sections.summary = raw;
  return sections;
}

export default function App() {
  const [stage, setStage] = useState("idle"); // idle | analyzing | done | error
  const [result, setResult] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobsNote, setJobsNote] = useState("");
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState("summary");
  const [showRaw, setShowRaw] = useState(false);
  const [fileName, setFileName] = useState("");
  const [fileObj, setFileObj] = useState(null);
  const [serverOk, setServerOk] = useState(null);
  const [llmOk, setLlmOk] = useState(null);
  const [sources, setSources] = useState([]);
  const fileRef = useRef();

  useEffect(() => {
    apiHealth()
      .then((h) => { setServerOk(true); setLlmOk(h.llm_configured); })
      .catch(() => setServerOk(false));
    fetchSources().then((s) => setSources(s.sources || [])).catch(() => {});
    fetchJobs({ limit: 60 }).then((d) => setJobs(d.jobs || [])).catch(() => {});
  }, []);

  const handleFile = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!ACCEPTED.includes(ext)) {
      setError(`Only ${ACCEPTED.join(", ")} files are accepted.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("File too large — max 10 MB.");
      return;
    }
    setError("");
    setFileName(file.name);
    setFileObj(file);
  };

  const analyze = async () => {
    if (!fileObj) return;
    setStage("analyzing");
    setError("");
    setResult(null);
    try {
      const data = await analyzeCV(fileObj);
      setResult({ ...parseResult(data.analysis || ""), _raw: data.analysis || "" });
      const jd = await fetchJobs({ limit: 60 });
      setJobs(jd.jobs || []);
      setJobsNote(jd.jobs && jd.jobs.length
        ? `${jd.jobs.length} real listings from verified employer boards.`
        : "No listings yet — hit Refresh jobs to run a research pass.");
      setStage("done");
      setActiveTab("summary");
    } catch (err) {
      setError(err.message || "Something went wrong");
      setStage("error");
    }
  };

  const refreshJobs = async () => {
    setJobsNote("Research running in background… refresh in a minute.");
    try {
      await triggerSearch();
    } catch (err) {
      setJobsNote(`Could not start research: ${err.message}`);
    }
  };

  const split = {
    highFit: jobs.filter((j) => j.score >= 80),
    medFit: jobs.filter((j) => j.score >= 60 && j.score < 80),
    stretch: jobs.filter((j) => j.score < 60),
  };

  const tabs = Object.keys(sectionMeta);

  return (
    <div style={{ minHeight: "100vh", background: "#020817", color: "#f1f5f9", fontFamily: "'Inter', 'Segoe UI', sans-serif", padding: "0 0 60px" }}>
      <div style={{ background: "linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%)", borderBottom: "1px solid #1e293b", padding: "24px 20px 20px", textAlign: "center" }}>
        <div style={{ fontSize: "2rem", marginBottom: 4 }}>🤖</div>
        <h1 style={{ margin: 0, fontSize: "1.4rem", fontWeight: 800, letterSpacing: "-0.02em" }}>AI Job Hunting System</h1>
        <p style={{ margin: "6px 0 0", color: "#94a3b8", fontSize: "0.85rem" }}>
          Upload your CV · Get AI-powered analysis · Browse <strong style={{ color: "#a5b4fc" }}>real, verified</strong> job listings
        </p>
        <div style={{ marginTop: 10, display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
          <span style={{ fontSize: "0.72rem", color: serverOk ? "#22c55e" : "#ef4444", background: "#0f172a", borderRadius: 999, padding: "3px 10px" }}>
            {serverOk === null ? "…checking backend" : serverOk ? "● Backend connected" : "● Backend offline — start it with uvicorn"}
          </span>
          {serverOk && (
            <span style={{ fontSize: "0.72rem", color: llmOk ? "#22c55e" : "#f59e0b", background: "#0f172a", borderRadius: 999, padding: "3px 10px" }}>
              {llmOk ? "● CV analysis ready" : "● CV analysis disabled (no API key on server)"}
            </span>
          )}
        </div>
      </div>

      <div style={{ maxWidth: 680, margin: "0 auto", padding: "24px 16px 0" }}>
        <div style={{ background: "#0d1f35", border: "1px solid #1e3a5f", borderRadius: 12, padding: "10px 14px", marginBottom: 20, fontSize: "0.8rem", color: "#93c5fd", lineHeight: 1.6 }}>
          <strong>How this works:</strong> job listings below come from real employer career boards
          (Greenhouse, Lever, RemoteOK — free public APIs) and each carries a verification badge.
          The AI <em>only</em> analyzes your CV — it never invents jobs, companies, or apply links.
        </div>

        {stage !== "done" && (
          <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 16, padding: "24px 20px", marginBottom: 20 }}>
            <div style={{ marginBottom: 14 }}>
              <label style={{ color: "#94a3b8", fontSize: "0.8rem", fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Upload Resume
              </label>
              <div onClick={() => fileRef.current.click()}
                style={{ marginTop: 8, border: "2px dashed #334155", borderRadius: 12, padding: "20px", textAlign: "center", cursor: "pointer", background: fileName ? "#0d1f35" : "transparent" }}>
                {fileName ? (
                  <div>
                    <div style={{ fontSize: "1.5rem", marginBottom: 4 }}>📄</div>
                    <div style={{ color: "#22c55e", fontWeight: 600, fontSize: "0.9rem" }}>{fileName}</div>
                    <div style={{ color: "#64748b", fontSize: "0.75rem", marginTop: 2 }}>Click to change</div>
                  </div>
                ) : (
                  <div>
                    <div style={{ fontSize: "1.8rem", marginBottom: 6 }}>☁️</div>
                    <div style={{ color: "#64748b", fontSize: "0.85rem" }}>Click to upload PDF or CV image (max 10 MB)</div>
                  </div>
                )}
                <input ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" style={{ display: "none" }} onChange={handleFile} />
              </div>
            </div>

            <button onClick={analyze} disabled={!fileObj || stage === "analyzing"}
              style={{ width: "100%", padding: "13px", background: fileObj && stage !== "analyzing" ? "linear-gradient(135deg, #6366f1, #8b5cf6)" : "#1e293b", color: fileObj && stage !== "analyzing" ? "#fff" : "#475569", border: "none", borderRadius: 12, fontWeight: 700, fontSize: "0.95rem", cursor: fileObj && stage !== "analyzing" ? "pointer" : "not-allowed", letterSpacing: "0.02em" }}>
              {stage === "analyzing" ? "🔍 Analyzing your CV..." : "🚀 Analyze & Find Jobs"}
            </button>

            {stage === "analyzing" && (
              <div style={{ marginTop: 16, textAlign: "center" }}>
                <div style={{ color: "#6366f1", fontSize: "0.85rem", marginBottom: 8 }}>AI is reading your resume and scoring real opportunities...</div>
                <div style={{ display: "flex", justifyContent: "center", gap: 6 }}>
                  {["Analyzing profile", "Scoring real jobs", "Building roadmap"].map((s, i) => (
                    <span key={i} style={{ background: "#1e293b", borderRadius: 999, padding: "3px 10px", fontSize: "0.75rem", color: "#94a3b8" }}>{s}</span>
                  ))}
                </div>
              </div>
            )}

            {error && (
              <div style={{ marginTop: 14, background: "#450a0a", borderRadius: 10, padding: "10px 14px", color: "#fca5a5", fontSize: "0.85rem" }}>
                ❌ {error}
              </div>
            )}
          </div>
        )}

        {stage === "done" && result && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16, flexWrap: "wrap", gap: 8 }}>
              <div style={{ color: "#22c55e", fontWeight: 700, fontSize: "0.9rem" }}>✅ Analysis Complete</div>
              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={refreshJobs} style={{ background: "#1e293b", color: "#94a3b8", border: "none", borderRadius: 8, padding: "6px 12px", fontSize: "0.78rem", cursor: "pointer" }}>
                  🔄 Refresh jobs
                </button>
                <button onClick={() => setShowRaw((r) => !r)} style={{ background: "#1e293b", color: "#94a3b8", border: "none", borderRadius: 8, padding: "6px 12px", fontSize: "0.78rem", cursor: "pointer" }}>
                  {showRaw ? "Card View" : "Raw Text"}
                </button>
                <button onClick={() => { setStage("idle"); setResult(null); setFileObj(null); setFileName(""); }} style={{ background: "#1e293b", color: "#94a3b8", border: "none", borderRadius: 8, padding: "6px 12px", fontSize: "0.78rem", cursor: "pointer" }}>
                  ↩ New CV
                </button>
              </div>
            </div>

            {jobsNote && (
              <div style={{ color: "#64748b", fontSize: "0.78rem", marginBottom: 12 }}>{jobsNote}</div>
            )}

            {showRaw ? (
              <div style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 12, padding: 16, maxHeight: 500, overflowY: "auto" }}>
                <pre style={{ color: "#cbd5e1", fontSize: "0.75rem", whiteSpace: "pre-wrap", margin: 0 }}>{result._raw}</pre>
              </div>
            ) : (
              <>
                <div style={{ display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4, marginBottom: 16, scrollbarWidth: "none" }}>
                  {tabs.map((tab) => (
                    <button key={tab} onClick={() => setActiveTab(tab)}
                      style={{ background: activeTab === tab ? "linear-gradient(135deg,#6366f1,#8b5cf6)" : "#0f172a", color: activeTab === tab ? "#fff" : "#94a3b8", border: activeTab === tab ? "none" : "1px solid #1e293b", borderRadius: 999, padding: "6px 14px", fontSize: "0.78rem", fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap", flexShrink: 0 }}>
                      {sectionMeta[tab].short}
                    </button>
                  ))}
                </div>

                <Section title={sectionMeta[activeTab].title}>
                  {["highFit", "medFit", "stretch"].includes(activeTab) ? (
                    split[activeTab].length > 0 ? (
                      split[activeTab].map((job, i) => <JobCard key={job.id} job={job} index={i} />)
                    ) : (
                      <div style={{ color: "#64748b", fontSize: "0.85rem" }}>
                        No jobs in this band yet. Upload a CV so scores can be computed, or hit 🔄 Refresh jobs.
                      </div>
                    )
                  ) : (
                    <MarkdownText text={result[activeTab] || "No data found for this section."} />
                  )}
                </Section>
              </>
            )}
          </div>
        )}

        {sources.length > 0 && stage !== "done" && (
          <div style={{ marginTop: 8 }}>
            <Section title="🔌 Live sources">
              {sources.map((s) => (
                <div key={s.name} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#94a3b8", padding: "6px 0", borderBottom: "1px solid #1e293b" }}>
                  <span>{s.label}</span>
                  <span style={{ color: s.health === "ok" ? "#22c55e" : "#f59e0b" }}>{s.health === "ok" ? "● live" : "● " + s.health}</span>
                </div>
              ))}
              <div style={{ color: "#64748b", fontSize: "0.72rem", marginTop: 8 }}>
                Free public APIs — no key needed. CV analysis uses your Anthropic key (server-side only).
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
