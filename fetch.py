"""Fetch bug bounty program data from HackerOne, Bugcrowd and Intigriti.

All endpoints are public. Data is cached on disk so repeated runs
do not hammer the platforms.
"""

import json
import os
import time

import requests

UA = "bounty-scout/0.1 (personal research tool; contact: abdulsalamabdulsalam204@gmail.com)"
POLITE_DELAY = 0.5
TIMEOUT = 15
H1_TTL = 7 * 86400
DAILY_TTL = 86400
DETAIL_TTL = 86400

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
DETAILS_DIR = os.path.join(CACHE_DIR, "details")

H1_ENDPOINT = "https://hackerone.com/graphql"
BC_ENDPOINT = "https://bugcrowd.com"
ALGOLIA_ENDPOINT = "https://aazuksyar4-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_HEADERS = {
    "x-algolia-api-key": "70d8a3400477311f27ce002ec953aeb0",
    "x-algolia-application-id": "AAZUKSYAR4",
}

H1_TEAMS_QUERY = """
query($cursor: String) {
  teams(first: 100, after: $cursor) {
    total_count
    pageInfo { hasNextPage endCursor }
    edges { node {
      handle
      name
      offers_bounties
      average_bounty_lower_amount
      average_bounty_upper_amount
      top_bounty_lower_amount
      top_bounty_upper_amount
      minimum_bounty
      resolved_report_count
      reports_received_last_90_days
      response_efficiency_percentage
      participants_count
      submission_state
      most_recent_sla_snapshot {
        average_time_to_first_program_response
        average_time_to_bounty_awarded
        average_time_to_report_resolved
      }
    } }
  }
}
"""

H1_SCOPES_QUERY = """
query($handle: String!) {
  team(handle: $handle) {
    structured_scopes(first: 100, archived: false) {
      edges { node {
        asset_identifier
        asset_type
        eligible_for_bounty
        eligible_for_submission
      } }
    }
  }
}
"""


class FetchError(Exception):
    """Raised when a platform request fails."""


def _http_get(url, **kwargs):
    """GET with the scout UA, polite delay and one retry."""
    time.sleep(POLITE_DELAY)
    headers = {"User-Agent": UA}
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as e:
        raise FetchError(f"GET {url} failed: {e}")
    if resp.status_code in (429, 500, 502, 503, 504):
        time.sleep(5)
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT, **kwargs)
        except requests.RequestException as e:
            raise FetchError(f"GET {url} retry failed: {e}")
    if resp.status_code != 200:
        raise FetchError(f"GET {url} returned {resp.status_code}")
    return resp


def _http_post(url, payload, headers=None):
    """POST with the scout UA, polite delay and one retry."""
    time.sleep(POLITE_DELAY)
    request_headers = {"User-Agent": UA, "Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    try:
        resp = requests.post(url, json=payload, headers=request_headers, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise FetchError(f"POST {url} failed: {e}")
    if resp.status_code in (429, 500, 502, 503, 504):
        time.sleep(5)
        try:
            resp = requests.post(url, json=payload, headers=request_headers, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise FetchError(f"POST {url} retry failed: {e}")
    if resp.status_code != 200:
        raise FetchError(f"POST {url} returned {resp.status_code}")
    return resp


def _cache_path(name):
    """Full path for a cache file."""
    return os.path.join(CACHE_DIR, name)


def _read_cache(name):
    """Return cached data or None."""
    path = _cache_path(name)
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_cache(name, data):
    """Write data to the cache."""
    os.makedirs(DETAILS_DIR, exist_ok=True)
    payload = {"fetched_at": time.time(), "data": data}
    path = _cache_path(name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def _is_fresh(name, ttl):
    """True when the cache file is newer than ttl seconds."""
    cached = _read_cache(name)
    if not cached:
        return False
    return time.time() - cached.get("fetched_at", 0) < ttl


def _fetch_cached(name, ttl, loader):
    """Return cached data or run loader and cache the result."""
    cached = _read_cache(name)
    if cached and time.time() - cached.get("fetched_at", 0) < ttl:
        return cached["data"], True
    data = loader()
    _write_cache(name, data)
    return data, False


def _h1_graphql(query, variables):
    """Run a GraphQL query against HackerOne."""
    resp = _http_post(H1_ENDPOINT, {"query": query, "variables": variables})
    body = resp.json()
    if "errors" in body:
        raise FetchError(f"HackerOne GraphQL errors: {body['errors']}")
    return body["data"]


def fetch_hackerone_teams(force=False):
    """Fetch the full HackerOne team directory, cached for a week."""
    if not force and _is_fresh("hackerone_teams.json", H1_TTL):
        cached = _read_cache("hackerone_teams.json")
        return cached["data"]

    teams = []
    cursor = None
    while True:
        data = _h1_graphql(H1_TEAMS_QUERY, {"cursor": cursor})
        page = data.get("teams", {})
        for edge in page.get("edges", []):
            teams.append(edge["node"])
        page_info = page.get("pageInfo", {})
        cursor = page_info.get("endCursor")
        if not page_info.get("hasNextPage") or not cursor:
            break
    _write_cache("hackerone_teams.json", {"teams": teams})
    return {"teams": teams}


def fetch_bugcrowd_engagements(force=False):
    """Fetch the Bugcrowd engagement directory, cached daily."""
    if not force and _is_fresh("bugcrowd_engagements.json", DAILY_TTL):
        cached = _read_cache("bugcrowd_engagements.json")
        return cached["data"]

    engagements = []
    page = 1
    while True:
        resp = _http_get(f"{BC_ENDPOINT}/engagements.json?page={page}")
        body = resp.json()
        batch = body.get("engagements", [])
        if not batch:
            break
        engagements.extend(batch)
        meta = body.get("paginationMeta", {})
        if len(batch) < meta.get("limit", 24):
            break
        page += 1
    _write_cache("bugcrowd_engagements.json", {"engagements": engagements})
    return {"engagements": engagements}


def fetch_bugcrowd_crowdstream(force=False):
    """Fetch recent accepted submissions from the public crowdstream feed."""
    if not force and _is_fresh("bugcrowd_crowdstream.json", DAILY_TTL):
        cached = _read_cache("bugcrowd_crowdstream.json")
        return cached["data"]

    items = []
    seen = set()
    for page in range(1, 5):
        resp = _http_get(f"{BC_ENDPOINT}/crowdstream.json?page={page}")
        body = resp.json()
        batch = body.get("results", [])
        if not batch:
            break
        for item in batch:
            item_id = item.get("id")
            if item_id and item_id not in seen:
                seen.add(item_id)
                items.append(item)
    _write_cache("bugcrowd_crowdstream.json", {"items": items})
    return {"items": items}


def fetch_intigriti_programs(force=False):
    """Fetch the Intigriti program directory from their Algolia index."""
    if not force and _is_fresh("intigriti_programs.json", DAILY_TTL):
        cached = _read_cache("intigriti_programs.json")
        return cached["data"]

    programs = []
    page = 0
    while True:
        payload = {"requests": [{"indexName": "programs_prod", "hitsPerPage": 24, "page": page, "query": ""}]}
        resp = _http_post(ALGOLIA_ENDPOINT, payload, headers=ALGOLIA_HEADERS)
        body = resp.json()
        hits = body["results"][0].get("hits", [])
        if not hits:
            break
        programs.extend(hits)
        if len(hits) < 24:
            break
        page += 1
    _write_cache("intigriti_programs.json", {"programs": programs})
    return {"programs": programs}


def fetch_hackerone_scopes(handle):
    """Fetch structured scopes for one HackerOne team, cached daily."""
    name = f"details/h1_{handle}.json"

    def loader():
        data = _h1_graphql(H1_SCOPES_QUERY, {"handle": handle})
        team = data.get("team") or {}
        scopes = [edge["node"] for edge in team.get("structured_scopes", {}).get("edges", [])]
        return {"scopes": scopes}

    data, _ = _fetch_cached(name, DETAIL_TTL, loader)
    return data


def fetch_bugcrowd_brief(engagement):
    """Fetch scope and reward ranges for one Bugcrowd engagement, cached daily."""
    code = engagement.get("code") or _bc_code(engagement)
    if not code:
        return {"in_scope": [], "reward_range": {}}
    name = f"details/bc_{code}.json"

    def loader():
        brief_url = engagement.get("briefUrl")
        if not brief_url:
            return {"in_scope": [], "reward_range": {}}
        html = _http_get(f"{BC_ENDPOINT}{brief_url}").text
        api_path = _bc_api_path(html)
        if not api_path:
            return {"in_scope": [], "reward_range": {}}
        resp = _http_get(f"{BC_ENDPOINT}{api_path}.json")
        body = resp.json()
        scope = body.get("data", {}).get("scope", [])
        in_scope = [s for s in scope if s.get("inScope")]
        return {"in_scope": in_scope, "reward_range": {}}

    data, _ = _fetch_cached(name, DETAIL_TTL, loader)
    return data


def _bc_code(engagement):
    """Extract the engagement code from its brief URL."""
    return engagement.get("briefUrl", "").rstrip("/").split("/")[-1]


def _bc_api_path(html):
    """Find the brief version document path inside the engagement page HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", {"data-react-class": "ResearcherEngagementBrief"})
    if not div:
        return None
    endpoints = div.get("data-api-endpoints")
    if not endpoints:
        return None
    try:
        api_map = json.loads(endpoints)
    except ValueError:
        return None
    path = api_map.get("engagementBriefApi", {}).get("getBriefVersionDocument")
    return path if path else None


def fetch_intigriti_detail(company_handle, handle):
    """Fetch full detail for one Intigriti program, cached daily."""
    name = f"details/intigriti_{handle}.json"

    def loader():
        url = f"https://app.intigriti.com/api/core/public/programs/{company_handle}/{handle}"
        resp = _http_get(url)
        return resp.json()

    data, _ = _fetch_cached(name, DETAIL_TTL, loader)
    return data


def refresh(platforms=None, force=False):
    """Refresh the directory cache for the given platforms."""
    if platforms is None:
        platforms = ["hackerone", "bugcrowd", "intigriti"]
    results = {}
    if "hackerone" in platforms:
        if force:
            data = fetch_hackerone_teams(force=True)
        else:
            data, _ = _fetch_cached("hackerone_teams.json", H1_TTL, lambda: fetch_hackerone_teams())
        results["hackerone"] = {"teams": len(data.get("teams", [])), "cache_hit": not force}
    if "bugcrowd" in platforms:
        if force:
            data = fetch_bugcrowd_engagements(force=True)
            crowd = fetch_bugcrowd_crowdstream(force=True)
        else:
            data, _ = _fetch_cached("bugcrowd_engagements.json", DAILY_TTL, lambda: fetch_bugcrowd_engagements())
            crowd, _ = _fetch_cached("bugcrowd_crowdstream.json", DAILY_TTL, lambda: fetch_bugcrowd_crowdstream())
        results["bugcrowd"] = {
            "engagements": len(data.get("engagements", [])),
            "crowdstream_items": len(crowd.get("items", [])),
            "cache_hit": not force,
        }
    if "intigriti" in platforms:
        if force:
            data = fetch_intigriti_programs(force=True)
        else:
            data, _ = _fetch_cached("intigriti_programs.json", DAILY_TTL, lambda: fetch_intigriti_programs())
        results["intigriti"] = {"programs": len(data.get("programs", [])), "cache_hit": not force}
    return results
