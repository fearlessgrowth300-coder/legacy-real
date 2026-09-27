"""Legacy Real -- web app for the lead engine (maps_leads.py). Backend runs on the VPS; open it on phone or PC.

    python3 app.py        (needs APP_KEY in .env; the other API keys are the same ones maps_leads.py uses)

Every tool command runs as a background job with its own log and results file, one job at a time (Gemini/Apify
limits + RAM). Keys and prospect data stay on the server: .env, reports/, results/, chats/, jobs/ are never
committed.
"""
import csv, hashlib, hmac, json, os, re, secrets, subprocess, sys, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote
import urllib.request

import maps_leads as m

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS, CHATS, JOBS, RESULTS = (os.path.join(HERE, d) for d in ("reports", "chats", "jobs", "results"))
ENV_FILE, USERS_FILE = os.path.join(HERE, ".env"), os.path.join(HERE, "data", "users.json")
m.load_env_file(ENV_FILE)
APP_KEY = os.environ.get("APP_KEY") or os.environ.get("CHAT_TOKEN", "")  # one-time setup code for the first account
PORT = int(os.environ.get("APP_PORT", os.environ.get("CHAT_PORT", "8765")))
SESSIONS = {}  # sid -> username. ponytail: in-memory, a server restart = sign in again
RUNNING = {"id": None}
LOCK = threading.Lock()

# Keys the Settings page may add/replace/remove (nothing else in .env is reachable from the web)
INTEGRATIONS = [
    {"id": "gemini", "name": "Google Gemini", "fields": ["GEMINI_API_KEY"],
     "powers": "AI Review of page sources, AI Visibility checks, message writing, chat coaching",
     "get": "aistudio.google.com → Get API key"},
    {"id": "apify", "name": "Apify", "fields": ["APIFY_TOKEN"],
     "powers": "Google search sweep for people, Zillow agent data (sales, reviews, volume)",
     "get": "console.apify.com → Settings → API & Integrations"},
    {"id": "salesbrain", "name": "Sales Brain", "fields": ["SALES_BRAIN_API_KEY"],
     "powers": "Principles from your books & videos for every message and chat reply",
     "get": "Legacy Sales Coach → Settings → Sales Brain API key (lsc_live_…)"},
    {"id": "snov", "name": "Snov.io", "fields": ["SNOV_CLIENT_ID", "SNOV_CLIENT_SECRET"],
     "powers": "Email lookup when an agent's website shows none",
     "get": "app.snov.io → Account → API"},
    {"id": "pagespeed", "name": "Google PageSpeed", "fields": ["PAGESPEED_API_KEY"],
     "powers": "Mobile speed grade in audits",
     "get": "console.cloud.google.com → APIs → PageSpeed Insights API → Credentials"},
]
EDITABLE = {f for i in INTEGRATIONS for f in i["fields"]}


# ---------------------------------------------------------------- accounts & settings

def users():
    return json.load(open(USERS_FILE, encoding="utf-8")) if os.path.exists(USERS_FILE) else {}


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return f"{salt}${digest}"


def check_password(password, stored):
    salt, _, digest = stored.partition("$")
    return hmac.compare_digest(hash_password(password, salt).partition("$")[2], digest)


def save_user(name, password):
    all_users = users()
    all_users[name] = {"password": hash_password(password), "created": time.strftime("%Y-%m-%d")}
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(all_users, f, indent=1)
    os.chmod(USERS_FILE, 0o600)


def set_env(key, value):
    """Add/replace (value) or remove (None) one key in .env and in this process; jobs start with the new value."""
    lines = open(ENV_FILE, encoding="utf-8").read().splitlines() if os.path.exists(ENV_FILE) else []
    lines = [l for l in lines if not l.startswith(key + "=")]
    if value:
        lines.append(f"{key}={value}")
        os.environ[key] = value
    else:
        os.environ.pop(key, None)
    tmp = ENV_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_FILE)
    m._gemini_exhausted.clear()
    m._visibility_cache.pop("_no_brain", None)


def mask(value):
    return ("•" * 6 + value[-4:]) if value and len(value) > 8 else ("•" * 6 if value else "")


def test_integration(iid):
    """A cheap real call per service, so 'connected' means the key actually works."""
    env = os.environ
    try:
        if iid == "gemini":
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=5"
            urllib.request.urlopen(urllib.request.Request(url, headers={"x-goog-api-key": env["GEMINI_API_KEY"]}),
                                   timeout=20)
            return True, "Key accepted by Google"
        if iid == "apify":
            usage = apify_usage()
            return (True, f"Connected · ${usage['used']} of ${usage['limit']} used this month") if usage \
                else (False, "Apify rejected the token")
        if iid == "salesbrain":
            return (True, "Sales Brain answered with principles") if m.sales_brain("cold outreach first message") \
                else (False, "No principles returned — check the key and that the Sales Brain API is deployed")
        if iid == "snov":
            body = m.urlencode({"grant_type": "client_credentials", "client_id": env["SNOV_CLIENT_ID"],
                                "client_secret": env["SNOV_CLIENT_SECRET"]}).encode()
            json.load(urllib.request.urlopen("https://api.snov.io/v1/oauth/access_token", body, 20))["access_token"]
            return True, "Snov.io accepted the keys"
        if iid == "pagespeed":
            url = ("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=https://example.com&strategy=mobile"
                   f"&category=performance&key={env['PAGESPEED_API_KEY']}")
            urllib.request.urlopen(url, timeout=90)
            return True, "PageSpeed answered"
    except KeyError:
        return False, "Not connected yet"
    except Exception as e:
        return False, f"Failed: {str(e)[:120]}"
    return False, "Unknown integration"


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
    """Jobs / chat analyses that were running when the server restarted can't be resumed -- say so."""
    for f in os.listdir(CHATS) if os.path.isdir(CHATS) else []:
        chat = load_chat(f[:-5])
        stuck = [t for t in chat["turns"] if (t.get("coach") or {}).get("pending")]
        for t in stuck:
            t["coach"] = {"reply": "(The server restarted during this analysis -- paste their reply again.)"}
        if stuck:
            save_chat(f[:-5], chat)
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


# ---------------------------------------------------------------- dashboard data

def result_sets():
    """Result files with a readable label from their job."""
    out = []
    for f in sorted((f for f in os.listdir(RESULTS) if f.endswith(".csv")), reverse=True) if os.path.isdir(RESULTS) else []:
        meta = job_meta(f[:-4]) or {}
        params = meta.get("params", {})
        what = {"hunt": f"Hunt · top {params.get('top', '?')} hot areas", "zips": f"ZIPs {params.get('zips', '')}",
                "zillow": f"Zillow · {params.get('city', '')}"}.get(meta.get("type"), meta.get("type") or "Imported")
        rows = sum(1 for _ in csv.DictReader(open(os.path.join(RESULTS, f), encoding="utf-8")))  # pitches span lines
        out.append({"file": f, "label": what, "date": meta.get("started", ""), "rows": max(rows, 0)})
    return out


def dashboard():
    sets = result_sets()
    scores, excellent = {"EXCELLENT": 0, "OKAY": 0, "POOR": 0}, []
    for s in sets[:10]:
        for r in csv.DictReader(open(os.path.join(RESULTS, s["file"]), encoding="utf-8")):
            tier = (r.get("Prospect Score") or "").split(":")[0]
            if tier in scores:
                scores[tier] += 1
            if tier == "EXCELLENT" and len(excellent) < 6:
                excellent.append({"name": r.get("Business Name", ""), "why": r["Prospect Score"].split(":", 1)[1].strip(),
                                  "file": s["file"]})
    everyone = people()
    chats_active = sum(1 for s in everyone if load_chat(s)["turns"])
    return {"leads": sum(s["rows"] for s in sets), "scores": scores, "excellent": excellent,
            "people": len(everyone), "chats": chats_active, "running": RUNNING["id"],
            "connected": {i["id"]: all(os.environ.get(f) for f in i["fields"]) for i in INTEGRATIONS},
            "recent_jobs": [job_meta(f[:-5]) for f in sorted(os.listdir(JOBS), reverse=True)
                            if f.endswith(".json")][:5] if os.path.isdir(JOBS) else []}


# ---------------------------------------------------------------- HTTP

STATIC = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"), "/manifest.json": ("manifest.json", "application/manifest+json"),
          "/icon.svg": ("icon.svg", "image/svg+xml")}
USERNAME = re.compile(r"^[A-Za-z0-9_.@-]{3,40}$")


class Handler(BaseHTTPRequestHandler):
    def _user(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return SESSIONS.get(cookie["lr_session"].value) if "lr_session" in cookie else None

    def _send(self, body, status=200, kind="application/json", headers=()):
        data = body if isinstance(body, bytes) else (body.encode() if isinstance(body, str) else json.dumps(body).encode())
        self.send_response(status)
        self.send_header("Content-Type", kind + ("; charset=utf-8" if kind.startswith(("text", "application/json")) else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Robots-Tag", "noindex")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        length = min(int(self.headers.get("Content-Length", 0)), 50000)
        return json.loads(self.rfile.read(length) or b"{}")

    def _sign_in(self, name):
        sid = secrets.token_urlsafe(32)
        SESSIONS[sid] = name
        return self._send({"ok": True, "user": name}, headers=[(
            "Set-Cookie", f"lr_session={sid}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")])

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in STATIC:
            file, kind = STATIC[path]
            return self._send(open(os.path.join(HERE, "static", file), "rb").read(), kind=kind)
        if path == "/api/me":
            return self._send({"user": self._user(), "needs_setup": not users()})
        if not self._user():
            return self._send({"error": "sign in required"}, 401)
        if path == "/api/dashboard":
            return self._send(dashboard())
        if path == "/api/settings":
            return self._send([{**i, "values": {f: mask(os.environ.get(f, "")) for f in i["fields"]},
                                "connected": all(os.environ.get(f) for f in i["fields"])} for i in INTEGRATIONS])
        if path == "/api/status":
            return self._send({"running": RUNNING["id"], "apify": apify_usage()})
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
            return self._send(result_sets())
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
            return self._send([{"slug": s, "name": n, "turns": len(load_chat(s)["turns"]),
                                "last": (load_chat(s)["turns"] or [{}])[-1].get("at", "")}
                               for s, (n, _) in people().items()])
        if (match := re.fullmatch(r"/api/chat/([\w-]+)", path)) and match[1] in people():
            name, report_path = people()[match[1]]
            report = open(report_path, encoding="utf-8").read()
            return self._send({"name": name, "report": report, "first_message": first_message(report),
                               **load_chat(match[1])})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/setup":  # first account only; needs the setup code from the server's .env
            if users():
                return self._send({"error": "already set up"}, 400)
            b = self._body()
            if not (APP_KEY and hmac.compare_digest(str(b.get("code", "")), APP_KEY)):
                time.sleep(1)
                return self._send({"error": "wrong setup code"}, 403)
            name, pw = str(b.get("username", "")).strip(), str(b.get("password", ""))
            if not USERNAME.match(name) or len(pw) < 10:
                return self._send({"error": "username 3-40 characters; password at least 10 characters"}, 400)
            save_user(name, pw)
            return self._sign_in(name)
        if path == "/api/login":
            b = self._body()
            name, record = str(b.get("username", "")).strip(), users().get(str(b.get("username", "")).strip())
            if not (record and check_password(str(b.get("password", "")), record["password"])):
                time.sleep(1)  # slow down guessing
                return self._send({"error": "wrong username or password"}, 403)
            return self._sign_in(name)
        user = self._user()
        if not user:
            return self._send({"error": "sign in required"}, 401)
        if path == "/api/logout":
            for sid, name in list(SESSIONS.items()):
                if name == user:
                    SESSIONS.pop(sid)
            return self._send({"ok": True})
        if path == "/api/password":
            b = self._body()
            if not check_password(str(b.get("current", "")), users()[user]["password"]):
                time.sleep(1)
                return self._send({"error": "current password is wrong"}, 403)
            if len(str(b.get("new", ""))) < 10:
                return self._send({"error": "new password must be at least 10 characters"}, 400)
            save_user(user, str(b["new"]))
            return self._send({"ok": True})
        if match := re.fullmatch(r"/api/settings/(\w+)(/test|/remove)?", path):
            integ = next((i for i in INTEGRATIONS if i["id"] == match[1]), None)
            if not integ:
                return self._send({"error": "unknown integration"}, 404)
            if match[2] == "/test":
                ok, msg = test_integration(integ["id"])
                return self._send({"ok": ok, "message": msg})
            if match[2] == "/remove":
                for f in integ["fields"]:
                    set_env(f, None)
                return self._send({"ok": True})
            values = self._body()
            for f in integ["fields"]:
                v = str(values.get(f, "")).strip()
                if v and (not re.fullmatch(r"[A-Za-z0-9_.\-:/+=]{8,300}", v)):
                    return self._send({"error": f"{f} doesn't look like a valid key"}, 400)
            for f in integ["fields"]:
                if str(values.get(f, "")).strip():
                    set_env(f, str(values[f]).strip())
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
            turn = {"role": "me" if match[2] == "mine" else "them", "text": text,
                    "at": time.strftime("%Y-%m-%d %H:%M")}
            if match[2] == "theirs":
                turn["coach"] = {"pending": True}  # 30-90s of AI work: answer now, fill in when done
            with LOCK:  # the background coach writes the same file
                chat = load_chat(slug)
                history = list(chat["turns"])
                chat["turns"].append(turn)
                index = len(chat["turns"]) - 1
                save_chat(slug, chat)
            if match[2] == "theirs":
                def work():
                    result = coach(name, open(report_path, encoding="utf-8").read(), history, text)
                    with LOCK:
                        latest = load_chat(slug)
                        latest["turns"][index]["coach"] = result
                        save_chat(slug, latest)
                threading.Thread(target=work, daemon=True).start()
            return self._send({"ok": True})
        self._send({"error": "not found"}, 404)

    def log_message(self, *args):  # keep prospects' data out of the server log
        pass


if __name__ == "__main__":
    if not users() and len(APP_KEY) < 16:
        sys.exit("Set APP_KEY (16+ random characters) in .env -- it's the one-time setup code for your account")
    mark_interrupted()
    print(f"Legacy Real on port {PORT}")
    # on the VPS APP_HOST=127.0.0.1: only Caddy (https) can reach the app, the plain port stays closed
    ThreadingHTTPServer((os.environ.get("APP_HOST", "0.0.0.0"), PORT), Handler).serve_forever()
