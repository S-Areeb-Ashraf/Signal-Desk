from api.app.main import dedupe_leads, normalize_row, score_lead, validate_leads
from api.app.models import ScoringProfile
def test_score_is_explainable()->None:
    lead=normalize_row({"company_name":"Fit Co","industry":"HVAC","city":"Tampa","employees":40,"revenue":5000000,"owner_operated":"yes","years_in_business":20,"succession_signal":"yes","digital_maturity_gap":"yes","email":"owner@fit.co"},"test"); scored=score_lead(lead,ScoringProfile(industry="HVAC",geography="Tampa")); assert scored.buy_box_score>70; assert scored.score_tier in {"A","B"}; assert any("industry match" in reason for reason in scored.score_reasons)
def test_duplicate_is_merged_and_reported()->None:
    first=normalize_row({"company_name":"Acme","domain":"acme.com","email":"hello@acme.com"},"test"); second=normalize_row({"company_name":"Acme LLC","domain":"acme.com","phone":"+1 555 0101"},"test"); leads,changes=dedupe_leads([first,second]); assert len(leads)==1; assert leads[0].phone=="+1 555 0101"; assert changes[0]["action"]=="merged_duplicate"
def test_invalid_email_is_flagged()->None:
    lead=normalize_row({"company_name":"Bad Email","email":"not-an-email"},"test"); assert "invalid_email_syntax" in validate_leads([lead])[0].validation_flags