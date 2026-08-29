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


def _state():
    """Form values to echo back into the page, defaults for a plain GET."""
    is_post = request.method == "POST"
    form = request.form
    return {
        "mode": form.get("mode") or "rank",
        "limit": form.get("limit") or "10",
        "min_payout": form.get("min_payout") or "0",
        "bug_class": form.get("bug_class") or "idor",
        "detail_platform": form.get("detail_platform") or "hackerone",
        "handle": form.get("handle") or "",
        "platforms": {p: (form.get(p) == "on") if is_post else True for p in PLATFORMS},
    }


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
                     f"{proxy}{p['participants']}", p["breakdown"][0],
                     " | ".join(p["breakdown"])))
    return rows


def _csv_response(result):
    """Stream a ranked list as a CSV download."""
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


@app.route("/", methods=["GET"])
def index():
    """The single page."""
    return render_template("index.html", state=_state())


@app.route("/run", methods=["POST"])
def run():
    """Run the chosen mode and render the result."""
    state = _state()
    mode = state["mode"]
    platforms = _platforms_from_form()
    limit = _int_from_form("limit", 10)
    min_payout = _int_from_form("min_payout", 0)

    if mode == "rank":
        result = json.loads(tools.rank(platforms, limit, min_payout))
        if result.get("status") == "success":
            return render_template("index.html", state=state, rows=_rank_table(result),
                                   note=f"{result['count']} programs, "
                                        f"{result['fetched_details']} details fetched fresh")
        return render_template("index.html", state=state, error=result.get("error"))

    if mode == "filter":
        result = json.loads(tools.filter_by_bug_class(state["bug_class"], platforms, limit))
        if result.get("status") == "success":
            return render_template("index.html", state=state, rows=_rank_table(result),
                                   note=f"{result['count']} programs match "
                                        f"'{state['bug_class']}' scope keywords")
        return render_template("index.html", state=state, error=result.get("error"))

    if mode == "details":
        result = json.loads(tools.program_details(state["detail_platform"], state["handle"]))
        if result.get("status") == "success":
            return render_template("index.html", state=state, detail=result)
        return render_template("index.html", state=state, error=result.get("error"))

    if mode == "refresh":
        result = json.loads(tools.refresh(platforms, force=True))
        if result.get("status") == "success":
            return render_template("index.html", state=state, refresh=result["data"])
        return render_template("index.html", state=state, error=result.get("error"))

    if mode == "export":
        result = json.loads(tools.rank(platforms, limit, 0))
        if result.get("status") == "success":
            return _csv_response(result)
        return render_template("index.html", state=state, error=result.get("error"))

    return render_template("index.html", state=state,
                           error=f"unknown mode {mode}")


@app.route("/export", methods=["POST"])
def export():
    """Download the ranked list as CSV."""
    platforms = _platforms_from_form()
    limit = _int_from_form("limit", 20)
    result = json.loads(tools.rank(platforms, limit, 0))
    if result.get("status") != "success":
        return result.get("error"), 400
    return _csv_response(result)


if __name__ == "__main__":
    print("Bounty Scout web interface: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True)
