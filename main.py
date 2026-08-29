"""Bounty Scout - bug bounty program picker for HackerOne, Bugcrowd and Intigriti.

All data comes from public endpoints and is cached locally, so
nothing here needs an API key or a login.
"""

import json

import rules
import tools


def _ask_platforms():
    """Ask which platforms to include, default is all."""
    value = input("  Platforms (hackerone, bugcrowd, intigriti, all = enter): ").strip()
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _ask_int(prompt, default):
    """Ask for a number with a default."""
    value = input(f"  {prompt} (default {default}): ").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def mode_rank():
    """Rank programs across the selected platforms."""
    platforms = _ask_platforms()
    limit = _ask_int("Top N", 10)
    min_payout = _ask_int("Minimum average payout $", 0)
    result = json.loads(tools.rank(platforms, limit, min_payout))
    if result.get("status") != "success":
        print(f"  error: {result.get('error')}")
        return
    print()
    print(rules.format_table(result))
    print()
    print(f"  {result['count']} programs, {result['fetched_details']} details fetched fresh")


def mode_bug_class():
    """Filter the ranking by a bug class."""
    bug_class = input("  Bug class (idor, auth, business_logic, response_manipulation): ").strip()
    platforms = _ask_platforms()
    limit = _ask_int("Top N", 10)
    result = json.loads(tools.filter_by_bug_class(bug_class, platforms, limit))
    if result.get("status") != "success":
        print(f"  error: {result.get('error')}")
        return
    print()
    print(rules.format_table(result))


def mode_refresh():
    """Refresh the platform data."""
    platforms = _ask_platforms()
    result = json.loads(tools.refresh(platforms, force=True))
    if result.get("status") != "success":
        print(f"  error: {result.get('error')}")
        return
    for platform, counts in result["data"].items():
        fields = ", ".join(f"{k} {v}" for k, v in counts.items())
        print(f"  {platform}: {fields}")


def mode_details():
    """Show one program in full."""
    platform = input("  Platform (hackerone, bugcrowd, intigriti): ").strip()
    handle = input("  Handle (program slug): ").strip()
    result = json.loads(tools.program_details(platform, handle))
    if result.get("status") != "success":
        print(f"  error: {result.get('error')}")
        return
    print()
    print(f"  {result['name']} ({result['platform']}/{result['handle']})")
    print(f"  score {result['score']} | avg payout ${result['avg_payout'] or '?'} "
          f"| participants {'~' if result['participants_proxy'] else ''}{result['participants']}")
    print("  why:")
    for line in result["breakdown"]:
        print(f"    - {line}")
    if result["scope_count"]:
        print(f"  scope ({result['scope_count']}):")
        for identifier in result["scopes"][:20]:
            print(f"    - {identifier}")


def mode_export():
    """Export the ranking to CSV."""
    platforms = _ask_platforms()
    limit = _ask_int("Top N", 20)
    result = json.loads(tools.export_csv(platforms, limit))
    if result.get("status") != "success":
        print(f"  error: {result.get('error')}")
        return
    print(f"  wrote {result['count']} rows to {result['file']}")


MODES = {
    "1": ("Rank programs (dupe risk + expected value)", mode_rank),
    "2": ("Filter by bug class (idor / auth / business_logic / response_manipulation)", mode_bug_class),
    "3": ("Refresh platform data", mode_refresh),
    "4": ("Show one program in detail", mode_details),
    "5": ("Export ranked list to CSV", mode_export),
}


def main():
    print("=" * 60)
    print("  Bounty Scout - bug bounty program picker")
    print("=" * 60)
    print("  Data from HackerOne, Bugcrowd and Intigriti public endpoints.")
    print("  Cached locally, no API keys needed.")
    print()
    for key, (label, _) in MODES.items():
        print(f"  {key}. {label}")
    while True:
        choice = input("  Pick a mode (1/2/3/4/5): ").strip()
        if choice in MODES:
            MODES[choice][1]()
            break
        if choice in ("q", "quit", "exit"):
            break
        print("  pick 1, 2, 3, 4 or 5")


if __name__ == "__main__":
    main()
