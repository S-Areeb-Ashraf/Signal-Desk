from __future__ import annotations
import csv, io, re, time, uuid
from copy import deepcopy
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from api.app.models import DiscoverRequest, DraftRequest, EnrichRequest, ImportRequest, Lead, Model, ScoreRequest, ScoringProfile
app=FastAPI(title="SignalDesk API",version="0.1.0",docs_url="/api/docs",redoc_url="/api/redoc")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
_cache: dict[str,tuple[float,list[Lead]]]={}
DEMO_ROWS=[
 {"company_name":"Northstar Precision Tools","domain":"northstarprecision.com","industry":"Industrial Manufacturing","city":"Cleveland","region":"Ohio","employees":72,"revenue_estimate":12500000,"owner_operated":True,"years_in_business":28,"succession_signal":True,"digital_maturity_gap":True,"email":"hello@northstarprecision.com","phone":"+1 216 555 0101"},
 {"company_name":"Harborline HVAC","domain":"harborlinehvac.com","industry":"HVAC Services","city":"Tampa","region":"Florida","employees":38,"revenue_estimate":6200000,"owner_operated":True,"years_in_business":19,"succession_signal":False,"digital_maturity_gap":True,"email":"info@harborlinehvac.com","phone":"+1 813 555 0102"},
 {"company_name":"Cedar & Finch Dental","domain":"cedarfinchdental.com","industry":"Dental Practice","city":"Austin","region":"Texas","employees":24,"revenue_estimate":3400000,"owner_operated":True,"years_in_business":12,"succession_signal":True,"digital_maturity_gap":False,"email":"team@cedarfinchdental.com","phone":"+1 512 555 0103"},
 {"company_name":"Atlas Safety Supply","domain":"atlassafetysupply.com","industry":"Industrial Distribution","city":"Phoenix","region":"Arizona","employees":115,"revenue_estimate":28000000,"owner_operated":False,"years_in_business":22,"succession_signal":False,"digital_maturity_gap":True,"email":"sales@atlassafetysupply.com","phone":"+1 602 555 0104"},
 {"company_name":"Blue Oak Landscape","domain":"blueoaklandscape.com","industry":"Landscaping","city":"Denver","region":"Colorado","employees":16,"revenue_estimate":1800000,"owner_operated":True,"years_in_business":8,"succession_signal":False,"digital_maturity_gap":True,"phone":"+1 303 555 0105"},
 {"company_name":"Meridian Compliance Group","domain":"meridiancompliance.com","industry":"Professional Services","city":"Raleigh","region":"North Carolina","employees":54,"revenue_estimate":9100000,"owner_operated":True,"years_in_business":16,"succession_signal":True,"digital_maturity_gap":True,"email":"contact@meridiancompliance.com"},]
def _int(value:Any)->int|None:
    if value in (None,""): return None
    digits=re.sub(r"[^0-9]","",str(value)); return int(digits) if digits else None
def _bool(value:Any)->bool|None:
    if value in (None,""): return None
    if isinstance(value,bool): return value
    return str(value).lower().strip() in {"true","yes","1","y"}
def normalize_row(row:dict[str,Any],source:str="csv_import")->Lead:
    raw={str(k).strip().lower().replace(" ","_"):v for k,v in row.items()}; name=str(raw.get("company_name") or raw.get("company") or raw.get("name") or "Unnamed company").strip(); domain=str(raw.get("domain") or "").strip().lower() or None; website=str(raw.get("website") or "").strip() or None
    if website and not domain: domain=urlparse(website if "://" in website else f"https://{website}").netloc.lower().removeprefix("www.") or None
    email,phone=str(raw.get("email") or "").strip().lower() or None,str(raw.get("phone") or "").strip() or None; flags=[]
    if not email: flags.append("missing_email")
    if not phone: flags.append("missing_phone")
    if not domain: flags.append("missing_domain")
    return Lead(id=str(uuid.uuid4()),company_name=name,domain=domain,website=website,industry=str(raw.get("industry") or "").strip() or None,city=str(raw.get("city") or "").strip() or None,region=str(raw.get("region") or raw.get("state") or "").strip() or None,country=str(raw.get("country") or "United States").strip(),employees=_int(raw.get("employees") or raw.get("employee_count")),revenue_estimate=_int(raw.get("revenue_estimate") or raw.get("revenue")),owner_operated=_bool(raw.get("owner_operated")),years_in_business=_int(raw.get("years_in_business") or raw.get("years")),succession_signal=_bool(raw.get("succession_signal")),digital_maturity_gap=_bool(raw.get("digital_maturity_gap")),email=email,phone=phone,linkedin_url=str(raw.get("linkedin_url") or "").strip() or None,source=source,validation_status="verified" if not flags else "needs_review",validation_flags=flags,confidence_score=max(0,100-len(flags)*18),raw_payload=row)
def dedupe_leads(leads:list[Lead])->tuple[list[Lead],list[dict[str,Any]]]:
    kept={}; changes=[]
    for lead in leads:
        key=lead.domain or re.sub(r"[^a-z0-9]","",lead.company_name.lower())
        if key not in kept: kept[key]=lead; continue
        existing,merged=kept[key],kept[key].model_copy(deep=True)
        for field in ("website","industry","city","region","employees","revenue_estimate","email","phone","linkedin_url"):
            if getattr(merged,field) in (None,"") and getattr(lead,field) not in (None,""): setattr(merged,field,getattr(lead,field))
        merged.validation_flags=sorted(set(existing.validation_flags+lead.validation_flags)); merged.confidence_score=max(existing.confidence_score,lead.confidence_score); kept[key]=merged; changes.append({"action":"merged_duplicate","kept":existing.company_name,"merged":lead.company_name,"key":key})
    return list(kept.values()),changes
def validate_leads(leads:list[Lead])->list[Lead]:
    pattern=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$"); result=[]
    for lead in leads:
        item,flags=lead.model_copy(deep=True),set(lead.validation_flags)
        if item.email and not pattern.match(item.email): flags.add("invalid_email_syntax")
        item.validation_flags,item.validation_status,item.confidence_score=sorted(flags),"verified" if not flags else "needs_review",max(0,100-len(flags)*18); result.append(item)
    return result
def score_lead(lead:Lead,profile:ScoringProfile)->Lead:
    weights,reasons,earned=profile.weights,[],0; possible=sum(max(0,v) for v in weights.values()) or 1
    def add(key:str,passed:bool,label:str)->None:
        nonlocal earned
        points=max(0,weights.get(key,0)); earned+=points if passed else 0; reasons.append(f"{'+' if passed else '-'}{points} {label}")
    location=" ".join(filter(None,[lead.city,lead.region,lead.country])); industry_ok=profile.industry.lower() in {"all industries",""} or bool(lead.industry and profile.industry.lower() in lead.industry.lower()); geo_ok=profile.geography.lower() in {"all locations",""} or profile.geography.lower() in location.lower()
    add("industry",industry_ok,"industry match"); add("geography",geo_ok,"geography match"); add("size",lead.employees is not None and profile.employee_min<=lead.employees<=profile.employee_max,"employee band"); add("revenue",lead.revenue_estimate is not None and profile.revenue_min<=lead.revenue_estimate<=profile.revenue_max,"revenue band"); add("ownership",lead.owner_operated is True,"owner-operated signal"); add("tenure",lead.years_in_business is not None and lead.years_in_business>=10,"tenure signal"); add("succession",lead.succession_signal is True,"succession signal"); add("contact",bool(lead.email or lead.phone),"contact data"); add("digital_gap",lead.digital_maturity_gap is True,"AI-readiness opportunity")
    total=round(earned/possible*100); tier="A" if total>=80 else "B" if total>=65 else "C" if total>=45 else "D"; item=lead.model_copy(deep=True); item.buy_box_score,item.score_tier,item.score_reasons,item.next_best_action=total,tier,reasons,{"A":"Contact first","B":"Verify contact data","C":"Research fit","D":"Deprioritize"}[tier]; return item
def process(leads:list[Lead],profile:ScoringProfile|None=None)->tuple[list[Lead],list[dict[str,Any]]]:
    unique,changes=dedupe_leads(validate_leads(leads)); scored=sorted((score_lead(lead,profile or ScoringProfile()) for lead in unique),key=lambda item:item.buy_box_score,reverse=True); return scored,changes
def demo(profile:ScoringProfile|None=None)->tuple[list[Lead],list[dict[str,Any]]]: return process([normalize_row(row,"synthetic_demo") for row in deepcopy(DEMO_ROWS)],profile)
class PipelineResponse(Model):
    leads:list[Lead]
    changes:list[dict[str,Any]]=[]
    warnings:list[str]=[]
@app.get("/")
async def root()->dict[str,str]: return {"service":"SignalDesk API","status":"ok","docs":"/api/docs","health":"/api/health"}
@app.get("/api/health")
async def health()->dict[str,str]: return {"status":"ok","service":"signaldesk-api"}
@app.get("/api/pipeline/demo",response_model=PipelineResponse)
async def get_demo()->PipelineResponse:
    leads,changes=demo(); return PipelineResponse(leads=leads,changes=changes)
@app.post("/api/scoring/preview",response_model=PipelineResponse)
async def score(request:ScoreRequest)->PipelineResponse:
    leads,changes=process(request.leads,request.profile); return PipelineResponse(leads=leads,changes=changes)
@app.post("/api/pipeline/import",response_model=PipelineResponse)
async def import_csv(request:ImportRequest)->PipelineResponse:
    reader=csv.DictReader(io.StringIO(request.csv_text))
    if not reader.fieldnames: raise HTTPException(status_code=422,detail="CSV must include a header row")
    leads,changes=process([normalize_row(dict(row),request.source) for row in reader]); return PipelineResponse(leads=leads,changes=changes)
@app.post("/api/pipeline/discover",response_model=PipelineResponse)
async def discover(request:DiscoverRequest)->PipelineResponse:
    key=f"v2:{request.industry}:{request.city}:{request.country}:{request.limit}"; cached=_cache.get(key)
    if cached and time.monotonic()-cached[0]<900: return PipelineResponse(leads=cached[1],warnings=["Served from a 15-minute public-source cache."])
    city_name=request.city.replace('"','')
    terms=[term for term in re.findall(r"[A-Za-z0-9]+",request.industry) if len(term)>2 and term.lower() not in {"services","service","business","company"}]
    pattern="|".join(re.escape(term) for term in terms) or re.escape(request.industry)
    query=f'[out:json][timeout:12];area["name"="{city_name}"]["boundary"="administrative"]->.searchArea;nwr["name"~"{pattern}",i](area.searchArea);out center {request.limit};'
    try:
        async with httpx.AsyncClient(timeout=15,headers={"User-Agent":"SignalDesk/0.1 public-business-data"}) as client: response=await client.post("https://overpass-api.de/api/interpreter",data={"data":query}); response.raise_for_status()
    except httpx.HTTPError as exc: raise HTTPException(status_code=502,detail=f"Discovery source unavailable: {exc}") from exc
    try:
        payload=response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502,detail="Discovery source returned an unreadable response") from exc
    elements=payload.get("elements",[])
    leads=[normalize_row({"company_name":item.get("tags",{}).get("name","Unnamed OSM place"),"industry":request.industry,"city":request.city,"country":request.country,"website":item.get("tags",{}).get("website"),"phone":item.get("tags",{}).get("phone")},"openstreetmap") for item in elements[:request.limit]]
    cleaned,changes=process(leads)
    warnings=["OpenStreetMap results may be partial; attribution and ODbL terms apply."]
    if not cleaned: warnings.insert(0,f"No public records matched {request.industry} in {request.city}. Try a broader industry or nearby city.")
    _cache[key]=(time.monotonic(),cleaned)
    return PipelineResponse(leads=cleaned,changes=changes,warnings=warnings)
@app.post("/api/pipeline/enrich",response_model=PipelineResponse)
async def enrich(request:EnrichRequest)->PipelineResponse:
    lead=request.lead.model_copy(deep=True)
    if not lead.website:
        lead.validation_flags=sorted(set(lead.validation_flags+["missing_website_for_enrichment"])); lead.validation_status="needs_review"; return PipelineResponse(leads=[lead],warnings=["A public website is required for enrichment."])
    url=lead.website if lead.website.startswith("http") else f"https://{lead.website}"; parsed=urlparse(url); user_agent="SignalDesk/0.1 public-business-data"
    try:
        async with httpx.AsyncClient(timeout=15,headers={"User-Agent":user_agent},follow_redirects=True) as client:
            robots=await client.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
            if robots.status_code < 400:
                parser=RobotFileParser(); parser.parse(robots.text.splitlines())
                if not parser.can_fetch(user_agent,url):
                    lead.validation_flags=sorted(set(lead.validation_flags+["robots_disallowed"])); lead.validation_status="needs_review"; return PipelineResponse(leads=[lead],warnings=["robots.txt disallows this fetch; no page content was collected."])
            page=await client.get(url); page.raise_for_status(); html=page.text[:1_000_000]
    except httpx.HTTPError as exc:
        lead.validation_flags=sorted(set(lead.validation_flags+["website_unreachable"])); lead.validation_status="needs_review"; return PipelineResponse(leads=[lead],warnings=[f"Website fetch failed gracefully: {exc}"])
    emails=re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",html,re.I); phones=re.findall(r"(?:\+?\d[\d ()-]{7,}\d)",html); socials=re.findall(r"https?://(?:www\.)?(?:linkedin\.com|facebook\.com|instagram\.com)/[^\"' ]+",html,re.I)
    if not lead.email and emails: lead.email=emails[0].lower()
    if not lead.phone and phones: lead.phone=phones[0].strip()
    if not lead.linkedin_url and socials: lead.linkedin_url=next((item for item in socials if "linkedin" in item.lower()),None)
    lead.validation_flags=sorted(set(lead.validation_flags+["website_enriched_public_page"])); lead.validation_status="verified" if lead.email or lead.phone else "needs_review"; lead.confidence_score=min(100,lead.confidence_score+12)
    return PipelineResponse(leads=[lead],changes=[{"action":"website_enriched","company":lead.company_name,"emails_found":str(len(emails)),"phones_found":str(len(phones))}],warnings=["Only public page content was inspected; verify signals before outreach."])
@app.post("/api/outreach/draft")
async def outreach(request:DraftRequest)->dict[str,str]:
    lead=request.lead; signal="your owner-led operating model" if lead.owner_operated else "your company’s operating footprint"; return {"subject":f"A practical growth idea for {lead.company_name}","body":f"Hi there,\n\nI’m reaching out because {lead.company_name} stood out for {signal}. We work with operators exploring practical growth and AI-readiness opportunities. Would a short conversation next week be useful?\n\nBest,\n{request.sender_name}"}
@app.get("/api/ethics")
async def ethics()->dict[str,list[str]]: return {"principles":["Public business-level data only","Honor robots.txt and terms","Use an honest User-Agent","Rate-limit politely","Never bypass CAPTCHAs or IP blocks","Attribute OpenStreetMap under ODbL"]}
@app.post("/api/export/csv")
async def export_csv(leads:list[Lead])->StreamingResponse:
    output=io.StringIO(); fields=["company_name","domain","industry","city","region","employees","revenue_estimate","email","phone","buy_box_score","score_tier","confidence_score","next_best_action"]; writer=csv.DictWriter(output,fieldnames=fields); writer.writeheader()
    for lead in leads: writer.writerow({field:getattr(lead,field) for field in fields})
    return StreamingResponse(iter([output.getvalue()]),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=signaldesk-leads.csv"})