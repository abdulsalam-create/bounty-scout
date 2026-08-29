"""Ranking rules for bounty programs.

Every program becomes a uniform dict, then gets a score:

    score = payout x response_quality x activity_health x wildcard x 100 / sqrt(participants)

Each gate records a PASS/FAIL line in the breakdown so the ranking
never looks like a black box.
"""

import json
import math
import os
import re
import time

import fetch

TOP_N_DETAILS = 10
DEFAULT_PARTICIPANTS = 100

BUG_CLASS_KEYWORDS = {
    "idor": ["api", "user", "account", "portal", "admin", "id"],
    "auth": ["login", "auth", "sso", "session", "oauth", "password"],
    "business_logic": ["checkout", "payment", "cart", "order", "wallet", "billing", "transfer"],
    "response_manipulation": ["api", "json", "mobile", "app", "graphql", "price", "coupon", "subscription"],
}


def _clamp(value, low, high):
    """Keep a value inside a band."""
    return max(low, min(high, value))


def _parse_money(text):
    """Turn a string like '$4,000' into an int."""
    if not text:
        return None
    digits = re.sub(r"[^0-9.]", "", text)
    try:
        return float(digits)
    except ValueError:
        return None


def _cache(name):
    """Raw cached payload or empty dict."""
    return fetch._read_cache(name) or {}


def _h1_programs():
    """Normalize HackerOne teams into uniform program dicts."""
    programs = []
    for row in _cache("hackerone_teams.json").get("data", {}).get("teams", []):
        if not row.get("offers_bounties"):
            continue
        if row.get("submission_state") in ("disabled", "paused"):
            continue
        programs.append(_h1_normalize(row))
    return programs


def _h1_normalize(row):
    """One HackerOne team row -> uniform program dict."""
    low = row.get("average_bounty_lower_amount")
    high = row.get("average_bounty_upper_amount")
    payout = None
    if low is not None and high is not None:
        payout = (low + high) / 2
    elif low is not None:
        payout = low
    return {
        "platform": "hackerone",
        "handle": row.get("handle"),
        "name": row.get("name"),
        "avg_payout": payout,
        "participants": row.get("participants_count") or DEFAULT_PARTICIPANTS,
        "participants_proxy": not row.get("participants_count"),
        "sla": row.get("most_recent_sla_snapshot") or {},
        "response_efficiency": row.get("response_efficiency_percentage"),
        "reports_90d": row.get("reports_received_last_90_days"),
        "submission_state": row.get("submission_state"),
        "resolved_count": row.get("resolved_report_count"),
        "scopes": None,
    }


def _bc_programs():
    """Normalize Bugcrowd engagements into uniform program dicts."""
    crowd = _cache("bugcrowd_crowdstream.json").get("data", {}).get("items", [])
    now = time.time()
    by_code = {}
    for item in crowd:
        code = item.get("engagement_code")
        created = item.get("created_at", "")
        try:
            created_ts = time.mktime(time.strptime(created[:10], "%Y-%m-%d"))
        except ValueError:
            continue
        if now - created_ts > 30 * 86400:
            continue
        by_code.setdefault(code, {"researchers": set(), "count": 0})
        by_code[code]["researchers"].add(item.get("researcher_username"))
        by_code[code]["count"] += 1

    programs = []
    for row in _cache("bugcrowd_engagements.json").get("data", {}).get("engagements", []):
        if row.get("isBanned"):
            continue
        programs.append(_bc_normalize(row, by_code))
    return programs


def _bc_normalize(row, by_code):
    """One Bugcrowd engagement -> uniform program dict."""
    code = row.get("briefUrl", "").rstrip("/").split("/")[-1]
    reward = row.get("rewardSummary") or {}
    low = _parse_money(reward.get("minReward"))
    high = _parse_money(reward.get("maxReward"))
    payout = None
    if low is not None and high is not None:
        payout = (low + high) / 2
    elif low is not None:
        payout = low

    activity = by_code.get(code, {})
    distinct = len(activity.get("researchers", set()))
    if row.get("isPrivate"):
        participants = 50
        proxy = True
    else:
        participants = max(DEFAULT_PARTICIPANTS, distinct * 5)
        proxy = True

    return {
        "platform": "bugcrowd",
        "handle": code,
        "name": row.get("name"),
        "avg_payout": payout,
        "participants": participants,
        "participants_proxy": proxy,
        "is_private": row.get("isPrivate"),
        "ends_at": row.get("endsAt"),
        "crowd_count_30d": activity.get("count", 0),
        "crowd_researchers_30d": distinct,
        "access_status": row.get("accessStatus"),
        "scopes": None,
    }


def _intigriti_programs():
    """Normalize the Intigriti directory into uniform program dicts."""
    programs = []
    for row in _cache("intigriti_programs.json").get("data", {}).get("programs", []):
        if row.get("status") != 3:
            continue
        programs.append(_intigriti_normalize(row))
    return programs


def _intigriti_normalize(row):
    """One Intigriti directory hit -> uniform program dict."""
    low = (row.get("minBounty") or {}).get("value")
    high = (row.get("maxBounty") or {}).get("value")
    payout = None
    if low is not None and high is not None:
        payout = (low + high) / 2
    elif low is not None:
        payout = low
    return {
        "platform": "intigriti",
        "handle": row.get("handle"),
        "company_handle": row.get("companyHandle"),
        "name": row.get("name"),
        "avg_payout": payout,
        "participants": DEFAULT_PARTICIPANTS,
        "participants_proxy": True,
        "last_submission_at": row.get("lastSubmissionAt"),
        "confidentiality_level": row.get("confidentialityLevel"),
        "detail": None,
    }


def _payout_factor(payout, breakdown):
    """Score the payout band, 0.5 to 2.0."""
    if payout is None:
        breakdown.append("payout unknown, neutral 0.7")
        return 0.7
    factor = _clamp(0.4 + payout / 1250, 0.5, 2.0)
    breakdown.append(f"payout {payout:.0f} -> factor {factor:.2f}")
    return factor


def _h1_response(sla, breakdown):
    """First response and triage speed from the SLA snapshot."""
    fr = sla.get("average_time_to_first_program_response")
    triage = sla.get("average_time_to_bounty_awarded")

    def band(minutes):
        if minutes is None:
            return None
        if minutes < 1440:
            return 1.5, f"{minutes / 60:.0f}h < 24h"
        if minutes < 2880:
            return 1.2, f"{minutes / 60:.0f}h < 48h"
        if minutes < 4320:
            return 1.0, f"{minutes / 60:.0f}h < 3d"
        if minutes < 10080:
            return 0.8, f"{minutes / 1440:.0f}d < 7d"
        return 0.5, f"{minutes / 1440:.0f}d >= 7d"

    fr_score, fr_desc = band(fr) if fr is not None else (None, None)
    if fr_score is None:
        breakdown.append("first response unknown, neutral 0.9")
        fr_score = 0.9
    else:
        breakdown.append(f"first response {fr_desc} -> {fr_score}")

    triage_score = 0.9
    if triage is not None:
        if triage < 4320:
            triage_score = 1.5
        elif triage < 10080:
            triage_score = 1.2
        elif triage < 20160:
            triage_score = 1.0
        elif triage < 43200:
            triage_score = 0.8
        else:
            triage_score = 0.5
        breakdown.append(f"bounty time {triage / 1440:.0f}d -> {triage_score}")
    else:
        breakdown.append("bounty time unknown, neutral 0.9")
    return 0.6 * fr_score + 0.4 * triage_score


def _h1_health(program, breakdown):
    """Activity health from response efficiency and report volume."""
    eff = program["response_efficiency"]
    if program["submission_state"] == "paused":
        breakdown.append("program paused -> health 0.6")
        return 0.6
    if program["reports_90d"] == 0:
        breakdown.append("0 reports in last 90 days -> health 0.6")
        return 0.6
    if eff is None:
        breakdown.append("response efficiency unknown, neutral 1.0")
        return 1.0
    if eff >= 90:
        score = 1.3
    elif eff >= 75:
        score = 1.1
    elif eff >= 50:
        score = 1.0
    elif eff >= 25:
        score = 0.8
    else:
        score = 0.6
    breakdown.append(f"response efficiency {eff}% -> {score}")
    return score


def _bc_response(breakdown):
    """Bugcrowd has no public triage stat, stay neutral."""
    breakdown.append("triage approximated: Bugcrowd publishes no response times")
    return 0.9


def _bc_health(program, breakdown):
    """Activity health from the crowdstream feed."""
    ends_at = program["ends_at"]
    if ends_at:
        try:
            ended = time.mktime(time.strptime(ends_at[:19], "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            ended = 0
        if ended and time.time() > ended:
            breakdown.append("engagement ended -> health 0.5")
            return 0.5
    count = program["crowd_count_30d"]
    if count >= 10:
        breakdown.append(f"{count} crowdstream items in 30d -> 1.2")
        return 1.2
    if count >= 3:
        breakdown.append(f"{count} crowdstream items in 30d -> 1.0")
        return 1.0
    if count >= 1:
        breakdown.append(f"{count} crowdstream item in 30d -> 0.8")
        return 0.8
    breakdown.append("no crowdstream activity in 30d -> 0.6")
    return 0.6


def _intigriti_response(program, breakdown):
    """Triage cadence from skipTriage and activity gaps."""
    detail = program["detail"]
    if not detail:
        breakdown.append("triage unknown, scope not fetched -> 0.9")
        return 0.9
    if detail.get("skipTriage"):
        breakdown.append("program skips triage -> 1.3")
        return 1.3
    activity = detail.get("lastActivity") or []
    stamps = sorted(a.get("timestamp") for a in activity if a.get("timestamp"))
    if len(stamps) < 2:
        breakdown.append("little activity data, neutral 0.9")
        return 0.9
    gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
    gaps.sort()
    median = gaps[len(gaps) // 2] / 3600
    if median < 48:
        score = 1.4
    elif median < 168:
        score = 1.0
    else:
        score = 0.7
    breakdown.append(f"median activity gap {median:.0f}h -> {score}")
    return score


def _intigriti_health(program, breakdown):
    """Activity health from acceptance ratio and submission recency."""
    detail = program["detail"]
    accepted = (detail or {}).get("acceptedSubmissionCount")
    submitted = (detail or {}).get("submissionCount")
    last_sub = program["last_submission_at"]

    if accepted is not None and submitted:
        ratio = accepted / submitted
        if ratio >= 0.5:
            score = 1.2
        elif ratio >= 0.25:
            score = 1.0
        elif ratio >= 0.1:
            score = 0.8
        else:
            score = 0.6
        breakdown.append(f"accepted/submitted {accepted}/{submitted} -> {score}")
    else:
        breakdown.append("acceptance ratio unknown, neutral 1.0")
        score = 1.0

    if last_sub and time.time() - last_sub > 90 * 86400:
        breakdown.append("no submission in 90 days -> health 0.6")
        score = 0.6
    return score


def _wildcard_factor(program, breakdown):
    """Boost programs whose scope includes wildcard domains."""
    identifiers = _scope_identifiers(program)
    if identifiers is None:
        breakdown.append("scope not fetched, wildcard unchecked")
        return 1.0
    wildcards = [i for i in identifiers if i.startswith("*.") or "*" in i]
    if wildcards:
        breakdown.append(f"wildcard scope {wildcards[0]} -> 1.2")
        return 1.2
    breakdown.append("no wildcard scope -> 1.0")
    return 1.0


def _scope_identifiers(program):
    """List of scope identifiers for a program, or None when unknown."""
    if program["platform"] == "hackerone":
        scopes = program.get("scopes")
        if scopes is None:
            return None
        return [s.get("asset_identifier") for s in scopes if s.get("asset_identifier")]
    if program["platform"] == "bugcrowd":
        scopes = program.get("scopes")
        if scopes is None:
            return None
        uris = []
        for item in scopes:
            for target in item.get("targets", []) or []:
                if target.get("uri"):
                    uris.append(target["uri"])
            if item.get("uri"):
                uris.append(item["uri"])
        return uris
    if program["platform"] == "intigriti":
        detail = program.get("detail")
        if not detail:
            return None
        names = []
        for collection in detail.get("assetsCollection", []) or []:
            for group in (collection.get("content", {}) or {}).get("assetsAndGroups", []) or []:
                names.append(group.get("name"))
                for asset in group.get("assets", []) or []:
                    if asset.get("name"):
                        names.append(asset["name"])
        return [n for n in names if n]
    return None


def score_program(program):
    """Score one program and attach the why breakdown."""
    breakdown = []
    payout = _payout_factor(program["avg_payout"], breakdown)

    if program["platform"] == "hackerone":
        response = _h1_response(program["sla"], breakdown)
        health = _h1_health(program, breakdown)
    elif program["platform"] == "bugcrowd":
        response = _bc_response(breakdown)
        health = _bc_health(program, breakdown)
    else:
        response = _intigriti_response(program, breakdown)
        health = _intigriti_health(program, breakdown)

    wildcard = _wildcard_factor(program, breakdown)
    participants = program["participants"]
    if participants < 150:
        breakdown.append(f"participants {participants} < 150, low dupe risk")
    else:
        breakdown.append(f"participants {participants} >= 150, dupe risk")

    score = payout * response * health * wildcard * 100 / math.sqrt(participants)
    return {
        "score": round(score, 1),
        "payout": payout,
        "response": response,
        "health": health,
        "wildcard": wildcard,
        "participants": participants,
        "breakdown": breakdown,
    }


def _load_details(program):
    """Fetch and attach lazy detail data for one program."""
    try:
        if program["platform"] == "hackerone":
            data = fetch.fetch_hackerone_scopes(program["handle"])
            program["scopes"] = data.get("scopes", [])
        elif program["platform"] == "bugcrowd":
            data = fetch.fetch_bugcrowd_brief({"briefUrl": f"/engagements/{program['handle']}"})
            program["scopes"] = data.get("in_scope", [])
        else:
            program["detail"] = fetch.fetch_intigriti_detail(program["company_handle"], program["handle"])
            contributors = program["detail"].get("lastContributors") or []
            submitted = program["detail"].get("submissionCount") or 0
            program["participants"] = max(50, len(contributors) * 10, submitted)
            program["participants_proxy"] = True
        return True
    except fetch.FetchError:
        return False


def _detail_cached(program):
    """True when the lazy detail for a program is already in the cache."""
    if program["platform"] == "hackerone":
        name = f"details/h1_{program['handle']}.json"
    elif program["platform"] == "bugcrowd":
        name = f"details/bc_{program['handle']}.json"
    else:
        name = f"details/intigriti_{program['handle']}.json"
    return fetch._is_fresh(name, fetch.DETAIL_TTL)


def _rank_raw(platforms, limit, min_payout):
    """Score and rank raw programs, attaching details to the top candidates."""
    all_programs = []
    for platform in platforms:
        if platform == "hackerone":
            all_programs.extend(_h1_programs())
        elif platform == "bugcrowd":
            all_programs.extend(_bc_programs())
        else:
            all_programs.extend(_intigriti_programs())

    filtered = [p for p in all_programs if min_payout == 0 or (p["avg_payout"] or 0) >= min_payout]

    # Phase 1: score with what the directories give us.
    for program in filtered:
        program["_scored"] = score_program(program)

    # Phase 2: fetch details for the top candidates and rescore.
    fetched = 0
    for platform in platforms:
        candidates = [p for p in filtered if p["platform"] == platform]
        candidates.sort(key=lambda p: p["_scored"]["score"], reverse=True)
        for program in candidates[:TOP_N_DETAILS]:
            if program["platform"] == "intigriti" and program.get("detail"):
                continue
            if program.get("scopes") is not None:
                continue
            cached_before = _detail_cached(program)
            if _load_details(program):
                if not cached_before:
                    fetched += 1
                program["_scored"] = score_program(program)

    ranked = sorted(filtered, key=lambda p: p["_scored"]["score"], reverse=True)[:limit]
    return ranked, fetched


def rank_programs(platforms=None, limit=10, min_payout=0):
    """Rank programs across platforms, fetching details for the top candidates."""
    if platforms is None:
        platforms = ["hackerone", "bugcrowd", "intigriti"]
    ranked, fetched = _rank_raw(platforms, limit, min_payout)
    return _result(ranked, fetched)


def filter_by_bug_class(bug_class, platforms=None, limit=10):
    """Rank programs whose scope plausibly fits a bug class."""
    keywords = BUG_CLASS_KEYWORDS.get(bug_class, [])
    if platforms is None:
        platforms = ["hackerone", "bugcrowd", "intigriti"]
    ranked, fetched = _rank_raw(platforms, limit * 5, 0)
    matches = []
    for program in ranked:
        identifiers = _scope_identifiers(program)
        if identifiers is None:
            program["_scored"]["breakdown"].insert(0, f"scope unknown, kept (no '{bug_class}' scan)")
            matches.append(program)
            continue
        haystack = " ".join(identifiers).lower()
        if any(k in haystack for k in keywords):
            program["_scored"]["breakdown"].insert(0, f"scope matches '{bug_class}' keywords")
            matches.append(program)
        if len(matches) >= limit:
            break
    return _result(matches, fetched)


def _raw_by_handle(platform, handle):
    """Find the raw program dict by platform and handle."""
    for program in _all_raw(platform):
        if program["handle"] == handle:
            return program
    return None


def _all_raw(platform):
    """All raw normalized programs for a platform."""
    if platform == "hackerone":
        return _h1_programs()
    if platform == "bugcrowd":
        return _bc_programs()
    return _intigriti_programs()


def _result(programs, fetched):
    """Shape the final result for tools.py and main.py."""
    rows = []
    for program in programs:
        if "_scored" in program:
            scored = program["_scored"]
            rows.append({
                "platform": program["platform"],
                "handle": program["handle"],
                "name": program["name"],
                "avg_payout": program["avg_payout"],
                "participants": scored["participants"],
                "participants_proxy": program["participants_proxy"],
                "score": scored["score"],
                "breakdown": scored["breakdown"],
            })
        else:
            rows.append(program)
    return {
        "status": "success",
        "count": len(rows),
        "fetched_details": fetched,
        "programs": rows,
    }


def format_table(result):
    """Render a ranked list as a readable table."""
    lines = []
    for i, p in enumerate(result["programs"], 1):
        proxy = "~" if p["participants_proxy"] else ""
        payout = f"${p['avg_payout']:.0f}" if p["avg_payout"] else "?"
        lines.append(f"{i:>2}. {p['score']:>5}  {p['name'][:40]:<40} {p['platform']:<10} "
                     f"{payout:>7}  {proxy}{p['participants']:<6}  {p['breakdown'][0]}")
    return "\n".join(lines)
