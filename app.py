"""Web interface for Bounty Scout.

Same logic as the CLI (tools.py), served on localhost so the ranking
is usable from a browser. Run with: python app.py
"""

import csv
import io
import json

from flask import Flask, Response, render_template, request

import rules
import tools

app = Flask(__name__)

PLATFORMS = ["hackerone", "bugcrowd", "intigriti"]
BUG_CLASSES = sorted(rules.BUG_CLASS_KEYWORDS)


def _platforms_from_form():
    """Selected platforms from the form, None means all."""
    picked = [p for p in PLATFORMS if request.form.get(p)]
    return None if not picked else picked


def _int_from_form(name, default):
    """Integer from the form with a fallback."""
    try:
        return int(request.form.get(name, default))
    except ValueError:
        return default


def _rank_table(result):
    """Build the ranked table rows for a result dict."""
    rows = []
    for i, p in enumerate(result.get("programs", []), 1):
        proxy = "~" if p["participants_proxy"] else ""
        payout = f"${p['avg_payout']:.0f}" if p["avg_payout"] else "?"
        rows.append((i, p["score"], p["name"], p["platform"], payout,
                     f"{proxy}{p['participants']}", p["breakdown"][0]))
    return rows


@app.route("/", methods=["GET"])
def index():
    """The single page."""
    return render_template("index.html", bug_classes=BUG_CLASSES)


@app.route("/run", methods=["POST"])
def run():
    """Run the chosen mode and render the result."""
    mode = request.form.get("mode", "rank")
    platforms = _platforms_from_form()
    limit = _int_from_form("limit", 10)
    min_payout = _int_from_form("min_payout", 0)

    result = None
    if mode == "rank":
        result = json.loads(tools.rank(platforms, limit, min_payout))
    elif mode == "filter":
        bug_class = request.form.get("bug_class", "idor")
        result = json.loads(tools.filter_by_bug_class(bug_class, platforms, limit))
    elif mode == "details":
        platform = request.form.get("detail_platform", "hackerone")
        handle = request.form.get("handle", "").strip()
        result = json.loads(tools.program_details(platform, handle))
    elif mode == "refresh":
        result = json.loads(tools.refresh(platforms, force=True))

    if result is None:
        result = {"status": "error", "error": f"unknown mode {mode}"}
    if result.get("status") != "success":
        return render_template("index.html", bug_classes=BUG_CLASSES,
                               error=result.get("error"))

    if mode in ("rank", "filter"):
        rows = _rank_table(result)
        note = f"{result['count']} programs, {result['fetched_details']} details fetched fresh"
        return render_template("index.html", bug_classes=BUG_CLASSES,
                               mode=mode, rows=rows, note=note)
    if mode == "details":
        return render_template("index.html", bug_classes=BUG_CLASSES,
                               detail=result)
    return render_template("index.html", bug_classes=BUG_CLASSES,
                           refresh=result["data"])


@app.route("/export", methods=["POST"])
def export():
    """Download the ranked list as CSV."""
    platforms = _platforms_from_form()
    limit = _int_from_form("limit", 20)
    result = json.loads(tools.rank(platforms, limit, 0))
    if result.get("status") != "success":
        return result.get("error"), 400

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "score", "platform", "handle", "name",
                     "avg_payout", "participants", "why"])
    for i, p in enumerate(result["programs"], 1):
        writer.writerow([i, p["score"], p["platform"], p["handle"], p["name"],
                         p["avg_payout"], p["participants"], p["breakdown"][0]])
    buffer.seek(0)
    return Response(buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=top_programs.csv"})


if __name__ == "__main__":
    print("Bounty Scout web interface: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
