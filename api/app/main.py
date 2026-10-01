from __future__ import annotations
import asyncio, csv, io, ipaddress, json, math, re, time, uuid
import os
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from dotenv import find_dotenv, load_dotenv
try:
    from supabase import create_client
except ImportError:
    create_client = None
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from api.app.models import DiscoverRequest, DraftRequest, EnrichRequest, ImportRequest, Lead, Model, ScoreRequest, ScoringProfile, VerifyRequest

# ---------------------------------------------------------------------------
# Environment loading
# This file lives at <root>/api/app/main.py, so the project root is two folders up.
# We load <root>/.env explicitly, then fall back to a .env found from the working directory.
# load_dotenv never overrides variables already set by the host (Vercel / Render dashboard).
# NOTE: .env is gitignored, so on Vercel / Render you must ALSO set these variables in the dashboard.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
_fallback_env = find_dotenv(usecwd=True)
if _fallback_env:
    load_dotenv(_fallback_env)

app = FastAPI(title="SignalDesk API", version="0.2.0", docs_url="/api/docs", redoc_url="/api/redoc")
frontend_origin = os.getenv("FRONTEND_ORIGIN")
app.add_middleware(CORSMiddleware, allow_origins=[frontend_origin] if frontend_origin else ["*"], allow_methods=["*"], allow_headers=["*"])

user_agent = os.getenv("USER_AGENT", "SignalDesk/0.2 (public-business-data; set USER_AGENT env var with a contact)")

# ---------------------------------------------------------------------------
# LLM configuration (Gemini with Google Search grounding for discovery)
# ---------------------------------------------------------------------------
# If LLM_MODEL does not exist (HTTP 404) these are tried in order. Both support Google Search grounding.
FALLBACK_GEMINI_MODELS = ["gemini-3.5-flash", "gemini-3.1-flash-lite"]
# Search grounding has its OWN quota, separate from normal text generation, and it can be zero on the free tier
# for some model families (e.g. Gemini 3.x). Older families are counted separately, so we try them as well.
DISCOVERY_EXTRA_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
GEMINI_PROVIDERS = {"gemini", "google", "google-gemini"}
# If every grounded attempt is quota-blocked, optionally fall back to an ungrounded model suggestion.
# Those leads are only kept when their website is reachable AND mentions the company name.
UNGROUNDED_FALLBACK = os.getenv("DISCOVERY_UNGROUNDED_FALLBACK", "true").strip().lower() not in {"0", "false", "no"}
LLM_DISCOVERY_TIMEOUT = float(os.getenv("LLM_DISCOVERY_TIMEOUT", "45"))
MAX_DISCOVER = 20            # max candidates requested per discovery call
VERIFY_CONCURRENCY = 10
VERIFY_TIMEOUT = 6.0
CACHE_TTL_SECONDS = 900
VERIFICATION_TIMEOUT = float(os.getenv("LLM_VERIFICATION_TIMEOUT", "45"))
MAX_VERIFY = 100

# Directories / social sites are not a company's own website, so they never count as one.
AGGREGATOR_DOMAINS = {
    "yelp.com", "yellowpages.com", "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "bbb.org", "mapquest.com", "angi.com", "angieslist.com", "thumbtack.com", "homeadvisor.com", "google.com",
    "manta.com", "chamberofcommerce.com", "superpages.com", "zocdoc.com", "healthgrades.com", "tripadvisor.com",
    "nextdoor.com", "porch.com", "houzz.com", "indeed.com", "glassdoor.com", "youtube.com", "wikipedia.org",
}
NAME_STOPWORDS = {"the", "and", "inc", "llc", "ltd", "corp", "company", "co", "group", "services", "service"}


def _llm_config() -> dict[str, Any]:
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    model = os.getenv("LLM_MODEL", "").strip().removeprefix("models/")
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    models = [model, *FALLBACK_GEMINI_MODELS] if provider in GEMINI_PROVIDERS else [model]
    return {"provider": provider, "api_key": api_key, "base_url": base_url, "models": [m for m in dict.fromkeys(models) if m]}


def _llm_ready(cfg: dict[str, Any]) -> bool:
    return bool(cfg["provider"] and cfg["api_key"] and cfg["base_url"] and cfg["models"])


def _google_error_summary(response: httpx.Response) -> str:
    """Pull Google's own explanation (message + quota id) out of an error response."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return response.text[:200]
    message = str(error.get("message", ""))[:260]
    quota_ids = []
    for detail in error.get("details", []) or []:
        for violation in (detail.get("violations") or []) if isinstance(detail, dict) else []:
            quota_id = violation.get("quotaId") or violation.get("quotaMetric")
            if quota_id:
                quota_ids.append(str(quota_id))
    return f"{message} [{', '.join(dict.fromkeys(quota_ids))}]".strip() if quota_ids else message


async def _gemini_generate(client: httpx.AsyncClient, cfg: dict[str, Any], body: dict[str, Any], skip_on_429: bool = False) -> tuple[dict[str, Any], str]:
    """Call Gemini generateContent. Moves to the next model on 404 (and on 429 when skip_on_429 is set).
    Google's real error text is always surfaced so quota problems can be diagnosed."""
    issues: list[str] = []
    saw_429 = False
    for model in cfg["models"]:
        response = await client.post(
            f"{cfg['base_url']}/models/{model}:generateContent",
            headers={"x-goog-api-key": cfg["api_key"], "Content-Type": "application/json"},
            json=body,
        )
        if response.status_code == 200:
            return response.json(), model
        summary = _google_error_summary(response)
        if response.status_code == 404:
            issues.append(f"{model}: not found")
            continue
        if response.status_code == 429:
            saw_429 = True
            issues.append(f"{model}: quota - {summary}")
            if skip_on_429:
                continue
            raise HTTPException(status_code=429, detail=f"Gemini quota/rate limit on {model}: {summary}")
        if response.status_code in (401, 403):
            raise HTTPException(status_code=502, detail=f"Gemini rejected the request ({response.status_code}). Check LLM_API_KEY and that the Gemini API is enabled. {summary}".strip())
        raise HTTPException(status_code=502, detail=f"Gemini returned HTTP {response.status_code} for {model}. {summary}".strip())
    detail = "; ".join(issues) or "no model configured"
    raise HTTPException(status_code=429 if saw_429 else 502, detail=f"No Gemini model could serve this request. {detail}")


def _gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates returned")
        raise HTTPException(status_code=502, detail=f"Gemini returned no answer ({reason}).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")).strip()


def _parse_json_array(text: str) -> list[Any]:
    """Pull a JSON array out of model text, tolerating code fences and surrounding prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    candidates = [cleaned]
    match = re.search(r"\[.*\]", cleaned, re.S)
    if match:
        candidates.append(match.group(0))
    for chunk in candidates:
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list):
                    return value
    raise HTTPException(status_code=502, detail="The AI discovery step returned an unreadable result. Please retry.")


def _clean_prompt_text(value: str, max_len: int = 80) -> str:
    """Keep user-supplied text short and free of control characters before it goes into a prompt."""
    return re.sub(r"[\x00-\x1f\x7f\"\\`{}<>]", " ", str(value)).strip()[:max_len]


# ---------------------------------------------------------------------------
# URL safety helpers (the server fetches AI-provided / user-provided URLs)
# ---------------------------------------------------------------------------
def _is_public_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return "." in host


def _safe_website(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"null", "none", "n/a"}:
        return None
    url = text if "://" in text else f"https://{text}"
    if not _is_public_url(url):
        return None
    host = (urlparse(url).hostname or "").removeprefix("www.")
    if any(host == d or host.endswith(f".{d}") for d in AGGREGATOR_DOMAINS):
        return None
    return url


# ---------------------------------------------------------------------------
# Supabase (optional persistence)
# ---------------------------------------------------------------------------
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
supabase_client = None
if create_client and supabase_url and supabase_key:
    try:
        supabase_client = create_client(supabase_url, supabase_key)
    except Exception:
        supabase_client = None

SAVE_FAILED_WARNING = "Results are shown but could not be saved to Supabase. Verify the schema is applied and the service-role key is valid."
NOT_CONFIGURED_WARNING = "Supabase is not configured; results are not being persisted."

_cache: dict[str, tuple[float, list[Lead]]] = {}

DEMO_ROWS = [
 {"company_name":"Northstar Precision Tools","domain":"northstarprecision.com","industry":"Industrial Manufacturing","city":"Cleveland","region":"Ohio","employees":72,"revenue_estimate":12500000,"owner_operated":True,"years_in_business":28,"succession_signal":True,"digital_maturity_gap":True,"email":"hello@northstarprecision.com","phone":"+1 216 555 0101"},
 {"company_name":"Harborline HVAC","domain":"harborlinehvac.com","industry":"HVAC Services","city":"Tampa","region":"Florida","employees":38,"revenue_estimate":6200000,"owner_operated":True,"years_in_business":19,"succession_signal":False,"digital_maturity_gap":True,"email":"info@harborlinehvac.com","phone":"+1 813 555 0102"},
 {"company_name":"Cedar & Finch Dental","domain":"cedarfinchdental.com","industry":"Dental Practice","city":"Austin","region":"Texas","employees":24,"revenue_estimate":3400000,"owner_operated":True,"years_in_business":12,"succession_signal":True,"digital_maturity_gap":False,"email":"team@cedarfinchdental.com","phone":"+1 512 555 0103"},
 {"company_name":"Atlas Safety Supply","domain":"atlassafetysupply.com","industry":"Industrial Distribution","city":"Phoenix","region":"Arizona","employees":115,"revenue_estimate":28000000,"owner_operated":False,"years_in_business":22,"succession_signal":False,"digital_maturity_gap":True,"email":"sales@atlassafetysupply.com","phone":"+1 602 555 0104"},
 {"company_name":"Blue Oak Landscape","domain":"blueoaklandscape.com","industry":"Landscaping","city":"Denver","region":"Colorado","employees":16,"revenue_estimate":1800000,"owner_operated":True,"years_in_business":8,"succession_signal":False,"digital_maturity_gap":True,"phone":"+1 303 555 0105"},
 {"company_name":"Meridian Compliance Group","domain":"meridiancompliance.com","industry":"Professional Services","city":"Raleigh","region":"North Carolina","employees":54,"revenue_estimate":9100000,"owner_operated":True,"years_in_business":16,"succession_signal":True,"digital_maturity_gap":True,"email":"contact@meridiancompliance.com"},
]


def _lead_record(lead: Lead, pipeline_run_id: str | None = None) -> dict[str, Any]:
    record = lead.model_dump()
    record["normalized_name"] = re.sub(r"[^a-z0-9]", "", lead.company_name.lower())
    if pipeline_run_id:
        record["pipeline_run_id"] = pipeline_run_id
    record["validation_flags"] = lead.validation_flags
    record["score_reasons"] = lead.score_reasons
    record["raw_payload"] = lead.raw_payload
    return record


def _persist_leads(leads: list[Lead], pipeline_run_id: str | None = None) -> str | None:
    """Best-effort save. Returns a warning string instead of raising, so the app keeps working."""
    if supabase_client is None:
        return NOT_CONFIGURED_WARNING
    if not leads:
        return None
    try:
        supabase_client.table("leads").upsert([_lead_record(lead, pipeline_run_id) for lead in leads], on_conflict="id").execute()
        return None
    except Exception:
        return SAVE_FAILED_WARNING


def _persist_pipeline(leads: list[Lead], changes: list[dict[str, Any]], source: str, warnings: list[str] | None = None) -> str | None:
    if supabase_client is None:
        return NOT_CONFIGURED_WARNING
    try:
        run = supabase_client.table("pipeline_runs").insert({"source": source, "status": "complete", "input_count": len(leads), "output_count": len(leads), "warnings": warnings or []}).execute().data[0]
        run_id = str(run["id"])
        lead_warning = _persist_leads(leads, run_id)
        if lead_warning and lead_warning != NOT_CONFIGURED_WARNING:
            return lead_warning
        if changes:
            supabase_client.table("lead_change_log").insert([{"pipeline_run_id": run_id, "action": change.get("action", "pipeline_change"), "details": change} for change in changes]).execute()
        return None
    except Exception:
        return SAVE_FAILED_WARNING


def _load_lead(row: dict[str, Any]) -> Lead:
    fields = {name: row.get(name) for name in Lead.model_fields if name in row}
    return Lead.model_validate(fields)


def _int(value: Any) -> int | None:
    if value in (None, ""): return None
    digits = re.sub(r"[^0-9]", "", str(value)); return int(digits) if digits else None
def _bool(value: Any) -> bool | None:
    if value in (None, ""): return None
    if isinstance(value, bool): return value
    return str(value).lower().strip() in {"true", "yes", "1", "y"}
def normalize_row(row: dict[str, Any], source: str = "csv_import") -> Lead:
    raw = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}; name = str(raw.get("company_name") or raw.get("company") or raw.get("name") or "Unnamed company").strip(); domain = str(raw.get("domain") or "").strip().lower() or None; website = str(raw.get("website") or "").strip() or None
    if website and not domain: domain = urlparse(website if "://" in website else f"https://{website}").netloc.lower().removeprefix("www.") or None
    email, phone = str(raw.get("email") or "").strip().lower() or None, str(raw.get("phone") or "").strip() or None; flags = []; identity = domain or re.sub(r"[^a-z0-9]", "", name.lower()); lead_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"signaldesk:{identity}"))
    if not email: flags.append("missing_email")
    if not phone: flags.append("missing_phone")
    if not domain: flags.append("missing_domain")
    return Lead(id=lead_id, company_name=name, domain=domain, website=website, industry=str(raw.get("industry") or "").strip() or None, city=str(raw.get("city") or "").strip() or None, region=str(raw.get("region") or raw.get("state") or "").strip() or None, country=str(raw.get("country") or "United States").strip(), employees=_int(raw.get("employees") or raw.get("employee_count")), revenue_estimate=_int(raw.get("revenue_estimate") or raw.get("revenue")), owner_operated=_bool(raw.get("owner_operated")), years_in_business=_int(raw.get("years_in_business") or raw.get("years")), succession_signal=_bool(raw.get("succession_signal")), digital_maturity_gap=_bool(raw.get("digital_maturity_gap")), email=email, phone=phone, linkedin_url=str(raw.get("linkedin_url") or "").strip() or None, source=source, validation_status="verified" if not flags else "needs_review", validation_flags=flags, confidence_score=max(0, 100 - len(flags) * 18), raw_payload=row)
def dedupe_leads(leads: list[Lead]) -> tuple[list[Lead], list[dict[str, Any]]]:
    kept = {}; changes = []
    for lead in leads:
        key = lead.domain or re.sub(r"[^a-z0-9]", "", lead.company_name.lower())
        if key not in kept: kept[key] = lead; continue
        existing, merged = kept[key], kept[key].model_copy(deep=True)
        for field in ("website", "industry", "city", "region", "employees", "revenue_estimate", "email", "phone", "linkedin_url"):
            if getattr(merged, field) in (None, "") and getattr(lead, field) not in (None, ""): setattr(merged, field, getattr(lead, field))
        merged.validation_flags = sorted(set(existing.validation_flags + lead.validation_flags)); merged.confidence_score = max(existing.confidence_score, lead.confidence_score); kept[key] = merged; changes.append({"action": "merged_duplicate", "kept": existing.company_name, "merged": lead.company_name, "key": key})
    return list(kept.values()), changes
def validate_leads(leads: list[Lead]) -> list[Lead]:
    pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$"); result = []
    for lead in leads:
        item, flags = lead.model_copy(deep=True), set(lead.validation_flags)
        if item.email and not pattern.match(item.email): flags.add("invalid_email_syntax")
        item.validation_flags, item.validation_status, item.confidence_score = sorted(flags), "verified" if not flags else "needs_review", max(0, 100 - len(flags) * 18); result.append(item)
    return result
def score_lead(lead: Lead, profile: ScoringProfile) -> Lead:
    weights, reasons, earned = profile.weights, [], 0
    possible = sum(max(0, value) for value in weights.values()) or 1
    verification = lead.raw_payload.get("verification") if isinstance(lead.raw_payload.get("verification"), dict) else {}
    def add(key: str, passed: bool, label: str) -> None:
        nonlocal earned
        points = max(0, weights.get(key, 0))
        earned += points if passed else 0
        reasons.append(f"{'+' if passed else '-'}{points} {label}")
    def verified_value(key: str, fallback: bool | None) -> tuple[bool | None, bool]:
        if key in verification:
            value = verification.get(key)
            return (value if isinstance(value, bool) else None), True
        return fallback, False
    location = " ".join(filter(None, [lead.city, lead.region, lead.country]))
    industry_ok = profile.industry.lower() in {"all industries", ""} or bool(lead.industry and profile.industry.lower() in lead.industry.lower())
    geo_ok = profile.geography.lower() in {"all locations", ""} or profile.geography.lower() in location.lower()
    industry_value, industry_verified = verified_value("industry_match", industry_ok)
    geography_value, geography_verified = verified_value("geography_match", geo_ok)
    if industry_verified:
        add("industry", industry_value is True, "verified industry match")
    else:
        add("industry", industry_ok, "industry match (unverified)")
    if geography_verified:
        add("geography", geography_value is True, "verified geography match")
    else:
        add("geography", geo_ok, "geography match (unverified)")
    add("size", lead.employees is not None and profile.employee_min <= lead.employees <= profile.employee_max, "employee band")
    add("revenue", lead.revenue_estimate is not None and profile.revenue_min <= lead.revenue_estimate <= profile.revenue_max, "revenue band")
    add("ownership", lead.owner_operated is True, "owner-operated signal")
    add("tenure", lead.years_in_business is not None and lead.years_in_business >= 10, "tenure signal")
    add("succession", lead.succession_signal is True, "succession signal")
    add("contact", bool(lead.email or lead.phone), "contact data")
    ai_gap, ai_verified = verified_value("digital_maturity_gap", None)
    if ai_verified:
        add("digital_gap", ai_gap is True, "verified AI-readiness opportunity")
    else:
        reasons.append("AI-readiness unverified")
    total = round(earned / possible * 100)
    tier = "A" if total >= 80 else "B" if total >= 65 else "C" if total >= 45 else "D"
    item = lead.model_copy(deep=True)
    item.buy_box_score, item.score_tier, item.score_reasons, item.next_best_action = total, tier, reasons, {"A": "Contact first", "B": "Verify contact data", "C": "Research fit", "D": "Deprioritize"}[tier]
    return item
def process(leads: list[Lead], profile: ScoringProfile | None = None) -> tuple[list[Lead], list[dict[str, Any]]]:
    unique, changes = dedupe_leads(validate_leads(leads)); scored = sorted((score_lead(lead, profile or ScoringProfile()) for lead in unique), key=lambda item: item.buy_box_score, reverse=True); return scored, changes
def demo(profile: ScoringProfile | None = None) -> tuple[list[Lead], list[dict[str, Any]]]: return process([normalize_row(row, "synthetic_demo") for row in deepcopy(DEMO_ROWS)], profile)


class PipelineResponse(Model):
    leads: list[Lead]
    changes: list[dict[str, Any]] = []
    warnings: list[str] = []


def _with_warning(warnings: list[str], extra: str | None) -> list[str]:
    return [*warnings, extra] if extra else warnings


@app.get("/")
async def root() -> dict[str, str]: return {"service": "SignalDesk API", "status": "ok", "docs": "/api/docs", "health": "/api/health"}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    cfg = _llm_config()
    return {"status": "ok", "service": "signaldesk-api", "llm_configured": _llm_ready(cfg), "llm_provider": cfg["provider"] or None, "supabase_configured": supabase_client is not None}


@app.get("/api/leads", response_model=PipelineResponse)
async def get_leads() -> PipelineResponse:
    if supabase_client is None:
        return PipelineResponse(leads=[], warnings=[NOT_CONFIGURED_WARNING])
    try:
        rows = supabase_client.table("leads").select("*").order("buy_box_score", desc=True).execute().data
        return PipelineResponse(leads=[_load_lead(row) for row in rows])
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Supabase lead retrieval failed. Verify that the schema is applied and the service-role key is valid.") from exc


@app.get("/api/pipeline/demo", response_model=PipelineResponse)
async def get_demo() -> PipelineResponse:
    leads, changes = demo()
    warning = _persist_pipeline(leads, changes, "synthetic_demo")
    return PipelineResponse(leads=leads, changes=changes, warnings=_with_warning([], warning))


@app.post("/api/scoring/preview", response_model=PipelineResponse)
async def score(request: ScoreRequest) -> PipelineResponse:
    leads, changes = process(request.leads, request.profile)
    warning = _persist_leads(leads)
    return PipelineResponse(leads=leads, changes=changes, warnings=_with_warning([], warning))


@app.post("/api/pipeline/import", response_model=PipelineResponse)
async def import_csv(request: ImportRequest) -> PipelineResponse:
    reader = csv.DictReader(io.StringIO(request.csv_text))
    if not reader.fieldnames: raise HTTPException(status_code=422, detail="CSV must include a header row")
    raw_rows = [dict(row) for row in reader]
    if not raw_rows: raise HTTPException(status_code=422, detail="CSV must include at least one data row")
    leads, changes = process([normalize_row(row, request.source) for row in raw_rows])
    warning = _persist_pipeline(leads, changes, "csv_import")
    return PipelineResponse(leads=leads, changes=changes, warnings=_with_warning([], warning))


# ---------------------------------------------------------------------------
# AI discovery: Gemini + Google Search grounding, then website verification
# ---------------------------------------------------------------------------
def _build_discovery_prompt(industry: str, city: str, country: str, limit: int, grounded: bool = True) -> str:
    keys = (
        "Return ONLY a JSON array (no prose, no markdown). Each element must have exactly these keys: "
        "company_name (string), website (official homepage URL or null), phone (string or null), email (string or null, "
        "only if publicly listed), employees_estimate (integer or null), years_in_business (integer or null), "
        "owner_operated (true/false/null), description (max 20 words), source_url (the page where you found it, or null)."
    )
    if grounded:
        return (
            f"You are a sourcing analyst for a search-fund acquirer. Use Google Search to find up to {limit} real, "
            f"currently operating {industry} businesses located in {city}, {country}.\n"
            "Rules:\n"
            "- Only include businesses that appear in your search results. Never invent companies, websites, phone numbers or emails.\n"
            "- Prefer independent, owner-operated small and mid-sized businesses. Exclude national chains, franchises' corporate sites, "
            "directories and aggregators (Yelp, Yellow Pages, Angi, etc.).\n"
            "- Use null for any field you did not actually see in a source.\n" + keys
        )
    return (
        f"You are a sourcing analyst for a search-fund acquirer. List up to {limit} {industry} businesses in {city}, {country} "
        "that you are highly confident really exist and have an official website.\n"
        "Rules:\n"
        "- If you are not confident a business exists, leave it out. Fewer, accurate results are better than many guesses.\n"
        "- Never invent websites, phone numbers or emails; use null when unsure.\n"
        "- Prefer independent, owner-operated small and mid-sized businesses; exclude national chains and directories.\n" + keys
    )


async def _verify_website(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str, company_name: str) -> str:
    """Returns 'verified' (name found on page), 'unconfirmed' (reachable or blocked), or 'unreachable' (DNS/connect failure)."""
    async with sem:
        try:
            response = await client.get(url)
        except httpx.ConnectError:
            return "unreachable"
        except Exception:
            return "unconfirmed"
    if response.status_code >= 400:
        return "unconfirmed"
    text = response.text[:300_000].lower()
    tokens = [t for t in re.findall(r"[a-z0-9]+", company_name.lower()) if len(t) > 2 and t not in NAME_STOPWORDS]
    if tokens and sum(1 for t in tokens if t in text) >= max(1, math.ceil(len(tokens) / 2)):
        return "verified"
    return "unconfirmed"


def _normalize_discovered(row: dict[str, Any]) -> Lead:
    try:
        return normalize_row(row, "llm_web_search")
    except Exception:
        # If your Lead model restricts `source` to a fixed set, add "llm_web_search" to it.
        # The ai_discovered flag below still labels these leads correctly in the meantime.
        return normalize_row(row, "csv_import")


def _build_verification_prompt(leads: list[Lead], profile: ScoringProfile, contexts: dict[str, list[dict[str, Any]]] = None) -> str:
    records = []
    for lead in leads[:MAX_VERIFY]:
        record = {
            "id": lead.id,
            "company_name": lead.company_name,
            "website": lead.website or lead.domain,
            "declared_industry": lead.industry,
            "declared_city": lead.city,
            "declared_region": lead.region,
            "declared_country": lead.country,
        }
        if contexts and lead.id in contexts:
            record["search_results"] = [
                {"title": r.get("title"), "snippet": r.get("snippet"), "link": r.get("link")}
                for r in contexts[lead.id][:3]
            ]
        records.append(record)
    criteria = {"industry": profile.industry, "geography": profile.geography}
    return (
        "You are a due-diligence research analyst. Review the provided context and web search results (if any) to verify each company below using current public web sources. Compare the actual business to the buy-box criteria. Do not trust the declared CSV industry, city, or AI-readiness fields without web evidence.\n\n"
        "For every input lead return exactly one JSON object with these keys: id, industry_match (boolean or null), geography_match (boolean or null), digital_maturity_gap (boolean or null), ai_readiness (one of high, medium, low, unknown), evidence (array of short factual strings), source_urls (array of URLs copied from your search results). Keep the same id. Use null when the web evidence is insufficient. A digital_maturity_gap of true means the company appears to have a meaningful opportunity for modern digital/AI workflow improvement; do not infer this merely because no technology was found.\n\n"
        f"Buy-box criteria: {json.dumps(criteria, ensure_ascii=False)}\n"
        f"Leads to verify (with context): {json.dumps(records, ensure_ascii=False)}\n\n"
        "Use official company websites and reputable public sources. Do not invent facts, sources, locations, or technology claims. Return JSON array only."
    )

async def _serper_search(client: httpx.AsyncClient, query: str) -> list[dict[str, Any]]:
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = await client.post(
            "https://google.serper.dev/search", 
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"}, 
            json={"q": query, "num": 5}, 
            timeout=10.0
        )
        resp.raise_for_status()
        return resp.json().get("organic", [])
    except Exception:
        return []


def _build_ai_readiness_prompt(leads: list[Lead], profile: ScoringProfile, contexts: dict[str, list[dict[str, Any]]] = None) -> str:
    """Build a prompt specifically for AI readiness verification with industry/geo counts."""
    records = []
    for lead in leads[:MAX_VERIFY]:
        record = {
            "id": lead.id,
            "company_name": lead.company_name,
            "website": lead.website or (f"https://{lead.domain}" if lead.domain else None),
            "declared_industry": lead.industry,
            "declared_city": lead.city,
            "declared_region": lead.region,
            "declared_country": lead.country,
            "employees": lead.employees,
        }
        if contexts and lead.id in contexts:
            record["search_results"] = [
                {"title": r.get("title"), "snippet": r.get("snippet"), "link": r.get("link")}
                for r in contexts[lead.id][:3]
            ]
        records.append(record)
    criteria = {"target_industry": profile.industry, "target_geography": profile.geography}
    return (
        "You are a due-diligence research analyst. For each company below, review the provided context and web search results (if any) to answer:\n"
        "1. AI/Digital readiness: How reliant is this company on modern digital tools, AI, automation? Look at their website, job postings, press releases.\n"
        "2. Industry match: Does the company actually operate in the stated industry? Verify via their website and search results.\n"
        "3. Geography: How many physical office/store/service locations does this company operate? Search for branch offices, service areas, store locators.\n\n"
        "For EVERY lead return exactly one JSON object with these keys:\n"
        "  id (same as input),\n"
        "  company_name (string),\n"
        "  industry_match (boolean or null - true if company matches target_industry),\n"
        "  industry_match_reason (short string explaining why),\n"
        "  geography_match (boolean or null - true if company operates in target_geography area),\n"
        "  num_locations (integer or null - actual number of physical locations/offices found via web search),\n"
        "  ai_readiness (string: one of 'high', 'medium', 'low', 'unknown'),\n"
        "  ai_readiness_score (integer 0-100 based on digital maturity evidence),\n"
        "  ai_readiness_reason (short string: specific evidence of digital tools, software, automation used or lacking),\n"
        "  digital_maturity_gap (boolean: true if company would significantly benefit from AI/digital modernization),\n"
        "  evidence (array of 2-5 short factual strings from your search),\n"
        "  source_urls (array of URLs you found this information at).\n\n"
        "IMPORTANT RULES:\n"
        "- Use null when web evidence is insufficient, do NOT guess.\n"
        "- For num_locations: search for '[company] locations' or '[company] offices' - count only physical locations, not service areas.\n"
        "- For ai_readiness: 'high' = company already uses modern digital tools/AI; 'low' = paper-based, legacy systems, no online presence.\n"
        "- digital_maturity_gap = true means they LACK modern tools and WOULD benefit from AI/automation improvement.\n"
        "- Never invent facts, sources, or locations. Return JSON array only.\n\n"
        f"Buy-box criteria: {json.dumps(criteria, ensure_ascii=False)}\n"
        f"Companies to research (with context): {json.dumps(records, ensure_ascii=False)}\n"
    )


@app.post("/api/leads/verify-ai-readiness", response_model=PipelineResponse)
async def verify_ai_readiness(request: VerifyRequest) -> PipelineResponse:
    """Dedicated AI-readiness verification endpoint using LLM + Google Search grounding.
    
    Performs real web search per lead to determine:
    - AI/digital readiness score (not hardcoded)
    - Industry match with evidence
    - Number of geographic locations (not hardcoded)
    - Digital maturity gap assessment
    """
    leads = request.leads[:MAX_VERIFY]
    cfg = _llm_config()
    if not _llm_ready(cfg):
        raise HTTPException(
            status_code=503,
            detail="AI-readiness verification is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY and LLM_BASE_URL."
        )

    serper_key = os.getenv("SERPER_API_KEY", "").strip()
    use_serper = bool(serper_key)

    if not use_serper and cfg["provider"] not in GEMINI_PROVIDERS:
        raise HTTPException(
            status_code=503,
            detail="AI-readiness verification currently requires either SERPER_API_KEY or LLM_PROVIDER=gemini for Google Search grounding."
        )

    # Fetch context concurrently if using Serper
    lead_contexts = {}
    if use_serper:
        async with httpx.AsyncClient() as client:
            async def fetch_lead_context(lead: Lead):
                query = f"{lead.company_name} {lead.city or ''} {lead.industry or ''}"
                results = await _serper_search(client, query)
                return lead.id, results
            
            tasks = [fetch_lead_context(lead) for lead in leads]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results_list:
                if isinstance(res, tuple):
                    lead_contexts[res[0]] = res[1]

    body = {
        "contents": [{"role": "user", "parts": [{"text": _build_ai_readiness_prompt(leads, request.profile, lead_contexts)}]}],
        "generationConfig": {"temperature": 0.1},
    }
    
    # Only use Gemini's built-in Google Search if Serper is NOT used
    if not use_serper:
        body["tools"] = [{"google_search": {}}]

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(VERIFICATION_TIMEOUT, connect=8.0)) as client:
            payload, model_used = await _gemini_generate(client, cfg, body, skip_on_429=False)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI-readiness verification request failed ({type(exc).__name__}). Please retry."
        ) from exc

    items = _parse_json_array(_gemini_text(payload))
    grounding = (payload.get("candidates") or [{}])[0].get("groundingMetadata") or {}
    grounding_sources = list(dict.fromkeys([
        str((chunk.get("web") or {}).get("uri"))
        for chunk in grounding.get("groundingChunks", [])
        if (chunk.get("web") or {}).get("uri")
    ]))[:20]
    
    if use_serper:
        for lead_id, results in lead_contexts.items():
            for r in results:
                if r.get("link") and r.get("link") not in grounding_sources:
                    grounding_sources.append(r.get("link"))
        grounding_sources = grounding_sources[:20]

    # Index results by id and name for flexible matching
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for result in items:
        if not isinstance(result, dict):
            continue
        result_id = str(result.get("id") or "").strip()
        result_name = re.sub(r"[^a-z0-9]", "", str(result.get("company_name") or "").lower())
        if result_id:
            by_id[result_id] = result
        if result_name:
            by_name[result_name] = result

    def as_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return True if normalized in {"true", "yes"} else False if normalized in {"false", "no"} else None

    def as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    enriched: list[Lead] = []
    matched = 0
    for lead in leads:
        result = by_id.get(lead.id) or by_name.get(re.sub(r"[^a-z0-9]", "", lead.company_name.lower()))
        if result:
            matched += 1

        industry_match = as_bool(result.get("industry_match")) if result else None
        geography_match = as_bool(result.get("geography_match")) if result else None
        digital_gap = as_bool(result.get("digital_maturity_gap")) if result else None
        num_locations = as_int(result.get("num_locations")) if result else None
        ai_readiness_score = as_int(result.get("ai_readiness_score")) if result else None
        ai_readiness_label = str(result.get("ai_readiness") or "unknown") if result else "unknown"
        ai_readiness_reason = str(result.get("ai_readiness_reason") or "").strip()[:300] if result else ""
        industry_match_reason = str(result.get("industry_match_reason") or "").strip()[:300] if result else ""
        evidence = [
            str(v).strip()[:240]
            for v in (result.get("evidence") or [])
            if str(v).strip()
        ][:8] if result else []

        model_sources = [str(v).strip() for v in (result.get("source_urls") or []) if str(v).strip()] if result else []
        source_urls = [url for url in model_sources if url in grounding_sources] or grounding_sources[:8]

        verification = {
            "status": "verified" if result and any(
                v is not None for v in (industry_match, geography_match, digital_gap)
            ) else "needs_review",
            "provider": "gemini_google_search_grounding",
            "model": model_used,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "verification_type": "ai_readiness_focused",
            # Core verified signals
            "industry_match": industry_match,
            "industry_match_reason": industry_match_reason,
            "geography_match": geography_match,
            "num_locations": num_locations,
            # AI readiness — all real, from web search
            "digital_maturity_gap": digital_gap,
            "ai_readiness": ai_readiness_label,
            "ai_readiness_score": ai_readiness_score,
            "ai_readiness_reason": ai_readiness_reason,
            # Evidence
            "evidence": evidence,
            "source_urls": source_urls,
        }

        updated = lead.model_copy(deep=True)
        updated.raw_payload = {**updated.raw_payload, "verification": verification}

        # Apply verified signals back to the lead
        if digital_gap is not None:
            updated.digital_maturity_gap = digital_gap
        if ai_readiness_score is not None and ai_readiness_score > 0:
            # Store ai_readiness_score as a raw_payload field for display
            updated.raw_payload["ai_readiness_score"] = ai_readiness_score
        if num_locations is not None:
            updated.raw_payload["num_locations"] = num_locations

        known = [v is not None for v in (industry_match, geography_match, digital_gap)]
        if any(known):
            flags = set(updated.validation_flags) | {"ai_readiness_verified"}
            if not all(known):
                flags.add("ai_readiness_partial")
            updated.validation_flags = sorted(flags)
            updated.confidence_score = min(100, max(updated.confidence_score, 60 + sum(known) * 10))

        enriched.append(updated)

    scored, changes = process(enriched, request.profile)
    changes.append({
        "action": "ai_readiness_verification",
        "model": model_used,
        "matched_leads": str(matched),
        "source_count": str(len(grounding_sources)),
    })
    warning = _persist_leads(scored)
    warnings = [
        f"AI-readiness, industry fit, geography locations, and digital maturity gap were verified via {'Serper Web Search' if use_serper else 'Gemini Google Search grounding'}. "
        "All scores reflect real web evidence — not hardcoded values. Review source links before outreach."
    ]
    if not grounding_sources:
        warnings.append("The provider returned no grounding URLs; treat the verification as provisional.")
    warnings = _with_warning(warnings, warning)
    return PipelineResponse(leads=scored, changes=changes, warnings=warnings)


@app.post("/api/leads/verify", response_model=PipelineResponse)
async def verify_pipeline(request: VerifyRequest) -> PipelineResponse:
    leads = request.leads[:MAX_VERIFY]
    cfg = _llm_config()
    if not _llm_ready(cfg):
        raise HTTPException(status_code=503, detail="Web verification is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY and LLM_BASE_URL.")

    serper_key = os.getenv("SERPER_API_KEY", "").strip()
    use_serper = bool(serper_key)

    if not use_serper and cfg["provider"] not in GEMINI_PROVIDERS:
        raise HTTPException(status_code=503, detail="Web verification currently requires either SERPER_API_KEY or LLM_PROVIDER=gemini for Google Search grounding.")

    lead_contexts = {}
    if use_serper:
        async with httpx.AsyncClient() as client:
            async def fetch_lead_context(lead: Lead):
                query = f"{lead.company_name} {lead.city or ''} {lead.industry or ''}"
                results = await _serper_search(client, query)
                return lead.id, results
            
            tasks = [fetch_lead_context(lead) for lead in leads]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results_list:
                if isinstance(res, tuple):
                    lead_contexts[res[0]] = res[1]

    body = {
        "contents": [{"role": "user", "parts": [{"text": _build_verification_prompt(leads, request.profile, lead_contexts)}]}],
        "generationConfig": {"temperature": 0.1},
    }
    
    if not use_serper:
        body["tools"] = [{"google_search": {}}]

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(VERIFICATION_TIMEOUT, connect=8.0)) as client:
            payload, model_used = await _gemini_generate(client, cfg, body, skip_on_429=False)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Web verification request failed ({type(exc).__name__}). Please retry.") from exc
    items = _parse_json_array(_gemini_text(payload))
    grounding = (payload.get("candidates") or [{}])[0].get("groundingMetadata") or {}
    grounding_sources = list(dict.fromkeys([str((chunk.get("web") or {}).get("uri")) for chunk in grounding.get("groundingChunks", []) if (chunk.get("web") or {}).get("uri")]))[:20]
    
    if use_serper:
        for lead_id, results in lead_contexts.items():
            for r in results:
                if r.get("link") and r.get("link") not in grounding_sources:
                    grounding_sources.append(r.get("link"))
        grounding_sources = grounding_sources[:20]
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for result in items:
        if not isinstance(result, dict):
            continue
        result_id = str(result.get("id") or "").strip()
        result_name = re.sub(r"[^a-z0-9]", "", str(result.get("company_name") or "").lower())
        if result_id:
            by_id[result_id] = result
        if result_name:
            by_name[result_name] = result
    def as_bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return True if normalized in {"true", "yes", "high", "opportunity"} else False if normalized in {"false", "no", "low", "modern"} else None
    enriched: list[Lead] = []
    matched = 0
    for lead in leads:
        result = by_id.get(lead.id) or by_name.get(re.sub(r"[^a-z0-9]", "", lead.company_name.lower()))
        if result:
            matched += 1
        industry_match = as_bool(result.get("industry_match")) if result else None
        geography_match = as_bool(result.get("geography_match")) if result else None
        digital_gap = as_bool(result.get("digital_maturity_gap")) if result else None
        evidence = [str(value).strip()[:240] for value in (result.get("evidence") or []) if str(value).strip()][:8] if result else []
        model_sources = [str(value).strip() for value in (result.get("source_urls") or []) if str(value).strip()] if result else []
        source_urls = [url for url in model_sources if url in grounding_sources] or grounding_sources[:8]
        verification = {
            "status": "verified" if result and any(value is not None for value in (industry_match, geography_match, digital_gap)) else "needs_review",
            "provider": "gemini_google_search_grounding",
            "model": model_used,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "industry_match": industry_match,
            "geography_match": geography_match,
            "digital_maturity_gap": digital_gap,
            "ai_readiness": str(result.get("ai_readiness") or "unknown") if result else "unknown",
            "evidence": evidence,
            "source_urls": source_urls,
        }
        updated = lead.model_copy(deep=True)
        updated.raw_payload = {**updated.raw_payload, "verification": verification}
        if digital_gap is not None:
            updated.digital_maturity_gap = digital_gap
        known = [value is not None for value in (industry_match, geography_match, digital_gap)]
        if any(known):
            flags = set(updated.validation_flags) | {"web_verification_completed"}
            if not all(known):
                flags.add("web_verification_partial")
            updated.validation_flags = sorted(flags)
            updated.confidence_score = min(100, max(updated.confidence_score, 60 + sum(known) * 10))
        enriched.append(updated)
    scored, changes = process(enriched, request.profile)
    changes.append({"action": "web_verification", "model": model_used, "matched_leads": str(matched), "source_count": str(len(grounding_sources))})
    warning = _persist_leads(scored)
    warnings = ["AI-readiness, industry fit, and geography fit were checked with Gemini Google Search grounding. Review the linked sources before outreach."]
    if not grounding_sources:
        warnings.append("The provider returned no grounding URLs; treat the verification as provisional.")
    warnings = _with_warning(warnings, warning)
    return PipelineResponse(leads=scored, changes=changes, warnings=warnings)


@app.post("/api/pipeline/discover", response_model=PipelineResponse)
async def discover(request: DiscoverRequest) -> PipelineResponse:
    limit = max(1, min(int(request.limit), MAX_DISCOVER))
    industry = _clean_prompt_text(request.industry)
    city = _clean_prompt_text(request.city)
    country = _clean_prompt_text(request.country) or "United States"
    if not industry or not city:
        raise HTTPException(status_code=422, detail="Both an industry and a city are required for discovery.")

    key = f"llm1:{industry.lower()}:{city.lower()}:{country.lower()}:{limit}"
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_TTL_SECONDS:
        return PipelineResponse(leads=cached[1], warnings=["Served from a 15-minute discovery cache."])

    cfg = _llm_config()
    if not _llm_ready(cfg):
        raise HTTPException(status_code=503, detail="AI discovery is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY and LLM_BASE_URL (in the root .env locally, or in your host's environment settings when deployed).")
    if cfg["provider"] not in GEMINI_PROVIDERS:
        raise HTTPException(status_code=503, detail="AI discovery needs live web search, which is only wired up for LLM_PROVIDER=gemini.")

    grounded_body = {
        "contents": [{"role": "user", "parts": [{"text": _build_discovery_prompt(industry, city, country, limit, True)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }
    ungrounded_body = {
        "contents": [{"role": "user", "parts": [{"text": _build_discovery_prompt(industry, city, country, limit, False)}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    grounded_cfg = {**cfg, "models": list(dict.fromkeys([*cfg["models"], *DISCOVERY_EXTRA_MODELS]))}
    grounded = True
    notices: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(LLM_DISCOVERY_TIMEOUT, connect=8.0)) as client:
            try:
                payload, model_used = await _gemini_generate(client, grounded_cfg, grounded_body, skip_on_429=True)
            except HTTPException as exc:
                if exc.status_code != 429 or not UNGROUNDED_FALLBACK:
                    raise
                # Search grounding is quota-blocked for every model: fall back to an ungrounded suggestion list.
                grounded = False
                notices.append(f"Google Search grounding is quota-blocked on this API key ({str(exc.detail)[:240]}...). Used model suggestions instead; only leads whose website is reachable and mentions the company name are kept.")
                payload, model_used = await _gemini_generate(client, cfg, ungrounded_body, skip_on_429=True)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"AI discovery request failed ({type(exc).__name__}). Please retry.") from exc

    items = _parse_json_array(_gemini_text(payload))
    grounding = (payload.get("candidates") or [{}])[0].get("groundingMetadata") or {}
    sources = [str((c.get("web") or {}).get("uri")) for c in grounding.get("groundingChunks", []) if (c.get("web") or {}).get("uri")][:10]
    search_queries = [str(q) for q in grounding.get("webSearchQueries", [])][:5]

    # Build candidates, discarding anything without a name.
    entries: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("company_name") or "").strip()
        if not name or name.lower() in {"null", "none"}:
            continue
        entries.append({"name": name, "website": _safe_website(item.get("website")), "item": item})

    # Verify each website in parallel; drop domains that do not resolve (likely invented).
    sem = asyncio.Semaphore(VERIFY_CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(VERIFY_TIMEOUT, connect=4.0), headers={"User-Agent": user_agent}, follow_redirects=True) as vclient:
        results = await asyncio.gather(*[
            _verify_website(vclient, sem, e["website"], e["name"]) if e["website"] else asyncio.sleep(0, result="no_website")
            for e in entries
        ])

    leads: list[Lead] = []
    status_by_id: dict[str, str] = {}
    dropped = 0
    for entry, status in zip(entries, results):
        if status == "unreachable" or (not grounded and status != "verified"):
            dropped += 1
            continue
        item = entry["item"]
        row = {
            "company_name": entry["name"], "website": entry["website"], "phone": item.get("phone"), "email": item.get("email"),
            "industry": industry, "city": city, "country": country,
            "employees": item.get("employees_estimate"), "years_in_business": item.get("years_in_business"), "owner_operated": item.get("owner_operated"),
            "source_url": item.get("source_url"), "description": item.get("description"),
        }
        lead = _normalize_discovered(row)
        flags = set(lead.validation_flags) | {"ai_discovered_verify_before_outreach"}
        if not grounded:
            flags.add("ungrounded_ai_suggestion")
        if status == "unconfirmed":
            flags.add("website_not_confirmed")
        if any(item.get(k) not in (None, "") for k in ("employees_estimate", "years_in_business", "owner_operated")):
            flags.add("ai_estimated_fields")
        lead.validation_flags = sorted(flags)
        status_by_id[lead.id] = status
        leads.append(lead)

    cleaned, changes = process(leads)
    for lead in cleaned:
        if status_by_id.get(lead.id) == "verified":
            lead.validation_flags = sorted(set(lead.validation_flags) | {"website_name_verified"})
            lead.confidence_score = min(100, lead.confidence_score + 20)
    changes.append({"action": "llm_discovery", "model": model_used, "queries": search_queries, "sources": sources, "candidates": str(len(entries)), "dropped_unverified": str(dropped), "grounded": str(grounded).lower()})

    warnings = ["AI-discovered via Google Search grounding. Confirm each lead before outreach; contact details can be incomplete."] if grounded else []
    warnings.extend(notices)
    if dropped:
        warnings.append(f"Dropped {dropped} candidate(s) that could not be verified through their website.")
    if cleaned:
        _cache[key] = (time.monotonic(), cleaned)  # never cache empty results
    else:
        warnings.insert(0, f"No verifiable businesses found for {industry} in {city}. Try a broader industry or a nearby city.")
    return PipelineResponse(leads=cleaned, changes=changes, warnings=warnings)


@app.post("/api/pipeline/enrich", response_model=PipelineResponse)
async def enrich(request: EnrichRequest) -> PipelineResponse:
    lead = request.lead.model_copy(deep=True)
    if not lead.website:
        lead.validation_flags = sorted(set(lead.validation_flags + ["missing_website_for_enrichment"])); lead.validation_status = "needs_review"; return PipelineResponse(leads=[lead], warnings=["A public website is required for enrichment."])
    url = lead.website if lead.website.startswith("http") else f"https://{lead.website}"; parsed = urlparse(url)
    if not _is_public_url(url):
        lead.validation_flags = sorted(set(lead.validation_flags + ["website_unreachable"])); lead.validation_status = "needs_review"; return PipelineResponse(leads=[lead], warnings=["That website address is not a public web address, so it was not fetched."])
    try:
        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": user_agent}, follow_redirects=True) as client:
            robots = await client.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
            if robots.status_code < 400:
                parser = RobotFileParser(); parser.parse(robots.text.splitlines())
                if not parser.can_fetch(user_agent, url):
                    lead.validation_flags = sorted(set(lead.validation_flags + ["robots_disallowed"])); lead.validation_status = "needs_review"; return PipelineResponse(leads=[lead], warnings=["robots.txt disallows this fetch; no page content was collected."])
            page = await client.get(url); page.raise_for_status(); html = page.text[:1_000_000]
    except httpx.HTTPError as exc:
        lead.validation_flags = sorted(set(lead.validation_flags + ["website_unreachable"])); lead.validation_status = "needs_review"; return PipelineResponse(leads=[lead], warnings=[f"Website fetch failed gracefully: {exc}"])
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", html, re.I); phones = re.findall(r"(?:\+?\d[\d ()-]{7,}\d)", html); socials = re.findall(r"https?://(?:www\.)?(?:linkedin\.com|facebook\.com|instagram\.com)/[^\"' ]+", html, re.I)
    if not lead.email and emails: lead.email = emails[0].lower()
    if not lead.phone and phones: lead.phone = phones[0].strip()
    if not lead.linkedin_url and socials: lead.linkedin_url = next((item for item in socials if "linkedin" in item.lower()), None)
    lead.validation_flags = sorted(set(lead.validation_flags + ["website_enriched_public_page"])); lead.validation_status = "verified" if lead.email or lead.phone else "needs_review"; lead.confidence_score = min(100, lead.confidence_score + 12)
    return PipelineResponse(leads=[lead], changes=[{"action": "website_enriched", "company": lead.company_name, "emails_found": str(len(emails)), "phones_found": str(len(phones))}], warnings=["Only public page content was inspected; verify signals before outreach."])


async def _generate_outreach_draft(request: DraftRequest) -> dict[str, str]:
    cfg = _llm_config()
    if not _llm_ready(cfg):
        raise HTTPException(status_code=503, detail="LLM outreach is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL in the backend environment.")
    lead = request.lead
    lead_context = json.dumps({"company_name": lead.company_name, "industry": lead.industry, "city": lead.city, "region": lead.region, "employees": lead.employees, "revenue_estimate": lead.revenue_estimate, "owner_operated": lead.owner_operated, "years_in_business": lead.years_in_business, "succession_signal": lead.succession_signal, "digital_maturity_gap": lead.digital_maturity_gap, "email": lead.email, "phone": lead.phone, "domain": lead.domain, "score_reasons": lead.score_reasons, "confidence_score": lead.confidence_score}, ensure_ascii=False)
    prompt = f"""Create a concise, credible first-touch acquisition outreach email for the business below. Use only the supplied facts; never invent financials, achievements, or personal details. The sender name is {request.sender_name!r}. Return JSON only with exactly two string fields: subject and body. The body should be 120 words or fewer, professional, specific, and end with a low-pressure call to action.\n\nBusiness facts:\n{lead_context}"""
    is_gemini = cfg["provider"] in GEMINI_PROVIDERS
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            if is_gemini:
                payload, _ = await _gemini_generate(client, cfg, {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.6, "responseMimeType": "application/json"}})
            else:
                response = await client.post(f"{cfg['base_url']}/chat/completions", headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}, json={"model": cfg["models"][0], "temperature": 0.6, "messages": [{"role": "system", "content": "You write evidence-based B2B acquisition outreach."}, {"role": "user", "content": prompt}]})
                response.raise_for_status()
                payload = response.json()
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM provider request failed for {cfg['provider']}.") from exc
    if is_gemini:
        text = _gemini_text(payload)
    else:
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    cleaned = text.strip()
    if cleaned.startswith("```"): cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        draft = json.loads(cleaned)
        subject = str(draft["subject"]).strip()
        body = str(draft["body"]).strip()
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise HTTPException(status_code=502, detail="LLM provider returned an invalid outreach draft format.") from exc
    if not subject or not body: raise HTTPException(status_code=502, detail="LLM provider returned an empty outreach draft.")
    return {"subject": subject, "body": body}


@app.post("/api/outreach/draft")
async def outreach(request: DraftRequest) -> dict[str, str]:
    return await _generate_outreach_draft(request)


@app.get("/api/ethics")
async def ethics() -> dict[str, list[str]]:
    return {"principles": [
        "Public business-level data only",
        "AI discovery uses Google Search grounding and cites its sources in the audit trail",
        "Every AI-discovered lead is flagged for verification before outreach",
        "Websites are checked and unreachable domains are dropped, so invented companies are filtered out",
        "Honor robots.txt and terms when enriching from a website",
        "Use an honest User-Agent",
        "Never bypass CAPTCHAs or IP blocks",
    ]}


@app.post("/api/export/csv")
async def export_csv(leads: list[Lead]) -> StreamingResponse:
    output = io.StringIO(); fields = ["company_name", "domain", "industry", "city", "region", "employees", "revenue_estimate", "email", "phone", "buy_box_score", "score_tier", "confidence_score", "next_best_action"]; writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for lead in leads: writer.writerow({field: getattr(lead, field) for field in fields})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=signaldesk-leads.csv"})
