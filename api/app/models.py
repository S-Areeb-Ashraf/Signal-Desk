from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field
class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")
class Lead(Model):
    id: str
    company_name: str
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    employees: int | None = None
    revenue_estimate: int | None = None
    owner_operated: bool | None = None
    years_in_business: int | None = None
    succession_signal: bool | None = None
    digital_maturity_gap: bool | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    source: str = "synthetic_demo"
    validation_status: Literal["verified", "partial", "needs_review"] = "partial"
    validation_flags: list[str] = Field(default_factory=list)
    confidence_score: int = Field(default=50, ge=0, le=100)
    buy_box_score: int = Field(default=0, ge=0, le=100)
    score_tier: Literal["A", "B", "C", "D"] = "D"
    score_reasons: list[str] = Field(default_factory=list)
    next_best_action: str = "Review fit"
    raw_payload: dict[str, Any] = Field(default_factory=dict)
class ScoringProfile(Model):
    industry: str = "All industries"
    geography: str = "All locations"
    employee_min: int = 10
    employee_max: int = 250
    revenue_min: int = 1_000_000
    revenue_max: int = 50_000_000
    weights: dict[str, int] = Field(default_factory=lambda: {"industry":20,"geography":12,"size":14,"revenue":14,"ownership":12,"tenure":8,"succession":8,"contact":6,"digital_gap":6})
class ScoreRequest(Model):
    leads: list[Lead] = Field(min_length=1, max_length=10000)
    profile: ScoringProfile
class ImportRequest(Model):
    csv_text: str = Field(min_length=1, max_length=5_000_000)
    source: str = "csv_import"
class DiscoverRequest(Model):
    industry: str = Field(min_length=2, max_length=120)
    city: str = Field(min_length=2, max_length=120)
    country: str = "United States"
    limit: int = Field(default=20, ge=1, le=100)
class EnrichRequest(Model):
    lead: Lead
class DraftRequest(Model):
    lead: Lead
    sender_name: str = "[Your name]"