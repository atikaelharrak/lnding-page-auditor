# Landing Page Health Auditor

A tool that audits any landing page for technical health, tracking/UTM
integrity, and lead-form quality, built as a software engineering
internship project, in weekly increments.

[![Tests](https://github.com/atikaelharrak/lnding-page-auditor/actions/workflows/tests.yml/badge.svg)](https://github.com/atikaelharrak/lnding-page-auditor/actions/workflows/tests.yml)

*(Replace `YOUR_USERNAME/YOUR_REPO` above with your actual GitHub path once pushed — GitHub will then show a live passing/failing badge here.)*

## What it does

Point it at a URL and it checks:
- **Technical health** : HTTPS, load time, broken images/links, alt text, mobile viewport, meta-robots/indexability
- **Tracking & UTM integrity** : UTM parameter coverage, completeness, naming consistency, duplicate/malformed tracking links
- **Lead form quality** : CAPTCHA/anti-bot protection, honeypot fields, required-field validation, secure form submission

Results come back as a 0–100 score per category plus an overall score, with specific pass/warning/critical findings and suggested fixes.

## Project structure

```
site_auditor/
├── crawler.py          # Fetches a URL, extracts images/links/forms/meta tags
├── checks.py            # Technical health checks
├── utm_checks.py         # Tracking/UTM integrity checks
├── form_checks.py         # Lead-form quality checks
├── report.py               # Combines all checks into one scored report
├── db.py                     # SQLite persistence, stores every audit run
├── cache.py                   # Rate-limiting/caching, avoids re-crawling recently-audited URLs
├── jobs.py                     # Background job processing for async audits
├── api.py                       # REST API (Flask Blueprint), JSON endpoints
├── app.py                        # Flask web frontend (HTML) + registers the API
├── main.py                        # CLI entry point
├── templates/index.html            # Web report page
├── static/style.css                 # Styling
├── tests/                             # 206 tests across every module (see below)
├── .github/workflows/tests.yml         # CI: runs the test suite on every push/PR
├── pytest.ini
└── requirements.txt
```

## Architecture

```
                    ┌─────────────┐
                    │  crawler.py │  fetches & parses a URL
                    └──────┬──────┘
                           │ PageData
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    checks.py        utm_checks.py    form_checks.py
   (technical)          (UTM)          (lead forms)
          │                │                │
          └────────────────┼────────────────┘
                           ▼
                     ┌───────────┐
                     │ report.py │  combines + scores
                     └─────┬─────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
          db.py        cache.py      jobs.py
        (persist)    (avoid re-crawl) (async)
              │            │            │
              └────────────┼────────────┘
                           ▼
                    ┌─────────────┐
                    │   api.py    │  REST endpoints
                    └──────┬──────┘
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
          app.py                    main.py
      (HTML frontend)              (CLI)
```

Each layer only depends on the ones below it. `crawler.py` doesn't know
checks exist; `checks.py`/`utm_checks.py`/`form_checks.py` don't know
about scoring or persistence; `report.py` doesn't know about HTTP or
databases; `db.py`/`cache.py`/`jobs.py` don't know about Flask. This
means each piece can be tested (and understood) in isolation.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate      # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Usage

**CLI:**
```bash
python main.py cubehead.info
```

**Web frontend:**
```bash
python app.py
```
Then open `http://127.0.0.1:5000`.

**REST API** (once `app.py` is running):
```bash
# Run a synchronous audit (cache-aware)
curl -X POST http://127.0.0.1:5000/api/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "cubehead.info"}'

# Force a fresh crawl, bypassing the cache
curl -X POST http://127.0.0.1:5000/api/audit \
  -H "Content-Type: application/json" \
  -d '{"url": "cubehead.info", "force": true}'

# Submit as a background job instead (returns immediately)
curl -X POST http://127.0.0.1:5000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"url": "cubehead.info"}'
# -> {"id": "...", "status": "pending", ...}

# Poll for the job result
curl http://127.0.0.1:5000/api/jobs/<job_id>

# Get audit history for a URL
curl "http://127.0.0.1:5000/api/history?url=cubehead.info"

# Get just the score trend over time
curl "http://127.0.0.1:5000/api/trend?url=cubehead.info"

# List recent audits across all URLs
curl http://127.0.0.1:5000/api/audits
```

## Tests

**206 tests, all passing.**

```bash
pytest                             # everything except 2 real-network tests, ~1.5s
pytest -m integration              # the 2 tests that hit a real live site
pytest -v                          # see every test name
```

| File | Covers |
|---|---|
| `tests/conftest.py` | Shared `make_page()` helper, builds `PageData` from synthetic HTML, no network. |
| `tests/test_crawler.py` | HTML extraction: images, links, forms, meta tags. |
| `tests/test_crawler_network.py` | Network error handling, URL normalization, + 2 real-network tests. |
| `tests/test_checks.py` | Technical health checks. |
| `tests/test_utm_checks.py` | UTM/tracking checks, including a regression test for a duplicate-query-key bug. |
| `tests/test_form_checks.py` | Lead-form quality checks. |
| `tests/test_report.py` | Shared report-building logic, category weighting. |
| `tests/test_db.py` | SQLite persistence: save/retrieve/history/trend queries. |
| `tests/test_cache.py` | TTL-based cache hit/miss logic, boundary conditions. |
| `tests/test_jobs.py` | Background job lifecycle, genuine-async verification, failure handling. |
| `tests/test_api.py` | Every REST endpoint, including caching behavior end-to-end. |
| `tests/test_app.py` | Flask HTML routes, history display, error states. |

## Continuous Integration

`.github/workflows/tests.yml` runs the full offline test suite
automatically on every push and pull request to `main`, against Python
3.11 and 3.12. The 2 real-network tests are excluded from CI (external
site availability shouldn't be able to block a merge) but are run
manually during development.

## Design notes and tradeoffs

These are deliberate choices made for this project's scope, worth
being able to explain in a review, since "why didn't you use X" is a
common follow-up question:

- **SQLite, not Postgres/MySQL.** No separate database server to run or
  configure; the entire database is one file. Appropriate for a
  single-process internal tool; would reconsider for a multi-server
  deployment.
- **Audit results stored as a JSON blob (`categories_json`), not a
  fully normalized schema.** We never need to query "all failed checks
  named X across every audit ever run", only "give me the audits for
  this URL" and "give me the score trend." A 3+ table normalized schema
  would add migration/join complexity for no benefit we actually use.
- **Plain `threading.ThreadPoolExecutor`, not Celery/RQ, for background
  jobs.** Audits are I/O-bound (waiting on network responses), so
  threads are sufficient, no need for separate worker processes or a
  message broker. The job store is in-memory and doesn't survive a
  server restart, which is fine for this scope; moving job state into
  the database would be the natural next step if that mattered.
- **Cache lives in the same SQLite database as audit history, not a
  separate store like Redis.** We already store every audit with a
  timestamp; "is there a recent one" is one query against data that
  already exists, with no second source of truth to keep in sync.
- **The 2 real-network tests are excluded from CI, not deleted.** They
  provide real value (proving the crawler works against an actual
  server, not just mocked responses) but external site behavior
  shouldn't be able to fail a CI run through no fault of the code.

## A genuine bug found during development

While building the background job tests, a subtle concurrency bug
surfaced: `unittest.mock.patch()` only patches for the duration of its
`with` block on the *calling* thread. Since audit jobs run on a
separate worker thread from a `ThreadPoolExecutor`, if the `with`
block exited before the worker thread actually called the mocked
function, the patch was already undone, and a real network request
would slip through instead of the mock, causing intermittent test
failures. Fixed by ensuring every test polls for job completion
*while still inside* the patch context, guaranteeing the mock stays
active for as long as the worker thread might need it. Confirmed fixed
by running the affected test file 5 times in a row with zero flakiness
(previously it failed intermittently).

## Known limitations / possible future extensions

- No authentication on the API : fine for a local/internal tool, would
  need addressing before any public deployment.
- Job state doesn't survive a server restart (in-memory only).
- Still doesn't render JavaScript-heavy pages, a good candidate for a
  Playwright-based crawler upgrade if real target pages turn out to be
  JS-heavy SPAs.
- No rate limiting on the API endpoints themselves (only on re-crawling
  the same URL), a public-facing deployment would want per-client
  request throttling too.
