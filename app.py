"""Legacy Real -- web app for the lead engine (maps_leads.py). Backend runs on the VPS; open it on phone or PC.

    python3 app.py        (needs APP_KEY in .env; the other API keys are the same ones maps_leads.py uses)

Every tool command runs as a background job with its own log and results file, one job at a time (Gemini/Apify
limits + RAM). Keys and prospect data stay on the server: .env, reports/, results/, chats/, jobs/ are never
committed.
"""
import base64, csv, hashlib, html, hmac, json, os, re, secrets, shutil, signal, subprocess, sys, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlparse, parse_qs, unquote
import smtplib, ssl, urllib.request
from email.message import EmailMessage
from email.utils import formataddr

import maps_leads as m

HERE = os.path.dirname(os.path.abspath(__file__))
REPORTS, CHATS, JOBS, RESULTS = (os.path.join(HERE, d) for d in ("reports", "chats", "jobs", "results"))
ENV_FILE, USERS_FILE = os.path.join(HERE, ".env"), os.path.join(HERE, "data", "users.json")
m.load_env_file(ENV_FILE)
APP_KEY = os.environ.get("APP_KEY") or os.environ.get("CHAT_TOKEN", "")  # one-time setup code for the first account
PORT = int(os.environ.get("APP_PORT", os.environ.get("CHAT_PORT", "8765")))
SESSIONS = {}  # sid -> username. ponytail: in-memory, a server restart = sign in again
RUNNING = {"id": None, "proc": None, "stopped": False}
AI_MODELS = {"claude": ["", "sonnet", "opus", "haiku"]}  # "" = the CLI's default for the plan
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
    {"id": "gmail", "name": "Gmail (sign in with Google)", "fields": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
     "extra": ["GMAIL_REFRESH_TOKEN", "GMAIL_ADDRESS"], "oauth": True,
     "powers": "Send the drafted emails from your Gmail -- click Connect Gmail and approve, no passwords",
     "get": "One-time: your own Google sign-in app (Client ID + Secret) -- steps in the chat / README"},
    {"id": "email", "name": "Other email (app password)", "fields": ["SMTP_USER", "SMTP_PASS", "SMTP_FROM_NAME", "SMTP_HOST"],
     "optional": ["SMTP_HOST"],
     "powers": "Send the drafted emails to leads from your own address (Gmail, Outlook, Yahoo, iCloud, Zoho...)",
     "get": "Gmail: myaccount.google.com → Security → 2-Step Verification → App passwords (use that, not your normal "
            "password). SMTP_HOST only for custom domains, e.g. smtp.gmail.com for Google Workspace"},
    {"id": "pagespeed", "name": "Google PageSpeed", "fields": ["PAGESPEED_API_KEY"],
     "powers": "Mobile speed grade in audits",
     "get": "console.cloud.google.com → APIs → PageSpeed Insights API → Credentials"},
]
EDITABLE = {f for i in INTEGRATIONS for f in i["fields"]}
FIELD_PATTERNS = {"SMTP_USER": r"[^@\s,;<>]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "SMTP_FROM_NAME": r"[\w .,'&-]{2,60}",
                  "SMTP_HOST": r"[A-Za-z0-9.-]{4,100}(:\d{2,5})?",
                  "GOOGLE_CLIENT_ID": r"[\w.-]{10,200}\.apps\.googleusercontent\.com"}
APP_URL = os.environ.get("APP_URL", "https://legacy-real.vercel.app")  # where Google sends you back after Connect
OAUTH_STATES = {}  # state -> time, proves the callback belongs to a Connect click from a signed-in user
EMAIL = re.compile(r"[^@\s,;<>\"']{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SMTP_HOSTS = {"gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com", "outlook.com": "smtp.office365.com",
              "hotmail.com": "smtp.office365.com", "live.com": "smtp.office365.com", "yahoo.com": "smtp.mail.yahoo.com",
              "icloud.com": "smtp.mail.me.com", "me.com": "smtp.mail.me.com", "zoho.com": "smtp.zoho.com"}
SENT_FILE = os.path.join(HERE, "data", "sent.json")
TASKS = {}  # id -> {"status": pending|done|error, ...}. ponytail: in-memory, a restart forgets unfinished ones


def connected(integ):
    return all(os.environ.get(f) for f in integ["fields"] if f not in integ.get("optional", []))


def smtp_open():
    user = os.environ["SMTP_USER"]
    host = os.environ.get("SMTP_HOST") or SMTP_HOSTS.get(user.split("@")[1].lower(), "smtp." + user.split("@")[1])
    host, _, port = host.partition(":")
    port = int(port or 587)
    server = smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) if port == 465 \
        else smtplib.SMTP(host, port, timeout=30)
    if port != 465:
        server.starttls(context=ssl.create_default_context())
    server.login(user, os.environ["SMTP_PASS"])
    return server


def google_token(params):
    return json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"], **params}).encode(),
        timeout=20))


def gmail_access_token():
    return google_token({"grant_type": "refresh_token", "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"]})["access_token"]


def email_ready():
    return bool(os.environ.get("GMAIL_REFRESH_TOKEN") or connected(next(i for i in INTEGRATIONS if i["id"] == "email")))


def send_email(to, subject, body, track=""):
    """Gmail (signed in with Google) when connected, otherwise the app-password mailbox. track = id of an invisible
    1px image (opens). Returns the Gmail threadId (to spot replies/bounces later) or ""."""
    gmail = os.environ.get("GMAIL_REFRESH_TOKEN")
    msg = EmailMessage()
    msg["From"] = formataddr((os.environ.get("SMTP_FROM_NAME", ""),
                              os.environ["GMAIL_ADDRESS"] if gmail else os.environ["SMTP_USER"]))
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    if track:  # plain text for spam filters + the same text as HTML carrying the open pixel
        msg.add_alternative(
            '<div style="font-family:Arial,sans-serif;font-size:14px">' + html.escape(body).replace("\n", "<br>")
            + f'</div><img src="{APP_URL}/api/t/{track}.gif" width="1" height="1" alt="" style="display:block">',
            subtype="html")
    if gmail:
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send", json.dumps({"raw": raw}).encode(),
                {"Authorization": f"Bearer {gmail_access_token()}", "Content-Type": "application/json"}),
                timeout=30)).get("threadId", "")
        except urllib.error.HTTPError as e:  # surface Google's reason (API disabled, quota...) instead of "403"
            reason = json.loads(e.read() or b"{}").get("error", {}).get("message", "")
            raise RuntimeError(f"Gmail said: {reason.split(' Enable it')[0] or e}") from None
    with smtp_open() as server:
        server.send_message(msg)
    return ""


def sent_log():
    return json.load(open(SENT_FILE, encoding="utf-8")) if os.path.exists(SENT_FILE) else []


def save_sent(log):
    os.makedirs(os.path.dirname(SENT_FILE), exist_ok=True)
    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=1)


def log_sent(entry):
    with LOCK:
        save_sent(sent_log() + [entry])


def open_device(agent):
    """(device, proxy) from the image request's User-Agent. Gmail/Apple/Yahoo fetch images through their own
    servers, so for those readers the device and place are hidden -- proxy says whose server it was."""
    if "GoogleImageProxy" in agent:
        return "Gmail (Google hides the device)", "Google"
    if "YahooMailProxy" in agent:
        return "Yahoo Mail (Yahoo hides the device)", "Yahoo"
    if agent.strip() in ("Mozilla/5.0", ""):  # Apple Mail Privacy Protection: may load it before a human opens it
        return "Apple Mail privacy (may be automatic, not a real open)", "Apple"
    os_name = next((label for key, label in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android"),
                                              ("Windows", "Windows PC"), ("Macintosh", "Mac"), ("Linux", "Linux"))
                    if key in agent), "unknown device")
    app_name = next((label for key, label in (("Outlook", "Outlook"), ("Thunderbird", "Thunderbird"),
                                               ("Edg/", "Edge"), ("Chrome/", "Chrome"), ("Safari/", "Safari"),
                                               ("Firefox/", "Firefox")) if key in agent), "")
    return (f"{os_name} · {app_name}" if app_name else os_name), ""


def ip_place(ip):
    """City, region, country for a public IP (ipwho.is, free, no key)."""
    try:
        d = json.load(urllib.request.urlopen(f"https://ipwho.is/{ip}?fields=success,city,region,country", timeout=8))
        return ", ".join(x for x in (d.get("city"), d.get("region"), d.get("country")) if x) if d.get("success") else ""
    except Exception:
        return ""


def log_open(track, headers):
    agent = headers.get("User-Agent", "")
    device, proxy = open_device(agent)
    # real visitor IP: Vercel forwards it (Caddy overwrites X-Forwarded-For with Vercel's own address)
    ip = (headers.get("X-Vercel-Forwarded-For") or headers.get("X-Real-Ip") or headers.get("X-Forwarded-For")
          or "").split(",")[0].strip()
    place = "" if proxy else ", ".join(unquote(x) for x in (headers.get("X-Vercel-Ip-City"),
                                                           headers.get("X-Vercel-Ip-Country-Region"),
                                                           headers.get("X-Vercel-Ip-Country")) if x)
    entry = {"at": time.strftime("%Y-%m-%d %H:%M"), "device": device, "via": agent[:160], "ip": ip,
             "place": place or (f"{proxy}'s servers" if proxy else "")}
    with LOCK:
        log = sent_log()
        for e in log:
            if e.get("id") == track:
                e.setdefault("opens", []).append(entry)
                save_sent(log)
                break
        else:
            return
    if not entry["place"] and ip:  # look the IP up after answering the image request

        def locate():
            where = ip_place(ip)
            with LOCK:
                log = sent_log()
                for e in log:
                    for o in e.get("opens", []) if e.get("id") == track else []:
                        if o.get("ip") == ip and not o.get("place"):
                            o["place"] = where
                save_sent(log)
        threading.Thread(target=locate, daemon=True).start()


CHECKING = {"last": 0}


def check_replies():
    """For Gmail threads we started: did they reply? did it bounce? (reads only the From/Date headers)"""
    if not os.environ.get("GMAIL_REFRESH_TOKEN") or time.time() - CHECKING["last"] < 300:
        return
    CHECKING["last"] = time.time()
    try:
        token, me = gmail_access_token(), os.environ.get("GMAIL_ADDRESS", "").lower()
    except Exception:
        return
    updates = {}
    for e in sent_log():
        if not e.get("thread") or e.get("replied") or e.get("bounced") or \
                time.time() - time.mktime(time.strptime(e["at"], "%Y-%m-%d %H:%M")) > 45 * 86400:
            continue
        try:
            thread = json.load(urllib.request.urlopen(urllib.request.Request(
                f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{e['thread']}?format=metadata"
                "&metadataHeaders=From", headers={"Authorization": f"Bearer {token}"}), timeout=20))
        except urllib.error.HTTPError as err:
            if err.code == 403:  # connected before tracking existed: token lacks the read-headers permission
                CHECKING["reconnect"] = True
                return
            continue
        except Exception:
            continue
        CHECKING["reconnect"] = False
        for msg in thread.get("messages", []):
            sender = next((h["value"] for h in msg.get("payload", {}).get("headers", []) if h["name"] == "From"), "")
            at = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(msg.get("internalDate", 0)) / 1000))
            if re.search(r"mailer-daemon|postmaster", sender, re.I):
                updates[e["id"]] = {"bounced": at}
            elif me not in sender.lower():
                updates[e["id"]] = {"replied": at}
    if updates:
        with LOCK:
            log = sent_log()
            for e in log:
                e.update(updates.get(e.get("id"), {}))
            save_sent(log)


def run_task(fn, *args):
    """Long AI work (30-120s) runs in a thread; the browser polls /api/tasks/<id> (proxies time out long requests)."""
    task_id = secrets.token_hex(8)
    TASKS[task_id] = {"status": "pending"}

    def work():
        try:
            TASKS[task_id] = {"status": "done", **fn(*args)}
        except Exception as e:
            TASKS[task_id] = {"status": "error", "error": str(e)[:300]}
    threading.Thread(target=work, daemon=True).start()
    return {"task": task_id}


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
        lines.append(f"{key}={value}" if " " not in value else f'{key}="{value}"')
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
        if iid == "gmail":
            if not env.get("GMAIL_REFRESH_TOKEN"):
                return False, "Client saved -- now click Connect Gmail"
            gmail_access_token()
            return True, f"Signed in as {env.get('GMAIL_ADDRESS', '')} -- ready to send"
        if iid == "email":
            smtp_open().quit()
            return True, f"Signed in to your mailbox as {env['SMTP_USER']}"
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
    # own process group, so Stop also kills its browser and claude children
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "maps_leads.py"), *args], cwd=HERE, env=env,
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    RUNNING.update(proc=proc, stopped=False)

    def wait():
        code = proc.wait()
        log.close()
        status = "stopped" if RUNNING["stopped"] else "done" if code == 0 else "failed"
        meta.update(status=status, exit=code, ended=time.strftime("%Y-%m-%d %H:%M"),
                    results=os.path.basename(out) if os.path.exists(out) else None)
        save_meta(meta)
        RUNNING.update(id=None, proc=None)

    threading.Thread(target=wait, daemon=True).start()
    return meta


def stop_job(job_id):
    proc = RUNNING["proc"]
    if RUNNING["id"] != job_id or not proc:
        return False
    RUNNING["stopped"] = True
    try:
        os.killpg(proc.pid, signal.SIGTERM) if hasattr(os, "killpg") else proc.terminate()
    except ProcessLookupError:
        pass
    return True


def ai_settings():
    return {"provider": "claude" if m.use_claude() else "gemini", "model": os.environ.get("CLAUDE_MODEL", ""),
            "models": AI_MODELS["claude"], "claude_installed": bool(shutil.which("claude")),
            "gemini_connected": bool(os.environ.get("GEMINI_API_KEY"))}


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


def save_screens(shots, tag):
    """data:image/...;base64 strings from the browser -> files in data/screens/<folder>/ (max 8)."""
    folder = time.strftime("%Y%m%d-%H%M%S-") + re.sub(r"\W+", "", tag)[:30] + secrets.token_hex(3)
    paths = []
    for shot in [x for x in shots or [] if isinstance(x, str)][:8]:
        kind = re.match(r"data:image/(png|jpeg);base64,", shot)
        if kind:
            os.makedirs(os.path.join(HERE, "data", "screens", folder), exist_ok=True)
            paths.append(os.path.join(HERE, "data", "screens", folder, f"{len(paths) + 1}.{'png' if kind[1] == 'png' else 'jpg'}"))
            with open(paths[-1], "wb") as f:
                f.write(base64.b64decode(shot[kind.end():]))
    return paths


def as_text(item):
    return item if isinstance(item, str) else " -- ".join(str(v) for v in item.values()) if isinstance(item, dict) \
        else str(item)


def chat_from_screens(paths, platform, name, notes, email):
    """Screenshots of their page -> AI reads the person -> Sales Brain principles -> opener. Saved like a --person
    report, so it shows up in Prospect Chat with coaching for every reply."""
    profile = m.read_screenshots(paths, notes)
    if not profile:
        raise RuntimeError("The AI didn't answer -- check Settings → AI engine (Test), then try again")
    if profile.get("error"):
        raise RuntimeError(f"The AI couldn't use these screenshots: {profile['error']}")
    if profile.get("kind") == "conversation":
        return chat_from_conversation(profile, platform, name, notes, email)
    name = name or str(profile.get("name") or "").strip() or "Unknown"
    city = str(profile.get("city") or "").strip()
    email = email or (str(profile.get("email") or "") if EMAIL.fullmatch(str(profile.get("email") or "")) else "")
    facts = [f"{k}: {profile[k]}" for k in ("headline", "business", "city", "website", "phone", "email") if profile.get(k)]
    facts += [as_text(f) for f in profile.get("facts") or []]
    facts += [f"Visible gap: {as_text(g)}" for g in profile.get("problems") or []]
    facts += [f"Possible opener: {as_text(h)}" for h in profile.get("hooks") or []]
    if profile.get("who_they_are"):
        facts.append(f"Who they are: {profile['who_they_are']}")
    if notes:
        facts.append(f"My notes: {notes}")
    slug = re.sub(r"\W+", "-", name).strip("-") or "Unknown"
    with LOCK:  # the chat remembers where you met them + their email, whichever path writes the report
        chat = load_chat(slug)
        chat.update(platform=platform, **({"email": email} if email else {}))
        save_chat(slug, chat)
    if city and re.fullmatch(r"[^,]+,\s*[A-Za-z]{2}", city):
        # full research, same as the Research page: Maps, web sweep, Zillow, every website + page source audit,
        # AI review/visibility, Sales Brain -> first messages. The report it writes becomes this chat.
        one_line = lambda v: " ".join(str(v or "").split())[:390].lstrip("-")
        about = "; ".join([str(profile.get("headline") or "")] + [as_text(f) for f in profile.get("facts") or []])
        try:
            job = start_job("person", {"name": name, "city": city, "brokerage": one_line(profile.get("business")),
                                       "sites": " ".join(re.findall(r"(?:https?://)?[\w-]+(?:\.[\w-]+)+(?:/[^\s()]*)?",
                                                                   str(profile.get("website") or "")))[:390], "phone": one_line(profile.get("phone")),
                                       "address": one_line(profile.get("address")), "notes": one_line(about)})
            return {"slug": slug, "job": job["id"]}
        except (ValueError, RuntimeError):
            pass  # another job is running / odd field: fall back to the quick opener from the screenshots alone
    out = m.outreach(name, facts, f"{platform} DM")
    used = "\n".join(f"- {u.get('principle', '')}: {u.get('how', '')}"
                     + (f"\n    \"{u['quote']}\" -- {u.get('source', '')}" if u.get("quote") else "")
                     for u in out["principles_used"])
    report = (f"{name} | {city} | {time.ctime()}\n\nFACTS (read from their {platform} screenshots):\n"
              + "\n".join(f"- {f}" for f in facts) + "\n\nSALES BRAIN PRINCIPLES:\n"
              + ("\n".join(f"- {n}" for n in out["principles"]) or "- (Sales Brain not reached -- check Settings)")
              + f"\n\nMESSAGES:\nMESSAGE 1\n{out.get('message', '')}\n\nMESSAGE 2 (after they reply)\n"
              f"{out.get('followup', '')}\n\nPRINCIPLES USED:\n{used}\n")
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, f"{slug}-{time.strftime('%Y-%m-%d-%H%M')}.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    return {"slug": slug}


def chat_from_conversation(convo, platform, name, notes, email):
    """Screenshots of an existing DM thread -> a chat with those messages, coached on their latest one."""
    name = name or str(convo.get("name") or "").strip() or "Unknown"
    slug = re.sub(r"\W+", "-", name).strip("-") or "Unknown"
    goal = notes or str(convo.get("goal") or "")
    report = (f"{name} | | {time.ctime()}\n\nFACTS (from a {convo.get('platform') or platform} conversation "
              f"screenshot):\n- {convo.get('context', '')}\n- My goal: {goal}\n\nSALES BRAIN PRINCIPLES:\n")
    os.makedirs(REPORTS, exist_ok=True)
    with open(os.path.join(REPORTS, f"{slug}-{time.strftime('%Y-%m-%d-%H%M')}.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    at = time.strftime("%Y-%m-%d %H:%M")
    turns = [{"role": "me" if str(x.get("from")).lower() == "me" else "them", "text": str(x.get("text", ""))[:4000],
              "at": at} for x in convo.get("messages") or [] if isinstance(x, dict) and x.get("text")]
    last_them = max((i for i, t in enumerate(turns) if t["role"] == "them"), default=None)
    if last_them is not None:  # coach the newest message from them, same as pasting it in
        turns[last_them]["coach"] = coach(name, report, turns[:last_them], turns[last_them]["text"],
                                          convo.get("platform") or platform, goal=goal)
    with LOCK:
        chat = load_chat(slug)
        chat.update(platform=convo.get("platform") or platform, goal=goal, **({"email": email} if email else {}))
        chat["turns"] = chat["turns"] + turns
        save_chat(slug, chat)
    return {"slug": slug}


def lead_row(file, name):
    path = os.path.join(RESULTS, os.path.basename(file))
    rows = list(csv.DictReader(open(path, encoding="utf-8"))) if os.path.exists(path) else []
    return next((r for r in rows if r.get("Business Name") == name), None)


def lead_email(row):
    """Everything the tool proved about this lead -> Sales Brain -> an email draft."""
    keep = ("Brokerage", "Address", "Website URL", "Sales (12 mo)", "Zillow Reviews", "Avg Price", "Expansion",
            "Zillow Specialties", "Other Issues", "AI Review", "AI Visibility")
    facts = [f"{k}: {row[k][:500]}" for k in keep if (row.get(k) or "").strip()]
    facts += [f"Website check {k}: {row[k]}" for k in ("Schema", "Geo Pin", "Schema Data", "NAP", "H1")
              if (row.get(k) or "").startswith(("FAIL", "PARTIAL"))]
    return m.outreach(row["Business Name"], facts, "email", os.environ.get("SMTP_FROM_NAME", ""))


def coach(name, report, turns, their_message, platform="LinkedIn", images=(), note="", goal=""):
    """What they said -> what it means -> next goal -> reply, grounded in the report + Sales Brain."""
    history = [("agent" if t["role"] == "me" else "prospect", t["text"] or "(sent a screenshot)") for t in turns]
    facts = report.split("SALES BRAIN PRINCIPLES:")[0][-6000:]
    principles = m.sales_brain(
        f"I'm in a {platform} conversation with {name}. "
        + (f"My goal: {goal}. " if goal else "They're a real estate agent/broker I want as a client for my service "
           "(fixing how their website and listings are read by Google and AI assistants). ") + "They just replied: "
        f"\"{their_message or '(a screenshot)'}\". " + (f"My goal: {note}. " if note else "")
        + "What is really going on in their reply and what should I say next?", history)
    convo = "\n".join(f"{'ME' if r == 'agent' else name.upper()}: {t}" for r, t in history)
    answer = m.gemini(
        f"You coach me in a {platform} conversation with {name}." + (f" MY GOAL: {goal}." if goal else "")
        + "\n\nWHAT I KNOW ABOUT THEM (checked facts):\n"
        f"{facts}\n\nCONVERSATION SO FAR:\n{convo}\n{name.upper()} (latest): {their_message or '(see screenshots)'}\n\n"
        + (f"I attached {len(images)} screenshot(s) (their reply, a post, their profile...): read them fully and use "
           "what they show.\n" if images else "")
        + (f"MY NOTE TO YOU (what I want -- do exactly this; the reply field is the message to send): {note}\n\n"
           if note else "") +
        "MY SALES TRAINING (principles + exact PASSAGES from my own books/videos):\n" + "\n".join(principles) + "\n\n"
        "Return JSON with keys: said (their message in plain words, 1 sentence), meaning (what's really going on: "
        "tone, interest level, what they want, any objection or buying signal), next_goal (the one thing my next "
        f"message should achieve), reply (the exact message to send, natural {platform} style, max 90 words, no "
        "jargon), why (which principle(s) you applied and how, 1-2 lines), watch_out (one thing NOT to say now), "
        "used (a list: " + m.QUOTE_RULE + "). "
        "Rules: answer any direct question honestly first; if they clearly say no, respect it and leave the door "
        "open; use ONLY the checked facts, never invent numbers/results/urgency, never promise rankings in "
        "Google or ChatGPT; don't state industry trends or how Google/AI choose who to recommend as facts (say "
        "what you found, not why it happens); don't pitch price until they show interest. 'said' must be a plain "
        "paraphrase, not a copy of their words.", as_json=True, images=images)
    try:
        out = json.loads(answer)
    except (ValueError, TypeError):
        out = {"said": "", "meaning": "", "next_goal": "", "reply": answer or "(AI unavailable, try again)",
               "why": "", "watch_out": ""}
    out["principles"] = m.brain_names(principles)
    out["used"] = m.keep_real_quotes(out.get("used"), principles)
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
            "connected": {**{i["id"]: connected(i) for i in INTEGRATIONS},
                          **({"gemini": True} if m.use_claude() else {})},  # Claude does the AI work instead
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

    def _body(self, limit=50000):
        length = int(self.headers.get("Content-Length", 0))
        if length > limit:
            raise ValueError("request too large")
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
        if match := re.fullmatch(r"/api/t/([\w-]{8,40})\.gif", path):
            log_open(match[1], self.headers)
            return self._send(base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"), kind="image/gif")
        if path == "/api/gmail/callback":
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            born = OAUTH_STATES.pop(q.get("state", ""), 0)
            back = lambda result: self._send(b"", 302, headers=[("Location", f"{APP_URL}/#/settings?gmail={result}")])
            if not born or time.time() - born > 900 or not q.get("code"):
                return back("failed")
            try:
                tokens = google_token({"grant_type": "authorization_code", "code": q["code"],
                                       "redirect_uri": f"{APP_URL}/api/gmail/callback"})
                claims = json.loads(base64.urlsafe_b64decode(tokens["id_token"].split(".")[1] + "=="))
                set_env("GMAIL_REFRESH_TOKEN", tokens["refresh_token"])
                set_env("GMAIL_ADDRESS", claims["email"])
                if claims.get("name") and not os.environ.get("SMTP_FROM_NAME"):
                    set_env("SMTP_FROM_NAME", re.sub(r"[^\w .,'&-]", "", claims["name"])[:60])
                return back("ok")
            except Exception:
                return back("failed")
        if not self._user():
            return self._send({"error": "sign in required"}, 401)
        if path == "/api/dashboard":
            return self._send(dashboard())
        if path == "/api/settings":
            return self._send([{**i, "values": {f: mask(os.environ.get(f, "")) if f not in FIELD_PATTERNS
                                                else os.environ.get(f, "") for f in i["fields"]},
                                "connected": connected(i), "account": os.environ.get("GMAIL_ADDRESS", "")
                                if i["id"] == "gmail" and os.environ.get("GMAIL_REFRESH_TOKEN") else ""}
                               for i in INTEGRATIONS])
        if path == "/api/ai":
            return self._send(ai_settings())
        if match := re.fullmatch(r"/api/tasks/(\w+)", path):
            return self._send(TASKS.get(match[1]) or {"status": "error", "error": "unknown task (server restarted?)"})
        if path == "/api/gmail/connect":
            if not (os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")):
                return self._send({"error": "save the Google Client ID and Secret first"}, 400)
            state = secrets.token_urlsafe(24)
            OAUTH_STATES[state] = time.time()
            return self._send({"url": "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
                "client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": f"{APP_URL}/api/gmail/callback",
                "response_type": "code", "access_type": "offline", "prompt": "consent", "state": state,
                "scope": "openid email profile https://www.googleapis.com/auth/gmail.send "
                         "https://www.googleapis.com/auth/gmail.metadata"})})
        if match := re.fullmatch(r"/api/screens/([\w-]+)/(\d+\.(?:jpg|png))", path):
            file = os.path.join(HERE, "data", "screens", match[1], match[2])
            return self._send(open(file, "rb").read(), kind="image/" + ("png" if file.endswith("png") else "jpeg")) \
                if os.path.exists(file) else self._send({"error": "not found"}, 404)
        if path == "/api/sent":
            threading.Thread(target=check_replies, daemon=True).start()  # results show on the next refresh
            return self._send({"sent": sent_log()[-500:], "reconnect": CHECKING.get("reconnect", False),
                               "gmail": bool(os.environ.get("GMAIL_REFRESH_TOKEN"))})
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
            files = sorted((f for f in os.listdir(REPORTS) if f.endswith(".txt")),  # newest first
                           key=lambda f: os.path.getmtime(os.path.join(REPORTS, f)), reverse=True) \
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
                for f in integ["fields"] + integ.get("extra", []):
                    set_env(f, None)
                return self._send({"ok": True})
            values = {f: str(self._body().get(f, "")).strip() for f in integ["fields"]}
            values = {f: v if f in ("SMTP_FROM_NAME",) else v.replace(" ", "") for f, v in values.items()}  # app passwords come spaced
            for f, v in values.items():
                if v and not re.fullmatch(FIELD_PATTERNS.get(f, r"[A-Za-z0-9_.\-:/+=]{8,300}"), v):
                    return self._send({"error": f"{f} doesn't look right"}, 400)
            for f, v in values.items():
                if v:
                    set_env(f, v)
            return self._send({"ok": True})
        if path == "/api/ai":  # which engine does all AI work: Gemini (API key) or Claude (subscription CLI)
            b = self._body()
            provider, model = b.get("provider"), str(b.get("model") or "")
            if provider not in ("gemini", "claude") or model not in AI_MODELS["claude"]:
                return self._send({"error": "unknown engine or model"}, 400)
            if provider == "claude" and not shutil.which("claude"):
                return self._send({"error": "Claude Code isn't installed on the server"}, 400)
            set_env("AI_PROVIDER", provider if provider == "claude" else None)
            set_env("CLAUDE_MODEL", model or None)
            return self._send(ai_settings())
        if path == "/api/ai/test":
            engine = "Claude" if m.use_claude() else "Gemini"
            answer = m.gemini("Reply with exactly the word: pong")
            return self._send({"ok": "pong" in answer.lower(),
                               "message": f"{engine} answered" if "pong" in answer.lower()
                               else f"{engine} didn't answer -- check the server login / key, or usage limits"})
        if path == "/api/chat/new":  # screenshots of their LinkedIn/Instagram/Facebook page -> a new chat
            try:
                b = self._body(12_000_000)
            except ValueError:
                return self._send({"error": "screenshots too large -- send fewer"}, 400)
            platform = b.get("platform") if b.get("platform") in ("LinkedIn", "Instagram", "Facebook", "Other") else "Other"
            try:
                name, notes = clean(b.get("name")), str(b.get("notes") or "")[:2000]
                email = clean(b.get("email"))
            except ValueError as e:
                return self._send({"error": str(e)}, 400)
            if email and not EMAIL.fullmatch(email):
                return self._send({"error": "that email doesn't look right"}, 400)
            paths = save_screens(b.get("images"), "new")
            if not paths:
                return self._send({"error": "add at least one screenshot (PNG or JPG)"}, 400)
            return self._send(run_task(chat_from_screens, paths, platform, name, notes, email))
        if path == "/api/email/draft":
            b = self._body()
            row = lead_row(str(b.get("file", "")), str(b.get("name", "")))
            return self._send(run_task(lead_email, row)) if row else self._send({"error": "lead not found"}, 404)
        if path == "/api/email/send":
            b = self._body()
            to, subject, text = str(b.get("to", "")).strip(), str(b.get("subject", "")).strip(), str(b.get("body", ""))
            if not EMAIL.fullmatch(to) or "\n" in subject or not (0 < len(subject) <= 200) or not (0 < len(text) <= 8000):
                return self._send({"error": "check the To address, subject and message"}, 400)
            if not email_ready():
                return self._send({"error": "connect Gmail (or another email) in Settings first"}, 400)
            track = secrets.token_urlsafe(12)
            try:
                thread = send_email(to, subject, text, track)
            except Exception as e:
                return self._send({"error": f"your mail server refused it: {str(e)[:160]}"}, 502)
            slug = str(b.get("slug") or "")
            log_sent({"id": track, "thread": thread, "opens": [], "to": to, "subject": subject,
                      "at": time.strftime("%Y-%m-%d %H:%M"), "slug": slug,
                      "lead": str(b.get("lead") or "")[:200]})
            if slug in people():
                with LOCK:
                    chat = load_chat(slug)
                    chat["email"] = to
                    chat["turns"].append({"role": "me", "text": f"(email) {subject}\n\n{text}",
                                          "at": time.strftime("%Y-%m-%d %H:%M")})
                    save_chat(slug, chat)
            return self._send({"ok": True})
        if match := re.fullmatch(r"/api/jobs/([\w-]+)/stop", path):
            return self._send({"ok": True}) if stop_job(match[1]) else self._send({"error": "that job isn't running"}, 400)
        if match := re.fullmatch(r"/api/jobs/(hunt|zips|person|audit|zillow)", path):
            try:
                return self._send(start_job(match[1], self._body()))
            except (ValueError, RuntimeError) as e:
                return self._send({"error": str(e)}, 400)
        if (match := re.fullmatch(r"/api/chat/([\w-]+)/(theirs|mine)", path)) and match[1] in people():
            try:
                b = self._body(12_000_000)
            except ValueError:
                return self._send({"error": "screenshots too large -- send fewer"}, 400)
            text, note = str(b.get("text", "")).strip()[:4000], str(b.get("note", "")).strip()[:2000]
            paths = save_screens(b.get("images"), match[1]) if match[2] == "theirs" else []
            if not (text or paths):
                return self._send({"error": "type their reply or add a screenshot"}, 400)
            slug, (name, report_path) = match[1], people()[match[1]]
            turn = {"role": "me" if match[2] == "mine" else "them", "text": text,
                    "at": time.strftime("%Y-%m-%d %H:%M")}
            if paths:
                turn["images"] = [os.path.relpath(x, os.path.join(HERE, "data", "screens")).replace(os.sep, "/") for x in paths]
            if note:
                turn["note"] = note
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
                    result = coach(name, open(report_path, encoding="utf-8").read(), history, text,
                                   chat.get("platform", "LinkedIn"), paths, note, chat.get("goal", ""))
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
