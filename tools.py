"""Tool handlers for bounty-scout.

Thin wrappers over fetch.py and rules.py. Every handler returns a
JSON string so the CLI can print or export results uniformly.
"""

import csv
import json
import os

import fetch
import rules


def refresh(platforms=None, force=False):
    """Refresh cached platform data."""
    try:
        results = fetch.refresh(platforms, force)
        return json.dumps({"status": "success", "data": results})
    except fetch.FetchError as e:
        return json.dumps({"status": "error", "error": str(e)})


def rank(platforms=None, limit=10, min_payout=0):
    """Rank programs by dupe risk and expected value."""
    try:
        result = rules.rank_programs(platforms, limit, min_payout)
        return json.dumps(result)
    except fetch.FetchError as e:
        return json.dumps({"status": "error", "error": str(e)})


def filter_by_bug_class(bug_class, platforms=None, limit=10):
    """Rank programs whose scope plausibly fits a bug class."""
    if bug_class not in rules.BUG_CLASS_KEYWORDS:
        return json.dumps({
            "status": "error",
            "error": f"unknown bug class '{bug_class}', pick from {sorted(rules.BUG_CLASS_KEYWORDS)}",
        })
    try:
        result = rules.filter_by_bug_class(bug_class, platforms, limit)
        return json.dumps(result)
    except fetch.FetchError as e:
        return json.dumps({"status": "error", "error": str(e)})


def program_details(platform, handle):
    """Full detail for one program."""
    try:
        raw = rules._raw_by_handle(platform, handle)
        if raw is None:
            return json.dumps({"status": "error", "error": f"unknown {platform} program '{handle}'"})
        rules._load_details(raw)
        scored = rules.score_program(raw)
        identifiers = rules._scope_identifiers(raw)
        return json.dumps({
            "status": "success",
            "name": raw["name"],
            "platform": raw["platform"],
            "handle": raw["handle"],
            "avg_payout": raw["avg_payout"],
            "participants": scored["participants"],
            "participants_proxy": raw["participants_proxy"],
            "score": scored["score"],
            "breakdown": scored["breakdown"],
            "scope_count": len(identifiers) if identifiers else 0,
            "scopes": identifiers[:50] if identifiers else [],
        })
    except fetch.FetchError as e:
        return json.dumps({"status": "error", "error": str(e)})


def export_csv(platforms=None, limit=20, filename="top_programs.csv"):
    """Export the ranked list to a CSV file."""
    try:
        result = json.loads(rank(platforms, limit, 0))
        if result.get("status") != "success":
            return json.dumps(result)
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["rank", "score", "platform", "handle", "name", "avg_payout", "participants", "why"])
            for i, p in enumerate(result["programs"], 1):
                writer.writerow([
                    i, p["score"], p["platform"], p["handle"], p["name"],
                    p["avg_payout"], p["participants"], p["breakdown"][0],
                ])
        return json.dumps({"status": "success", "file": path, "count": len(result["programs"])})
    except (fetch.FetchError, OSError) as e:
        return json.dumps({"status": "error", "error": str(e)})
