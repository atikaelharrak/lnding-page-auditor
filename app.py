"""
app.py
------
Web frontend for the Landing Page Health Auditor.

As of this version, the "real" logic lives in two places:
  - report.py    : fetch a URL + run checks + score it (pure function, no I/O)
  - db.py         : persist and retrieve audit results (SQLite)
  - api.py        : a REST API (Flask Blueprint) exposing both of the above as JSON

This file (app.py) is now just the HTML-rendering layer: it registers
the API blueprint under /api, and its own "/" route calls report.py +
db.py directly (same as the API does) to render a human-friendly page.
The HTML frontend and the JSON API are two independent consumers of the
same underlying logic — neither depends on the other, which is what
lets a script or another service use /api/* without ever touching HTML.

Run locally:
    python app.py
Then open http://127.0.0.1:5000 in a browser for the HTML UI,
or POST to http://127.0.0.1:5000/api/audit for the JSON API.
"""

from flask import Flask, render_template, request

import db
from api import api as api_blueprint
from report import build_report

app = Flask(__name__)
app.register_blueprint(api_blueprint)

# Ensure the database and its table exist before the app starts serving
# requests. init_db() is idempotent (CREATE TABLE IF NOT EXISTS), so
# this is safe to run every time the app boots.
db.init_db()


@app.route("/", methods=["GET", "POST"])
def index():
    report = None
    error = None
    submitted_url = ""
    history = None

    if request.method == "POST":
        submitted_url = request.form.get("url", "").strip()
        if not submitted_url:
            error = "Please enter a URL to audit."
        else:
            try:
                report = build_report(submitted_url)
                db.save_audit(report)
            except Exception as e:
                # Defensive catch-all: build_report/fetch_page already handle
                # network errors gracefully via PageData.error, but this
                # guards against any unexpected exception so the page never
                # shows a raw Flask error trace to the user.
                error = f"Something went wrong while auditing this URL: {e}"

            if report is not None:
                # Show past audits for this URL, if any exist, so the
                # person can see whether the score is improving over time.
                history = db.get_audit_history(submitted_url, limit=5)

    return render_template(
        "index.html",
        report=report,
        error=error,
        submitted_url=submitted_url,
        history=history,
    )


if __name__ == "__main__":
    # debug=True is fine for local development / demoing during the
    # internship; would be turned off for any real deployment.
    app.run(debug=True)
