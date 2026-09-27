# Legacy Real

Lead engine for selling "get found by Google and AI assistants" to real estate agents:

- **Hunt** hot ZIPs (Realtor.com 2026 list) → producers on Zillow (Apify) → website/page-source audit → Prospect Score
- **Person**: from a LinkedIn connection's name + city → Google Maps, Google search sweep, Zillow, every website,
  AI review and visibility checks → two LinkedIn messages written with your Sales Brain principles
- **Audit** any website (dated reports = before/after proof)
- **Prospect Chat**: paste their reply → what it means + the next message

`maps_leads.py` is the engine (CLI, `python3 maps_leads.py` for usage). `app.py` + `static/index.html` is the web app.

## Run (VPS)

```
pip install playwright && python3 -m playwright install --with-deps chromium
python3 app.py            # http://<server>:8765
```

`.env` next to the scripts (never committed):

```
APP_KEY=<16+ random chars, your login key>
APIFY_TOKEN=...            # Google search + Zillow data
GEMINI_API_KEY=...         # AI review, visibility, message writing
SALES_BRAIN_API_KEY=...    # Legacy Sales Coach principles
SNOV_CLIENT_ID=... / SNOV_CLIENT_SECRET=...   # optional email lookup
PAGESPEED_API_KEY=...      # optional speed grade
```

Prospect data (reports, results, chats, jobs, caches) stays on the server and is git-ignored.
