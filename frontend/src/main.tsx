import {
  StrictMode,
  type ChangeEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";
import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { flexRender, getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BarChart3,
  Check,
  ChevronRight,
  Database,
  Globe2,
  MapPin,
  Moon,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Upload,
  Users,
  Zap,
} from "lucide-react";
import { api } from "./api";
import type { Lead, Profile } from "./types";
import { Badge, Button, Card } from "./components/ui";
import "./styles.css";

const qc = new QueryClient();

const defaultProfile: Profile = {
  industry: "All industries",
  geography: "All locations",
  employee_min: 10,
  employee_max: 250,
  revenue_min: 1_000_000,
  revenue_max: 50_000_000,
  weights: {
    industry: 20,
    geography: 12,
    size: 14,
    revenue: 14,
    ownership: 12,
    tenure: 8,
    succession: 8,
    contact: 6,
    digital_gap: 6,
  },
};

type VerificationEvidence = {
  industry_match?: boolean | null;
  industry_match_reason?: string;
  geography_match?: boolean | null;
  num_locations?: number | null;
  digital_maturity_gap?: boolean | null;
  ai_readiness?: string;
  ai_readiness_score?: number | null;
  ai_readiness_reason?: string;
  source_urls?: string[];
  evidence?: string[];
  verification_type?: string;
};

function getVerification(lead: Lead): VerificationEvidence | null {
  const value = lead.raw_payload?.verification;
  return value && typeof value === "object" ? (value as VerificationEvidence) : null;
}

function aiReadinessGap(lead: Lead) {
  return getVerification(lead)?.digital_maturity_gap === true;
}

function getAiReadinessScore(lead: Lead): number | null {
  const v = getVerification(lead);
  if (v?.ai_readiness_score != null) return v.ai_readiness_score;
  // Fallback: check raw_payload directly
  const raw = lead.raw_payload?.ai_readiness_score;
  return typeof raw === "number" ? raw : null;
}

function getNumLocations(lead: Lead): number | null {
  const v = getVerification(lead);
  if (v?.num_locations != null) return v.num_locations;
  const raw = lead.raw_payload?.num_locations;
  return typeof raw === "number" ? raw : null;
}

function isAiReadinessVerified(lead: Lead): boolean {
  return getVerification(lead)?.verification_type === "ai_readiness_focused";
}

// ---------------------------------------------------------------------------
// App shell
// ---------------------------------------------------------------------------
function App() {
  return (
    <Routes>
      <Route path="*" element={<Shell />} />
    </Routes>
  );
}

function Shell() {
  const location = useLocation();
  const [darkMode, setDarkMode] = useState(
    () => window.localStorage.getItem("signaldesk-theme") === "dark",
  );
  const toggleTheme = () => {
    const next = !darkMode;
    setDarkMode(next);
    window.localStorage.setItem("signaldesk-theme", next ? "dark" : "light");
  };

  const navLabels: Record<string, string> = {
    "/": "Welcome",
    "/workspace": "Buy-box workspace",
    "/companies": "Companies",
    "/data-quality": "Data quality",
    "/discovery": "Public discovery",
    "/insights": "Pipeline insights",
    "/outreach": "Outreach drafts",
    "/ethics": "Data & ethics",
  };

  return (
    <div className={`app ${darkMode ? "theme-dark" : ""}`}>
      <aside className="sidebar">
        <Link className="brand" to="/">
          <div className="brand-mark">S</div>
          <span>SignalDesk</span>
        </Link>
        <nav className="nav-group">
          <div className="nav-label eyebrow">Lead intelligence</div>
          <Link className={`nav-item ${location.pathname === "/workspace" ? "active" : ""}`} to="/workspace">
            <Users size={15} /><span>Buy-box workspace</span>
          </Link>
          <Link className={`nav-item ${location.pathname === "/companies" ? "active" : ""}`} to="/companies">
            <Search size={15} /><span>Companies</span>
          </Link>
          <Link className={`nav-item ${location.pathname === "/data-quality" ? "active" : ""}`} to="/data-quality">
            <Database size={15} /><span>Data quality</span>
          </Link>
        </nav>
        <nav className="nav-group">
          <div className="nav-label eyebrow">Market intelligence</div>
          <Link className={`nav-item ${location.pathname === "/discovery" ? "active" : ""}`} to="/discovery">
            <Globe2 size={15} /><span>Public discovery</span>
          </Link>
          <Link className={`nav-item ${location.pathname === "/insights" ? "active" : ""}`} to="/insights">
            <BarChart3 size={15} /><span>Pipeline insights</span>
          </Link>
        </nav>
        <nav className="nav-group">
          <div className="nav-label eyebrow">Outreach</div>
          <Link className={`nav-item ${location.pathname === "/outreach" ? "active" : ""}`} to="/outreach">
            <Sparkles size={15} /><span>Outreach drafts</span>
          </Link>
          <Link className={`nav-item ${location.pathname === "/ethics" ? "active" : ""}`} to="/ethics">
            <ShieldCheck size={15} /><span>Data & ethics</span>
          </Link>
        </nav>
        <div className="sidebar-footer">
          Synthetic demo data<br />No signup required<br />v0.1.0
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} style={{ verticalAlign: "middle" }} />{" "}
            <strong>{navLabels[location.pathname] || "Welcome"}</strong>
          </div>
          <div className="top-actions">
            <Button variant="ghost" onClick={toggleTheme} aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}>
              {darkMode ? <Sun size={16} /> : <Moon size={16} />}
            </Button>
            <div className="avatar">FT</div>
          </div>
        </header>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/workspace" element={<Dashboard />} />
          <Route path="/companies" element={<CompaniesPage />} />
          <Route path="/data-quality" element={<DataQualityPage />} />
          <Route path="/discovery" element={<DiscoveryPage />} />
          <Route path="/insights" element={<InsightsPage />} />
          <Route path="/outreach" element={<OutreachPage />} />
          <Route path="/ethics" element={<Ethics />} />
          <Route path="*" element={<Home />} />
        </Routes>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Home page
// ---------------------------------------------------------------------------
function Home() {
  return (
    <div className="home-page">
      <section className="home-hero">
        <div className="hero-copy">
          <div className="eyebrow home-eyebrow">SignalDesk / acquisition intelligence</div>
          <h1>Find the next great company before the market does.</h1>
          <p>SignalDesk turns messy public business data into a clear, evidence-based shortlist for focused acquisition teams.</p>
          <div className="hero-actions">
            <Link className="btn btn-primary" to="/workspace">Open buy-box workspace <ArrowRight size={16} /></Link>
            <Link className="btn btn-secondary" to="/discovery">Explore public discovery</Link>
          </div>
          <div className="hero-proof">
            <span><ShieldCheck size={15} /> Confidence-aware data</span>
            <span><Sparkles size={15} /> Explainable scoring</span>
          </div>
        </div>
        <div className="hero-visual">
          <div className="hero-orb hero-orb-one" />
          <div className="hero-orb hero-orb-two" />
          <div className="hero-window">
            <div className="hero-window-top">
              <span>Pipeline command center</span>
              <Badge tone="verified">Live workspace</Badge>
            </div>
            <div className="hero-score-row">
              <div>
                <div className="hero-kicker">Top opportunity</div>
                <strong>Live company records</strong>
                <span>Confidence · fit · next action</span>
              </div>
              <div className="hero-score">100<small>score</small></div>
            </div>
            <div className="hero-mini-grid">
              <div><span>Imported rows</span><b>CSV</b></div>
              <div><span>Ranked leads</span><b>Live</b></div>
              <div><span>Outreach drafts</span><b>LLM</b></div>
            </div>
            <div className="hero-bars">
              <span style={{ width: "86%" }} />
              <span style={{ width: "63%" }} />
              <span style={{ width: "74%" }} />
            </div>
          </div>
        </div>
      </section>
      <section className="home-section">
        <div className="section-heading">
          <div>
            <div className="eyebrow">A sharper operating system</div>
            <h2>From public signal to confident action.</h2>
          </div>
          <p>Every screen is built to keep evidence, quality, and next steps in view.</p>
        </div>
        <div className="feature-grid">
          <Card className="feature-card">
            <div className="feature-icon"><SlidersHorizontal size={19} /></div>
            <h3>Build your buy-box</h3>
            <p>Set the industries, geographies, and operating signals that define your ideal acquisition.</p>
            <Link to="/workspace">Tune the workspace <ArrowRight size={14} /></Link>
          </Card>
          <Card className="feature-card">
            <div className="feature-icon"><Globe2 size={19} /></div>
            <h3>Discover public companies</h3>
            <p>Search public business sources by market and review results before they enter your pipeline.</p>
            <Link to="/discovery">Start discovering <ArrowRight size={14} /></Link>
          </Card>
          <Card className="feature-card">
            <div className="feature-icon"><BarChart3 size={19} /></div>
            <h3>See what matters next</h3>
            <p>Turn score, confidence, and readiness signals into a practical contact sequence.</p>
            <Link to="/insights">View pipeline insights <ArrowRight size={14} /></Link>
          </Card>
        </div>
      </section>
      <section className="home-callout">
        <div>
          <div className="eyebrow">Ready when you are</div>
          <h2>Make the next lead easier to choose.</h2>
          <p>Start with the synthetic demo pipeline—no signup required.</p>
        </div>
        <Link className="btn btn-primary" to="/workspace">Enter SignalDesk <ArrowRight size={16} /></Link>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared hook
// ---------------------------------------------------------------------------
function usePipelineLeads() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api
      .leads()
      .then((data) => { if (active) setLeads(data.leads); })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : "Could not load leads from Supabase."); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  return { leads, setLeads, loading, error };
}

// ---------------------------------------------------------------------------
// Dashboard / Buy-box workspace
// ---------------------------------------------------------------------------
function Dashboard() {
  const { leads, setLeads, loading, error } = usePipelineLeads();
  const [profile, setProfile] = useState<Profile>(defaultProfile);
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState("All tiers");
  const [message, setMessage] = useState("Loading leads from Supabase…");
  const [verifyWarnings, setVerifyWarnings] = useState<string[]>([]);

  useEffect(() => {
    if (error) setMessage(error);
    else if (!loading)
      setMessage(
        leads.length
          ? `${leads.length} leads loaded from Supabase.`
          : "No saved leads yet. Import a CSV to populate Supabase.",
      );
  }, [error, loading, leads.length]);

  const score = useMutation({
    mutationFn: () => api.score(leads, profile),
    onSuccess: (data) => { setLeads(data.leads); setMessage("Scores refreshed and saved to Supabase."); },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Could not save scores to Supabase."),
  });

  const verify = useMutation({
    mutationFn: () => api.verify(leads, profile),
    onSuccess: (data) => {
      setLeads(data.leads);
      setVerifyWarnings(data.warnings || []);
      setMessage(`Verified ${data.leads.length} leads with Google Search grounding.`);
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Web verification failed."),
  });

  // NEW: dedicated AI readiness verification
  const verifyAi = useMutation({
    mutationFn: () => api.verifyAiReadiness(leads, profile),
    onSuccess: (data) => {
      setLeads(data.leads);
      setVerifyWarnings(data.warnings || []);
      const verified = data.leads.filter((l) => isAiReadinessVerified(l)).length;
      setMessage(`AI readiness verified for ${verified}/${data.leads.length} leads via Google Search grounding.`);
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "AI readiness verification failed."),
  });

  const load = useMutation({
    mutationFn: api.demo,
    onSuccess: (data) => { setLeads(data.leads); setMessage("Loaded demo rows and saved them to Supabase."); },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Could not load demo data."),
  });

  const importCsv = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      api
        .importCsv(String(reader.result))
        .then((data) => { setLeads(data.leads); setMessage(`Imported and saved ${data.leads.length} records to Supabase.`); })
        .catch((err) => setMessage(err instanceof Error ? err.message : "CSV import failed."));
    };
    reader.readAsText(file);
  };

  const filtered = useMemo(
    () =>
      leads.filter(
        (lead) =>
          (tier === "All tiers" || lead.score_tier === tier) &&
          `${lead.company_name} ${lead.industry || ""} ${lead.city || ""}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [leads, tier, query],
  );

  const a = leads.filter((l) => l.score_tier === "A").length;
  const verified = leads.filter((l) => l.validation_status === "verified").length;
  const aiVerifiedCount = leads.filter((l) => isAiReadinessVerified(l)).length;
  const anyPending = score.isPending || verify.isPending || verifyAi.isPending;

  return (
    <div className="content">
      <div className="title-row">
        <div>
          <div className="eyebrow">Lead intelligence / quality first</div>
          <h1>Prioritize the next best lead.</h1>
          <p className="subtitle">Your pipeline is loaded from Supabase and updated as you import, score, and review.</p>
        </div>
        <div className="top-actions">
          <label className="btn btn-secondary">
            <Upload size={15} /> Import CSV
            <input type="file" accept=".csv,text/csv" onChange={importCsv} hidden />
          </label>
          <Button onClick={() => load.mutate()} disabled={load.isPending}>
            <RefreshCw size={15} /> {load.isPending ? "Saving demo…" : "Load demo data"}
          </Button>
        </div>
      </div>

      <div className="steps">
        <div className="step done"><span className="step-dot"><Check size={13} /></span>Import</div>
        <div className="step-line" />
        <div className="step done"><span className="step-dot"><Check size={13} /></span>Clean</div>
        <div className="step-line" />
        <div className="step current"><span className="step-dot">3</span>Score</div>
        <div className="step-line" />
        <div className="step"><span className="step-dot">4</span>Review</div>
        <div className="step-line" />
        <div className="step"><span className="step-dot">5</span>Export</div>
      </div>

      <div className="grid-4">
        <Metric label="Leads in view" value={leads.length} foot="Supabase pipeline" />
        <Metric label="A-tier leads" value={a} foot="Contact these first" good />
        <Metric label="Verified records" value={`${verified}/${leads.length}`} foot="Confidence-aware" />
        <Metric label="AI-readiness checked" value={`${aiVerifiedCount}/${leads.length}`} foot="Via web search" good={aiVerifiedCount > 0} />
      </div>

      <div className="workspace">
        <Card>
          <div className="panel-title">
            <h2><SlidersHorizontal size={15} style={{ verticalAlign: "middle" }} /> Buy-box</h2>
            <span>Live weights</span>
          </div>
          <div className="filters">
            <div className="field">
              <label htmlFor="industry">Industry</label>
              <select id="industry" value={profile.industry} onChange={(e) => setProfile({ ...profile, industry: e.target.value })}>
                <option>All industries</option>
                <option>Industrial</option>
                <option>HVAC</option>
                <option>Dental</option>
                <option>Professional Services</option>
              </select>
            </div>
            <div className="field">
              <label htmlFor="geo">Geography</label>
              <input id="geo" value={profile.geography} onChange={(e) => setProfile({ ...profile, geography: e.target.value })} />
            </div>
            <div className="field">
              <label>Employee band</label>
              <div className="range-row">
                <span>{profile.employee_min}</span>
                <span>{profile.employee_max}</span>
              </div>
              <input type="range" min="0" max="500" value={profile.employee_max} onChange={(e) => setProfile({ ...profile, employee_max: Number(e.target.value) })} />
            </div>
            <div className="field">
              <label>Contact data weight <b>{profile.weights.contact}</b></label>
              <input type="range" min="0" max="20" value={profile.weights.contact} onChange={(e) => setProfile({ ...profile, weights: { ...profile.weights, contact: Number(e.target.value) } })} />
            </div>
            <div className="field">
              <label>AI-readiness weight <b>{profile.weights.digital_gap}</b></label>
              <input type="range" min="0" max="20" value={profile.weights.digital_gap} onChange={(e) => setProfile({ ...profile, weights: { ...profile.weights, digital_gap: Number(e.target.value) } })} />
            </div>

            {/* AI Readiness Web Search Button — calls the new real verification endpoint */}
            <Button
              variant="secondary"
              onClick={() => verifyAi.mutate()}
              disabled={!leads.length || anyPending}
              title="Uses LLM + Google Search to verify AI readiness, industry match, and number of locations for each lead"
            >
              <Zap size={15} /> {verifyAi.isPending ? "Checking AI readiness via web…" : "Check AI Readiness (web search)"}
            </Button>

            <Button variant="secondary" onClick={() => verify.mutate()} disabled={!leads.length || anyPending}>
              <Globe2 size={15} /> {verify.isPending ? "Verifying…" : "Full web verification"}
            </Button>

            <Button onClick={() => score.mutate()} disabled={!leads.length || anyPending}>
              <Activity size={15} /> {score.isPending ? "Rescoring…" : "Re-score pipeline"}
            </Button>

            <div className="filter-foot"><ShieldCheck size={14} /> {message}</div>
          </div>
        </Card>

        <Card>
          <div className="panel-title">
            <div>
              <h2>Ranked lead review</h2>
              <span>{message}</span>
            </div>
            <div className="top-actions">
              <div className="field">
                <label htmlFor="search" style={{ display: "none" }}>Search leads</label>
                <input id="search" placeholder="Search leads" value={query} onChange={(e) => setQuery(e.target.value)} />
              </div>
              <select aria-label="Filter by tier" value={tier} onChange={(e) => setTier(e.target.value)}>
                <option>All tiers</option>
                <option>A</option>
                <option>B</option>
                <option>C</option>
                <option>D</option>
              </select>
              <Button variant="secondary" onClick={() => download(filtered)} disabled={!filtered.length}>
                <ArrowDownToLine size={15} /> Export
              </Button>
            </div>
          </div>

          {verifyWarnings.length > 0 && (
            <div className="notice notice-good" style={{ margin: "0 0 8px 0", fontSize: "0.8rem" }}>
              {verifyWarnings[0]}
            </div>
          )}

          <div className="insights">
            <div className="insight"><b>{a} leads</b> merit first contact</div>
            <button
              className="insight insight-button"
              onClick={() => verifyAi.mutate()}
              disabled={!leads.length || anyPending}
            >
              <b>{leads.filter(aiReadinessGap).length}</b>{" "}
              {verifyAi.isPending
                ? "checking AI-readiness via web search…"
                : "AI-readiness gaps · click to verify with web search"}
            </button>
            <div className="insight"><b>{leads.filter((l) => l.validation_status !== "verified").length}</b> need data review</div>
          </div>

          <LeadTable leads={filtered} />
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Companies page
// ---------------------------------------------------------------------------
function CompaniesPage() {
  const { leads, loading, error } = usePipelineLeads();
  const [query, setQuery] = useState("");
  const filtered = useMemo(
    () => leads.filter((lead) => `${lead.company_name} ${lead.industry || ""} ${lead.city || ""}`.toLowerCase().includes(query.toLowerCase())),
    [leads, query],
  );
  return (
    <div className="content">
      <div className="eyebrow">Lead intelligence / company directory</div>
      <h1>Companies</h1>
      <p className="subtitle">Browse the normalized companies currently saved in Supabase.</p>
      <div className="page-toolbar">
        <input aria-label="Search companies" placeholder="Search companies" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Link className="btn btn-primary" to="/workspace">Open buy-box workspace</Link>
      </div>
      {error && <div className="notice notice-warning">{error}</div>}
      {loading ? (
        <div className="notice">Loading companies from Supabase…</div>
      ) : (
        <Card>
          <div className="panel-title">
            <h2>Company records</h2>
            <span>{filtered.length} visible</span>
          </div>
          <LeadTable leads={filtered} />
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Data quality page
// ---------------------------------------------------------------------------
function DataQualityPage() {
  const { leads, loading, error } = usePipelineLeads();
  const verified = leads.filter((lead) => lead.validation_status === "verified").length;
  const flagged = leads.filter((lead) => lead.validation_flags.length > 0);
  return (
    <div className="content">
      <div className="eyebrow">Lead intelligence / quality first</div>
      <h1>Data quality</h1>
      <p className="subtitle">Review validation status, confidence, and fields needing attention in your saved pipeline.</p>
      {error && <div className="notice notice-warning">{error}</div>}
      <div className="grid-4">
        <Metric label="Records reviewed" value={leads.length} foot="Supabase records" />
        <Metric label="Verified" value={`${verified}/${leads.length}`} foot="Ready for contact" good />
        <Metric label="Needs review" value={flagged.length} foot="Resolve before export" />
        <Metric
          label="Avg. confidence"
          value={`${leads.length ? Math.round(leads.reduce((sum, lead) => sum + lead.confidence_score, 0) / leads.length) : 0}%`}
          foot="Evidence-weighted"
        />
      </div>
      {loading ? (
        <div className="notice">Loading quality data from Supabase…</div>
      ) : (
        <Card>
          <div className="panel-title">
            <h2>Validation queue</h2>
            <span>Flags are carried with every lead</span>
          </div>
          <div className="table-wrap">
            <table className="table data-table">
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Confidence</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => (
                  <tr key={lead.id}>
                    <td>
                      <div className="company">{lead.company_name}</div>
                      <div className="domain">{lead.domain || "No domain"}</div>
                    </td>
                    <td><Badge tone={lead.validation_status}>{lead.validation_status.replace("_", " ")}</Badge></td>
                    <td><strong>{lead.confidence_score}%</strong></td>
                    <td>{lead.validation_flags.length ? lead.validation_flags.join(", ") : "No validation flags"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Discovery page
// ---------------------------------------------------------------------------
function DiscoveryPage() {
  const [industry, setIndustry] = useState("HVAC Services");
  const [city, setCity] = useState("Tampa");
  const [leads, setLeads] = useState<Lead[]>([]);
  const [message, setMessage] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);

  const mutation = useMutation({
    mutationFn: () => api.discover(industry, city),
    onSuccess: (data) => {
      setLeads(data.leads);
      setWarnings(data.warnings || []);
      setMessage(
        data.leads.length
          ? `Found ${data.leads.length} public records for ${industry} in ${city}.`
          : `No public records matched ${industry} in ${city}. Try a broader industry or nearby city.`,
      );
    },
    onError: (err) => {
      setLeads([]);
      setWarnings([]);
      setMessage(err instanceof Error ? err.message : "Public discovery is temporarily unavailable.");
    },
  });

  return (
    <div className="content">
      <div className="eyebrow">Market intelligence / public sources</div>
      <h1>Public discovery</h1>
      <p className="subtitle">Find public business records by industry and location, then review them before adding them to your pipeline.</p>
      <Card>
        <div className="discovery-form">
          <div className="field">
            <label htmlFor="discovery-industry">Industry</label>
            <input id="discovery-industry" value={industry} onChange={(e) => setIndustry(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="discovery-city">City</label>
            <input id="discovery-city" value={city} onChange={(e) => setCity(e.target.value)} />
          </div>
          <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
            {mutation.isPending ? "Searching…" : "Discover public businesses"}
          </Button>
        </div>
        <p className="helper">Uses public business-level sources with attribution and rate-limit safeguards.</p>
      </Card>
      {message && <div className={`notice ${leads.length ? "notice-good" : "notice-warning"}`}>{message}</div>}
      {warnings.map((w) => <div className="notice" key={w}>{w}</div>)}
      {leads.length > 0 && (
        <Card>
          <div className="panel-title">
            <h2>Discovery results</h2>
            <span>{leads.length} records</span>
          </div>
          <LeadTable leads={leads} />
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Insights page
// ---------------------------------------------------------------------------
function InsightsPage() {
  const { leads, loading, error } = usePipelineLeads();
  const tiers = ["A", "B", "C", "D"].map((t) => ({
    tier: t,
    count: leads.filter((lead) => lead.score_tier === t).length,
  }));
  const avg = leads.length ? Math.round(leads.reduce((sum, lead) => sum + lead.buy_box_score, 0) / leads.length) : 0;

  return (
    <div className="content">
      <div className="eyebrow">Market intelligence / pipeline performance</div>
      <h1>Pipeline insights</h1>
      <p className="subtitle">Understand ranking coverage and next actions across the Supabase-backed pipeline.</p>
      {error && <div className="notice notice-warning">{error}</div>}
      <div className="grid-4">
        <Metric label="Leads in pipeline" value={leads.length} foot="Supabase pipeline" />
        <Metric label="Average score" value={avg} foot="Buy-box score" good />
        <Metric label="A-tier opportunities" value={tiers[0].count} foot="Prioritize first contact" />
        <Metric label="AI-readiness gaps" value={leads.filter(aiReadinessGap).length} foot="Potential workflow fit" />
      </div>
      {loading ? (
        <div className="notice">Loading insights from Supabase…</div>
      ) : (
        <>
          <Card>
            <div className="panel-title">
              <h2>Score distribution</h2>
              <span>Current buy-box ranking</span>
            </div>
            <div className="insight-list">
              {tiers.map((item) => (
                <div className="insight-row" key={item.tier}>
                  <Badge tone={item.tier}>{item.tier}</Badge>
                  <span>{item.count} lead{item.count === 1 ? "" : "s"}</span>
                  <div className="insight-bar">
                    <span style={{ width: `${leads.length ? Math.max(4, (item.count / leads.length) * 100) : 4}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <div className="panel-title">
              <h2>Recommended action mix</h2>
            </div>
            <div className="insights">
              {["Contact first", "Verify data", "Research fit", "Nurture"].map((action) => (
                <div className="insight" key={action}>
                  <b>{leads.filter((lead) => lead.next_best_action.toLowerCase().includes(action.split(" ")[0].toLowerCase())).length}</b>{" "}
                  {action}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Outreach page
// ---------------------------------------------------------------------------
function OutreachPage() {
  const { leads, loading, error } = usePipelineLeads();
  const [selectedId, setSelectedId] = useState("");
  const [draft, setDraft] = useState<{ subject: string; body: string } | null>(null);
  useEffect(() => {
    if (!selectedId && leads[0]) setSelectedId(leads[0].id);
  }, [leads, selectedId]);
  const selected = leads.find((lead) => lead.id === selectedId);
  const mutation = useMutation({
    mutationFn: () => (selected ? api.draft(selected) : Promise.reject(new Error("Import a CSV before generating outreach."))),
    onSuccess: (data) => setDraft(data),
  });

  return (
    <div className="content">
      <div className="eyebrow">Outreach / quality-aware drafting</div>
      <h1>Outreach drafts</h1>
      <p className="subtitle">Generate an LLM-written first-touch draft grounded in the selected Supabase lead's verified signals.</p>
      {error && <div className="notice notice-warning">{error}</div>}
      {loading ? (
        <div className="notice">Loading leads from Supabase…</div>
      ) : (
        <>
          <Card>
            <div className="discovery-form">
              <div className="field">
                <label htmlFor="outreach-lead">Lead</label>
                <select
                  id="outreach-lead"
                  value={selectedId}
                  onChange={(e) => { setSelectedId(e.target.value); setDraft(null); }}
                  disabled={!leads.length}
                >
                  {leads.length
                    ? leads.map((lead) => <option value={lead.id} key={lead.id}>{lead.company_name}</option>)
                    : <option>Import a CSV first</option>}
                </select>
              </div>
              <Button onClick={() => mutation.mutate()} disabled={!selected || mutation.isPending}>
                {mutation.isPending ? "Writing with LLM…" : "Generate outreach draft"}
              </Button>
            </div>
          </Card>
          {mutation.isError && (
            <div className="notice notice-warning">
              {mutation.error instanceof Error ? mutation.error.message : "LLM outreach failed."}
            </div>
          )}
          {draft && (
            <Card>
              <div className="panel-title">
                <h2>{draft.subject}</h2>
                <Badge tone="neutral">Review before sending</Badge>
              </div>
              <div className="draft-body">{draft.body}</div>
            </Card>
          )}
          <div className="notice">Drafts are generated by the configured LLM and are never sent automatically.</div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------
function Metric({ label, value, foot, good = false }: { label: string; value: string | number; foot: string; good?: boolean }) {
  return (
    <Card>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className={`metric-foot ${good ? "good" : ""}`}>{foot}</div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// LeadTable — shows real verified AI readiness, num_locations, industry match
// ---------------------------------------------------------------------------
function LeadTable({ leads }: { leads: Lead[] }) {
  const parentRef = useRef<HTMLDivElement>(null);

  const columns = useMemo(
    () => [
      { accessorKey: "company_name", header: "Company" },
      { accessorKey: "buy_box_score", header: "Score" },
      { accessorKey: "score_tier", header: "Tier" },
      { accessorKey: "industry", header: "Fit signals" },
      { accessorKey: "confidence_score", header: "Data confidence" },
      { accessorKey: "next_best_action", header: "Next action" },
    ],
    [],
  );

  const table = useReactTable({ data: leads, columns, getCoreRowModel: getCoreRowModel() });
  const rowVirtualizer = useVirtualizer({
    count: table.getRowModel().rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 110,
    overscan: 8,
  });

  return (
    <div className="table-wrap" ref={parentRef} style={{ maxHeight: 520, overflow: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            {table.getHeaderGroups()[0].headers.map((header) => (
              <th key={header.id}>{flexRender(header.column.columnDef.header, header.getContext())}</th>
            ))}
          </tr>
        </thead>
        <tbody style={{ height: `${rowVirtualizer.getTotalSize()}px`, position: "relative", display: "block" }}>
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const row = table.getRowModel().rows[virtualRow.index];
            const lead = row.original;
            const verification = getVerification(lead);
            const aiScore = getAiReadinessScore(lead);
            const numLoc = getNumLocations(lead);
            const isAiVerified = isAiReadinessVerified(lead);

            return (
              <tr
                key={row.id}
                ref={rowVirtualizer.measureElement}
                data-index={virtualRow.index}
                style={{
                  position: "absolute",
                  top: 0,
                  transform: `translateY(${virtualRow.start}px)`,
                  display: "grid",
                  gridTemplateColumns: "2.1fr .55fr .55fr 1.25fr 1fr 1fr",
                  alignItems: "center",
                  width: "100%",
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {cell.column.id === "company_name" ? (
                      <>
                        <div className="company">{lead.company_name}</div>
                        <div className="domain">{lead.domain || "No domain"}</div>
                        <div className="chips">
                          {/* Score reasons */}
                          {lead.score_reasons.slice(0, 2).map((reason) => (
                            <span className="chip" key={reason}>{reason}</span>
                          ))}

                          {/* AI Readiness — real web-verified score, not hardcoded */}
                          {isAiVerified && aiScore != null ? (
                            <span
                              className={`chip ${aiScore >= 70 ? "chip-good" : aiScore >= 40 ? "chip-warn" : "chip-bad"}`}
                              title={verification?.ai_readiness_reason || ""}
                            >
                              <Zap size={10} style={{ verticalAlign: "middle" }} />{" "}
                              AI-ready: {aiScore}/100 ({verification?.ai_readiness || "?"})
                            </span>
                          ) : !isAiVerified ? (
                            <span className="chip" title="Click 'Check AI Readiness' to verify via web search">
                              AI-readiness unverified
                            </span>
                          ) : null}

                          {/* Industry match — verified */}
                          {isAiVerified && verification?.industry_match != null && (
                            <span
                              className={`chip ${verification.industry_match ? "chip-good" : "chip-bad"}`}
                              title={verification.industry_match_reason || ""}
                            >
                              Industry: {verification.industry_match ? "✓ match" : "✗ mismatch"}
                            </span>
                          )}

                          {/* Num locations — from web search, not hardcoded */}
                          {isAiVerified && numLoc != null && (
                            <span className="chip chip-info" title="Number of physical locations found via web search">
                              <MapPin size={10} style={{ verticalAlign: "middle" }} /> {numLoc} location{numLoc !== 1 ? "s" : ""}
                            </span>
                          )}

                          {/* Web evidence link */}
                          {verification?.source_urls?.slice(0, 1).map((src) => (
                            <a className="chip source-chip" href={src} target="_blank" rel="noreferrer" key={src}>
                              Web evidence
                            </a>
                          ))}

                          {/* Verification status badge */}
                          {verification ? (
                            <span className="chip verification-chip">
                              {isAiVerified ? "AI-readiness verified" : "Web verified"}
                            </span>
                          ) : (
                            <span className="chip">Needs web verification</span>
                          )}
                        </div>
                      </>
                    ) : cell.column.id === "buy_box_score" ? (
                      <span className={`score score-${lead.score_tier.toLowerCase()}`}>{lead.buy_box_score}</span>
                    ) : cell.column.id === "score_tier" ? (
                      <Badge tone={lead.score_tier}>{lead.score_tier}</Badge>
                    ) : cell.column.id === "confidence_score" ? (
                      <>
                        <strong>{lead.confidence_score}%</strong>
                        <div><Badge tone={lead.validation_status}>{lead.validation_status.replace("_", " ")}</Badge></div>
                      </>
                    ) : cell.column.id === "next_best_action" ? (
                      <button className="table-action">{lead.next_best_action}</button>
                    ) : (
                      String(cell.getValue() || "–")
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      {!leads.length && <div className="empty">No leads match this view. Adjust the filter or load demo data.</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ethics page
// ---------------------------------------------------------------------------
function Ethics() {
  return (
    <div className="content ethics">
      <div className="eyebrow">Utilities / governance</div>
      <h1>Data & ethics</h1>
      <p className="subtitle">SignalDesk works with public business-level data and makes uncertainty visible.</p>
      <Card>
        <h2>Collection principles</h2>
        <ul>
          <li>Public business data only. No private-person harvesting.</li>
          <li>Honor robots.txt, site terms, and per-domain rate limits.</li>
          <li>Use an honest User-Agent and degrade gracefully on 429s, blocks, or CAPTCHAs.</li>
          <li>OpenStreetMap discovery is attributed and subject to ODbL.</li>
          <li>The bundled dataset is synthetic and contains no real customer records.</li>
          <li>AI readiness scores are sourced from live web search — never hardcoded.</li>
          <li>Industry match and geography location counts are verified by LLM web search grounding.</li>
        </ul>
        <Button variant="secondary" onClick={() => (location.href = "/workspace")}>Back to workspace</Button>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Export / download
// ---------------------------------------------------------------------------
function download(leads: Lead[]) {
  const fields = [
    "company_name", "domain", "industry", "city", "region",
    "employees", "revenue_estimate", "email", "phone",
    "buy_box_score", "score_tier", "confidence_score", "next_best_action",
  ];
  const csv = [
    fields.join(","),
    ...leads.map((lead) =>
      fields.map((field) => JSON.stringify((lead as unknown as Record<string, unknown>)[field] ?? "")).join(","),
    ),
  ].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "signaldesk-leads.csv";
  a.click();
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
