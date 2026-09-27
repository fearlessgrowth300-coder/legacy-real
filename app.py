"""Legacy Real -- web app for the lead engine (maps_leads.py). Backend runs on the VPS; open it on phone or PC.

    python3 app.py        (needs APP_KEY in .env; the other API keys are the same ones maps_leads.py uses)

Every tool command runs as a background job with its own log and results file, one job at a time (Gemini/Apify
limits + RAM). Keys and prospect data stay on the server: .env, reports/, results/, chats/, jobs/ are never
committed.
"""
import csv, hmac, json, os, re, secrets, subprocess, sys, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import urllib.request

import maps_leads as m

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS, CHATS, JOBS, RESULTS = (os.path.join(HERE, d) for d in ("reports", "chats", "jobs", "results"))
m.load_env_file(os.path.join(HERE, ".env"))
APP_KEY = os.environ.get("APP_KEY") or os.environ.get("CHAT_TOKEN", "")
PORT = int(os.environ.get("APP_PORT", os.environ.get("CHAT_PORT", "8765")))
SESSIONS = set()  # ponytail: in-memory logins, restart = log in again; move to a file if that gets annoying
RUNNING = {"id": None}
LOCK = threading.Lock()


# ---------------------------------------------------------------- jobs: tool commands run in the background

TEXT = re.compile(r"^[^\r\n\x00]{0,400}$")  # one line of normal text


def clean(value, pattern=TEXT, required=False):
    value = str(value or "").strip()
    if required and not value:
        raise ValueError("missing field")
    if value.startswith("-") or not pattern.match(value):  # a leading '-' could smuggle in a command flag
        raise ValueError(f"invalid value: {value[:40]}")
    return value


def build_args(kind, p):
    """Form fields -> maps_leads.py arguments (a list, never a shell string)."""
    num = lambda k, d, lo, hi: str(max(lo, min(hi, int(p.get(k) or d))))
    if kind == "hunt":
        args = ["--hunt", "--top", num("top", 5, 1, 50), "--min-price", num("min_price", 400000, 0, 10**8),
                "--min-sales", num("min_sales", 20, 0, 1000), "--min-reviews", num("min_reviews", 20, 0, 10000),
                "--per-city", num("per_city", 15, 1, 100)]
        return args + (["--teams"] if p.get("teams") else [])
    if kind == "zips":
        zips = re.findall(r"\d{5}", str(p.get("zips", "")))
        if not zips:
            raise ValueError("enter at least one 5-digit ZIP")
        return zips[:10]
    if kind == "person":
        args = ["--person", "--name", clean(p.get("name"), required=True), "--city", clean(p.get("city"), required=True)]
        for field in ("brokerage", "sites", "phone", "address", "notes"):
            if str(p.get(field) or "").strip():
                args += [f"--{field}", clean(p.get(field))]
        return args
    if kind == "audit":
        url = clean(p.get("url"), re.compile(r"^https?://[^\s]{3,300}$"), required=True)
        return ["--audit", url, clean(p.get("address")), clean(p.get("phone")), clean(p.get("name"))]
    if kind == "zillow":
        return ["--zillow-db", clean(p.get("city"), required=True), "--min-reviews", num("min_reviews", 10, 0, 10000),
                "--min-sales", num("min_sales", 0, 0, 1000), "--max", num("max", 25, 1, 200)]
    raise ValueError("unknown job type")


def job_meta(job_id):
    path = os.path.join(JOBS, job_id + ".json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


def save_meta(meta):
    os.makedirs(JOBS, exist_ok=True)
    with open(os.path.join(JOBS, meta["id"] + ".json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)


def start_job(kind, params):
    args = build_args(kind, params)
    with LOCK:
        if RUNNING["id"]:
            raise RuntimeError("another job is still running -- wait for it to finish")
        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + kind
        RUNNING["id"] = job_id
    os.makedirs(RESULTS, exist_ok=True)
    out = os.path.join(RESULTS, job_id + ".csv")
    meta = {"id": job_id, "type": kind, "params": {k: v for k, v in params.items() if v not in ("", None, False)},
            "started": time.strftime("%Y-%m-%d %H:%M"), "status": "running", "results": None}
    save_meta(meta)
    log = open(os.path.join(JOBS, job_id + ".log"), "w", encoding="utf-8")
    env = {**os.environ, "HEADLESS": "1", "LEADS_OUT": out, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "maps_leads.py"), *args], cwd=HERE, env=env,
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def wait():
        code = proc.wait()
        log.close()
        meta.update(status="done" if code == 0 else "failed", exit=code, ended=time.strftime("%Y-%m-%d %H:%M"),
                    results=os.path.basename(out) if os.path.exists(out) else None)
        save_meta(meta)
        RUNNING["id"] = None

    threading.Thread(target=wait, daemon=True).start()
    return meta


def mark_interrupted():
    """Jobs that were running when the server restarted can't be resumed -- say so instead of 'running' forever."""
    for f in os.listdir(JOBS) if os.path.isdir(JOBS) else []:
        if f.endswith(".json"):
            meta = json.load(open(os.path.join(JOBS, f), encoding="utf-8"))
            if meta.get("status") == "running":
                meta["status"] = "interrupted"
                save_meta(meta)


# ---------------------------------------------------------------- prospect chat (Sales Brain coaching)

def people():
    """Latest --person report per person: {slug: (name, path)}."""
    found = {}
    for f in sorted(os.listdir(REPORTS)) if os.path.isdir(REPORTS) else []:
        match = re.match(r"(.+?)-\d{4}-\d{2}-\d{2}-\d{4}\.txt$", f)
        if match:
            with open(os.path.join(REPORTS, f), encoding="utf-8") as fh:
                first = fh.readline()
            if "|" in first:  # --person reports start "Name | City | date"; --audit reports start with a URL
                found[match[1]] = (first.split("|")[0].strip(), os.path.join(REPORTS, f))
    return found


def first_message(report):
    block = re.search(r"MESSAGE 1\**\s*(.*?)(?:\n\s*\*?Line|\n\s*\*{3}|\n\s*-{3}|\*\*MESSAGE 2|MESSAGE 2)", report, re.S)
    return block[1].strip() if block else ""


def load_chat(slug):
    path = os.path.join(CHATS, slug + ".json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"turns": []}


def save_chat(slug, chat):
    os.makedirs(CHATS, exist_ok=True)
    with open(os.path.join(CHATS, slug + ".json"), "w", encoding="utf-8") as f:
        json.dump(chat, f, indent=1)


def coach(name, report, turns, their_message):
    """What they said -> what it means -> next goal -> reply, grounded in the report + Sales Brain."""
    history = [("agent" if t["role"] == "me" else "prospect", t["text"]) for t in turns]
    facts = report.split("SALES BRAIN PRINCIPLES:")[0][-6000:]
    principles = m.sales_brain(
        f"I'm in a LinkedIn conversation with {name}, a real estate agent/broker I want as a client for my service "
        "(fixing how their website and listings are read by Google and AI assistants). They just replied: "
        f"\"{their_message}\". What is really going on in their reply and what should I say next?", history)
    convo = "\n".join(f"{'ME' if r == 'agent' else name.upper()}: {t}" for r, t in history)
    answer = m.gemini(
        f"You coach me in a LinkedIn sales conversation with {name}.\n\nWHAT I KNOW ABOUT THEM (checked facts):\n"
        f"{facts}\n\nCONVERSATION SO FAR:\n{convo}\n{name.upper()} (latest): {their_message}\n\n"
        "MY SALES TRAINING PRINCIPLES (from my own books/videos):\n" + "\n".join(principles) + "\n\n"
        "Return JSON with keys: said (their message in plain words, 1 sentence), meaning (what's really going on: "
        "tone, interest level, what they want, any objection or buying signal), next_goal (the one thing my next "
        "message should achieve), reply (the exact message to send, natural LinkedIn style, max 90 words, no "
        "jargon), why (which principle(s) you applied and how, 1-2 lines), watch_out (one thing NOT to say now). "
        "Rules: answer any direct question honestly first; if they clearly say no, respect it and leave the door "
        "open; use ONLY the checked facts, never invent numbers/results/urgency, never promise rankings in "
        "Google or ChatGPT; don't state industry trends or how Google/AI choose who to recommend as facts (say "
        "what you found, not why it happens); don't pitch price until they show interest. 'said' must be a plain "
        "paraphrase, not a copy of their words.", as_json=True)
    try:
        out = json.loads(answer)
    except (ValueError, TypeError):
        out = {"said": "", "meaning": "", "next_goal": "", "reply": answer or "(AI unavailable, try again)",
               "why": "", "watch_out": ""}
    out["principles"] = [p.split(":")[0].lstrip("- ") for p in principles]
    return out


# ---------------------------------------------------------------- status

def apify_usage():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        return None
    try:
        d = json.load(urllib.request.urlopen(f"https://api.apify.com/v2/users/me/limits?token={token}", timeout=15))
        return {"used": round(d["data"]["current"]["monthlyUsageUsd"], 2),
                "limit": d["data"]["limits"]["maxMonthlyUsageUsd"]}
    except Exception:
        return None


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def _session(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        sid = cookie["lr_session"].value if "lr_session" in cookie else ""
        return sid if sid in SESSIONS else None

    def _send(self, body, status=200, kind="application/json", headers=()):
        data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
        self.send_response(status)
        self.send_header("Content-Type", kind + ("; charset=utf-8" if "json" in kind or "text" in kind else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = min(int(self.headers.get("Content-Length", 0)), 50000)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._send(open(os.path.join(HERE, "static", "index.html"), "rb").read(), kind="text/html")
        if path == "/manifest.json":
            return self._send(open(os.path.join(HERE, "static", "manifest.json"), "rb").read(),
                              kind="application/manifest+json")
        if not self._session():
            return self._send({"error": "login required"}, 401)
        if path == "/api/status":
            return self._send({"running": RUNNING["id"], "apify": apify_usage(),
                               "keys": {k: bool(os.environ.get(k)) for k in
                                        ("APIFY_TOKEN", "GEMINI_API_KEY", "SALES_BRAIN_API_KEY", "SNOV_CLIENT_ID",
                                         "PAGESPEED_API_KEY")}})
        if path == "/api/hot-zips":
            return self._send([{"zip": z, "city": c, "state": s, "price": p} for z, c, s, p in m.HOT_ZIPS_2026])
        if path == "/api/jobs":
            metas = [job_meta(f[:-5]) for f in sorted(os.listdir(JOBS), reverse=True)
                     if f.endswith(".json")] if os.path.isdir(JOBS) else []
            return self._send(metas[:50])
        if match := re.fullmatch(r"/api/jobs/([\w-]+)", path):
            meta = job_meta(match[1])
            if not meta:
                return self._send({"error": "not found"}, 404)
            log_path = os.path.join(JOBS, match[1] + ".log")
            log = open(log_path, encoding="utf-8", errors="ignore").read()[-20000:] if os.path.exists(log_path) else ""
            return self._send({**meta, "log": log})
        if path == "/api/results":
            files = sorted((f for f in os.listdir(RESULTS) if f.endswith(".csv")), reverse=True) \
                if os.path.isdir(RESULTS) else []
            return self._send(files)
        if match := re.fullmatch(r"/api/results/([\w.-]+\.csv)", path):
            file = os.path.join(RESULTS, match[1])
            if not os.path.exists(file):
                return self._send({"error": "not found"}, 404)
            if "download" in (urlparse(self.path).query or ""):
                return self._send(open(file, "rb").read(), kind="text/csv",
                                  headers=[("Content-Disposition", f'attachment; filename="{match[1]}"')])
            return self._send(list(csv.DictReader(open(file, encoding="utf-8"))))
        if path == "/api/reports":
            files = sorted((f for f in os.listdir(REPORTS) if f.endswith(".txt")), reverse=True) \
                if os.path.isdir(REPORTS) else []
            return self._send(files)
        if match := re.fullmatch(r"/api/reports/([\w.-]+\.txt)", path):
            file = os.path.join(REPORTS, match[1])
            return self._send(open(file, encoding="utf-8").read(), kind="text/plain") if os.path.exists(file) \
                else self._send({"error": "not found"}, 404)
        if path == "/api/people":
            return self._send([{"slug": s, "name": n, "turns": len(load_chat(s)["turns"])}
                               for s, (n, _) in people().items()])
        if (match := re.fullmatch(r"/api/chat/([\w-]+)", path)) and match[1] in people():
            name, report_path = people()[match[1]]
            report = open(report_path, encoding="utf-8").read()
            return self._send({"name": name, "report": report, "first_message": first_message(report),
                               **load_chat(match[1])})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            given = str(self._body().get("key", ""))
            if not (APP_KEY and hmac.compare_digest(given, APP_KEY)):
                time.sleep(1)  # slow down guessing
                return self._send({"error": "wrong key"}, 403)
            sid = secrets.token_urlsafe(32)
            SESSIONS.add(sid)
            return self._send({"ok": True}, headers=[(
                "Set-Cookie", f"lr_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")])
        if not self._session():
            return self._send({"error": "login required"}, 401)
        if path == "/api/logout":
            SESSIONS.discard(self._session())
            return self._send({"ok": True})
        if match := re.fullmatch(r"/api/jobs/(hunt|zips|person|audit|zillow)", path):
            try:
                return self._send(start_job(match[1], self._body()))
            except (ValueError, RuntimeError) as e:
                return self._send({"error": str(e)}, 400)
        if (match := re.fullmatch(r"/api/chat/([\w-]+)/(theirs|mine)", path)) and match[1] in people():
            text = str(self._body().get("text", "")).strip()[:4000]
            if not text:
                return self._send({"error": "empty"}, 400)
            slug, (name, report_path) = match[1], people()[match[1]]
            chat = load_chat(slug)
            turn = {"role": "me" if match[2] == "mine" else "them", "text": text,
                    "at": time.strftime("%Y-%m-%d %H:%M")}
            if match[2] == "theirs":
                turn["coach"] = coach(name, open(report_path, encoding="utf-8").read(), chat["turns"], text)
            chat["turns"].append(turn)
            save_chat(slug, chat)
            return self._send({"ok": True})
        self._send({"error": "not found"}, 404)

    def log_message(self, *args):  # keep prospects' data out of the server log
        pass


if __name__ == "__main__":
    if len(APP_KEY) < 16:
        sys.exit("Set APP_KEY (16+ random characters) in .env first")
    mark_interrupted()
    print(f"Legacy Real on port {PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
