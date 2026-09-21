"""Small API walkthrough. Run the API first, then execute this file."""
import json
from urllib.request import Request, urlopen
BASE = "http://localhost:8000"
print(urlopen(f"{BASE}/api/health").read().decode())
request = Request(f"{BASE}/api/pipeline/demo", headers={"Accept":"application/json"})
response = json.loads(urlopen(request).read())
print(json.dumps({"top_lead": response["leads"][0]["company_name"], "score": response["leads"][0]["buy_box_score"]}, indent=2))