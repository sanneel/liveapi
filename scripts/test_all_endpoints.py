#!/usr/bin/env python3
# Script to exercise all FastAPI endpoints and report basic health/security checks
import sys, time, json
import requests

BASE = "http://127.0.0.1:8000"

# Endpoints gathered from grep (method inferred by route decorator)
ENDPOINTS = [
    ("GET", "/api/admin/matches/search"),
    ("GET", "/api/admin/matches/{event_id}"),
    ("GET", "/api/admin/diagnostics"),
    ("GET", "/api/admin/stats"),
    ("GET", "/admin/campaigns"),
    ("GET", "/admin/campaigns/new"),
    ("POST", "/admin/campaigns"),
    ("GET", "/admin/campaigns/{slug}"),
    ("GET", "/admin/campaigns/{slug}/edit"),
    ("GET", "/admin/campaigns/{slug}/matches"),
    ("POST", "/admin/campaigns/{slug}"),
    ("POST", "/admin/campaigns/{slug}/delete"),
    ("POST", "/admin/campaigns/{slug}/toggle"),
    ("POST", "/admin/campaigns/{slug}/duplicate"),
    ("GET", "/api/admin/campaigns/{slug}/matches"),
    ("GET", "/api/admin/campaigns/{slug}/preview"),
    ("POST", "/api/admin/campaigns/{slug}/matches"),
    ("DELETE", "/api/admin/campaigns/{slug}/matches/{event_id}"),
    ("PUT", "/api/admin/campaigns/{slug}/matches"),
    ("GET", "/api/admin/campaigns/{slug}/picker"),
    ("GET", "/admin/clubs"),
    ("GET", "/admin/clubs/{slug}"),
    ("POST", "/admin/clubs"),
    ("POST", "/admin/clubs/{slug}"),
    ("GET", "/api/admin/clubs"),
    ("GET", "/api/admin/clubs/{slug}"),
    ("POST", "/api/admin/clubs"),
    ("PUT", "/api/admin/clubs/{slug}"),
    ("DELETE", "/api/admin/clubs/{slug}"),
    ("POST", "/admin/clubs/{slug}/delete"),
    ("GET", "/admin/hot"),
    ("GET", "/admin/hot/{sport}"),
    ("GET", "/api/admin/hot/{sport}/leaderboard"),
    ("PUT", "/api/admin/hot/{sport}/reorder"),
    ("POST", "/api/admin/hot/{sport}/pin/{event_id}"),
    ("POST", "/api/admin/hot/{sport}/suppress/{event_id}"),
    ("DELETE", "/api/admin/hot/{sport}/override/{event_id}"),
    ("GET", "/api/hot/override"),
    ("GET", "/api/hot/override/{event_id}"),
    ("POST", "/api/hot/override/{event_id}"),
    ("DELETE", "/api/hot/override/{event_id}"),
    ("GET", "/admin/logs"),
    ("GET", "/admin"),
]

# Simple helper to replace path params with placeholder values
def fill_path(path):
    return path.replace("{slug}", "testslug").replace("{event_id}", "1").replace("{sport}", "football")

results = []
for method, path in ENDPOINTS:
    url = BASE + fill_path(path)
    try:
        resp = requests.request(method, url, timeout=5)
        status = resp.status_code
        # basic security header checks (only when not in dev mode)
        csp = resp.headers.get("Content-Security-Policy")
        hsts = resp.headers.get("Strict-Transport-Security")
        # Log result
        results.append({"method": method, "url": url, "status": status, "csp": bool(csp), "hsts": bool(hsts)})
    except Exception as e:
        results.append({"method": method, "url": url, "error": str(e)})

# Output JSON report
print(json.dumps(results, indent=2))

# Exit with non-zero if any request failed (status >=500 or exception)
if any(r.get("status", 0) >= 500 or "error" in r for r in results):
    sys.exit(1)
