"""Boutique real-estate lead finder: top 20 "Real Estate Agency in <ZIP>" on Google Maps,
national-chain offices skipped (unless a named local team), emails pulled from their sites -> CSV.

Usage:
  $env:SNOV_CLIENT_ID="..."; $env:SNOV_CLIENT_SECRET="..."   (optional, snov.io; used only when the site has no email)
  $env:PAGESPEED_API_KEY="..."       (optional, free key, no billing; adds the mobile speed grade)
  $env:SALES_BRAIN_API_KEY="lsc_live_..."   (optional, Legacy Sales Coach key; Pitch uses your sales training)
  $env:GEMINI_API_KEY="..."          (optional, aistudio.google.com key; adds AI Review of the page source,
                                      AI Visibility and a drafted Pitch)
  Keys can also live in a .env file next to this script (KEY=value per line) -- that's how the VPS runs.
  python maps_leads.py 01960 01970 01945     -> leads.csv (open/import in Google Sheets)
  python maps_leads.py --audit source.html "200 Lynnfield St, Peabody, MA 01960, United States" "+19783946736"
      -> grades a page source you saved yourself (Ctrl+U, then Ctrl+S) when a site blocks the checker
  python maps_leads.py --zillow Peabody, MA
      -> (on your PC) opens Zillow's agent list; open an agent, press Enter to copy them; 'done' audits them all
  python maps_leads.py --person --name "Petar Mandic" --city "Louisville, KY" --brokerage Semonin
                       [--sites "petarmandic.com petarmandic.semonin.com"] [--phone ..] [--address ".."] [--notes ".."]
      -> everything for one LinkedIn connection: Maps + Zillow + sites + AI + Sales Brain -> 2 messages
  python maps_leads.py --hunt [--top 10] [--min-price 400000] [--min-sales 40] [--min-reviews 50]
                              [--min-volume 20000000] [--per-city 25] [--teams]
      -> hot ZIPs (Realtor.com 2026) -> producers (Zillow via Apify, else Google Maps reviews) -> full gap audit
  python maps_leads.py --list agents.txt    -> audits a list you made: Name | website | phone | City, ST
  python maps_leads.py --zillow-db Peabody, MA [--min-reviews 10] [--min-sales 5] [--max 50]
      -> busy Zillow agents via Apify (APIFY_TOKEN, ~$0.003/agent) + the full audit; adds Zillow columns
  python maps_leads.py --audit https://site.com "address" "phone" ["Business Name" -> adds the AI columns]
      -> grades the live site now; every --audit run is saved in reports/ (dated) for before/after proof
"""
import csv, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
JUNK = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "example.com", "sentry", "wixpress", "domain.com")
ROLE_INBOXES = {"info", "sales", "admin", "contact", "contactus", "hello", "hi", "office", "support", "help", "team",
                "mail", "email", "enquiries", "enquiry", "inquiries", "inquiry", "noreply", "no-reply", "donotreply",
                "do-not-reply", "webmaster", "marketing", "service", "services", "customerservice", "billing",
                "accounts", "accounting", "hr", "jobs", "careers", "press", "media", "reception", "frontdesk",
                "listings", "leads", "privacy", "legal", "abuse", "postmaster", "hostmaster", "general", "main",
                "realestate", "homes", "properties", "rentals", "management", "operations", "notifications",
                "publicrelations", "pr", "partnerships", "partners", "events", "community", "feedback", "news"}
PLACEHOLDER_LOCALS = {"your", "youremail", "yourname", "you", "name", "firstname", "first.last", "user", "username",
                      "test", "example", "sample", "demo", "john", "johndoe", "john.doe", "jane", "janedoe", "someone"}
PLACEHOLDER_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "email.com", "yourdomain.com",
                       "yoursite.com", "yourwebsite.com", "company.com", "mysite.com", "test.com", "website.com",
                       "sentry.io", "wixpress.com", "sentry-next.wixpress.com"}
CONTACT_PATHS = ("", "contact", "contact-us", "about", "about-us")
CHAINS = ("coldwell banker", "re/max", "remax", "keller williams", "century 21", "sotheby", "compass",
          "berkshire hathaway", "exp realty", "redfin", "better homes", "douglas elliman", "william raveis", "era ")
SOCIAL = re.compile(r"https?://(?:www\.|m\.)?(instagram|facebook|linkedin|tiktok|youtube|twitter|x)\.com/([A-Za-z0-9_.\-/@]+)")
SOCIAL_SKIP = {"sharer", "sharer.php", "share", "share.php", "intent", "tr", "p", "reel", "watch", "embed", "plugins",
               "dialog", "home.php", "shareArticle", "sharearticle", "hashtag", "explore", "legal", "policies", "privacy",
               # website-builder / IDX vendors whose own profiles sit in their clients' footers
               "brivityplatform", "brivity", "wix", "squarespace", "wordpress", "godaddy", "kvcore", "insiderealestate",
               "boomtownroi", "placester", "realgeeks", "luxurypresence", "agentfire", "lofty", "chime.me", "sierrainteractive",
               # the directory site's own accounts in its header/footer
               "zillow", "zillowgroup", "company", "zillow-group"}
SOCIAL_NETS = ("instagram", "facebook", "linkedin", "tiktok", "youtube", "x")
PHONE = re.compile(r"(?:\+?1[\s.-]?)?\(?\b\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}\b")
AI_BOTS = ("GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "CCBot")
STREET_ABBR = {"street": "st", "road": "rd", "avenue": "ave", "drive": "dr", "lane": "ln", "boulevard": "blvd",
               "court": "ct", "place": "pl", "highway": "hwy", "parkway": "pkwy", "square": "sq", "terrace": "ter",
               "suite": "ste", "north": "n", "south": "s", "east": "e", "west": "w"}
GRADE_COLS = ("Schema", "Geo Pin", "Schema Data", "NAP", "H1", "Speed", "Other Issues")
_gemini_exhausted = set()
GEMINI_FALLBACKS = ("gemini-3.8-flash", "gemini-flash-lite-latest")
GENERIC_NAME_WORDS = {"real", "estate", "realty", "realtor", "realtors", "group", "team", "properties", "property",
                      "homes", "home", "agent", "agents", "agency", "associates", "brokerage", "broker", "company",
                      "partners", "sell", "buys", "buyers", "house", "houses", "north", "shore", "with", "from"}
DEAD_SITE = [  # (pattern in final URL or page, what the visitor actually gets)
    (r"suspendedpage\.cgi|account (has been )?suspended|this account is suspended", "hosting account SUSPENDED"),
    (r"domain (is )?(parked|for sale)|buy this domain|this domain may be for sale|sedoparking|parkingcrew",
     "domain parked / for sale"),
    (r"site (is )?under construction|coming soon</title>", "site under construction"),
    (r"<title>\s*(index of /|default web site page|welcome to nginx|apache2 \w+ default page)", "blank server page"),
]
BUSINESS_TYPES = {"RealEstateAgent", "LocalBusiness", "ProfessionalService", "Organization"}
BLOCK_PAGES = ("captcha", "request is blocked", "access denied", "attention required", "just a moment",
               "does not support embedding its pages", "contact the site owner for access", "http 403",
               "challenges.cloudflare.com")
AI_CRAWLER_UA = {"User-Agent": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; OAI-SearchBot/1.0; +https://openai.com/searchbot)"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}


def is_chain_office(name):
    n = name.lower()
    return any(c in n for c in CHAINS) and not any(t in n for t in ("team", "group"))


def search_places(query, limit=20):
    """Opens Google Maps in Chrome, reads the top `limit` results (no API key needed)."""
    from urllib.parse import quote_plus
    from playwright.sync_api import sync_playwright
    out = []
    with sync_playwright() as pw:
        # persistent profile so Google's cookie-consent answer is remembered between runs
        browser = pw.chromium.launch_persistent_context("browser-profile", locale="en-US",
                                                        headless=os.environ.get("HEADLESS") == "1")  # 1 on a VPS
        page = browser.new_page()
        page.goto(f"https://www.google.com/maps/search/{quote_plus(query)}", timeout=60000)
        if "consent.google" in page.url:
            page.click("button:has-text('Accept all')")
            page.wait_for_url("**/maps/**", timeout=30000)
        feed = page.locator("div[role=feed]")
        feed.wait_for(timeout=30000)
        for _ in range(15):  # scroll the results list until we have enough
            if page.locator("a.hfpxzc").count() >= limit:
                break
            feed.evaluate("el => el.scrollBy(0, 3000)")
            page.wait_for_timeout(1500)
        links = page.locator("a.hfpxzc")
        for i in range(min(limit, links.count())):
            name = links.nth(i).get_attribute("aria-label") or ""
            links.nth(i).click()
            try:  # wait for this business's panel, then for its detail rows to render
                page.wait_for_selector(f"h1:has-text({json.dumps(name)})", timeout=10000)
                page.wait_for_selector("button[data-item-id=address], a[data-item-id=authority]", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(800)
            site = page.locator("a[data-item-id=authority]")
            phone = page.locator("button[data-item-id^='phone:tel:']")
            addr = page.locator("button[data-item-id=address]")
            pin = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", page.url)  # office pin from the place URL
            stars = page.locator("div.F7nice")  # "5.0" (+ "(120)" only in a signed-in view; bots get no count)
            rating = re.search(r"(\d\.\d)(?:\D+\(?([\d,]+)\)?)?", stars.first.inner_text()) if stars.count() else None
            out.append({
                "google": {"Google Rating": rating[1] if rating else "",
                           "Google Reviews": int(rating[2].replace(",", "")) if rating and rating[2] else None},
                "displayName": {"text": name},
                # no address = service-area business, URL coords are just the map view, not an office
                "pin": (float(pin[1]), float(pin[2])) if pin and addr.count() else None,
                "websiteUri": site.first.get_attribute("href") if site.count() else "",
                "nationalPhoneNumber": phone.first.get_attribute("data-item-id").removeprefix("phone:tel:") if phone.count() else "",
                "formattedAddress": (addr.first.get_attribute("aria-label") or "").removeprefix("Address: ").strip() if addr.count() else "",
            })
            print(f"  {i + 1}. {name}")
        browser.close()
    return out


def fetch_page(url, tries=3, headers=UA):
    """(html, final url after redirects); retries with backoff because small-business hosts flake."""
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
                return r.read(3_000_000).decode("utf-8", "ignore"), r.geturl()
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 503):  # a bot wall (Cloudflare etc.): return its page so it gets named, not "down"
                return e.read(200_000).decode("utf-8", "ignore") or f"HTTP {e.code}", e.url
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return "", url


def fetch(url):
    return fetch_page(url)[0]


def is_personal_email(email):
    """False for shared inboxes (info@, sales@...), template placeholders and tracker/hash addresses."""
    local, _, domain = email.lower().partition("@")
    base = re.sub(r"[._-]?\d+$", "", local)  # info2@ / sales-1@ are still role inboxes
    return not (
        any(j in email.lower() for j in JUNK)
        or base in ROLE_INBOXES or base in PLACEHOLDER_LOCALS or domain in PLACEHOLDER_DOMAINS
        or re.fullmatch(r"[0-9a-f]{16,}", local)  # sentry/wix style hashes
        or domain.endswith((".png", ".jpg", ".js", ".css"))
    )


def extract_emails(html):
    return {e for e in (m.lower().rstrip(".") for m in EMAIL.findall(html)) if is_personal_email(e)}


_mx_cache = {}


def has_mail_server(domain):
    """Real inbox domains publish MX records; typo'd or made-up domains don't (checked over DNS-over-HTTPS)."""
    if domain not in _mx_cache:
        try:
            url = "https://dns.google/resolve?" + urlencode({"name": domain, "type": "MX"})
            answer = json.load(urllib.request.urlopen(url, timeout=15))
            _mx_cache[domain] = answer.get("Status") == 0 and any(a.get("type") == 15 for a in answer.get("Answer", []))
        except Exception:
            _mx_cache[domain] = True  # DNS lookup failed: don't throw away a possibly good email
    return _mx_cache[domain]


def extract_socials(html):
    """First business-profile link per network; skips share buttons, posts, tracking pixels."""
    found = {}
    for net, handle in SOCIAL.findall(html):
        net = "x" if net == "twitter" else net
        if net not in found and handle.split("/")[0].lower() not in SOCIAL_SKIP:
            found[net] = f"https://www.{net}.com/{handle.rstrip('/')}"
    return found


def phones_in(text):
    return {re.sub(r"\D", "", m)[-10:] for m in PHONE.findall(text)}


def grade_schema(static_nodes, js_nodes, js_broken=False):
    static_agents = [n for n in static_nodes if "RealEstateAgent" in types_of(n)]
    js_agents = [n for n in js_nodes if "RealEstateAgent" in types_of(n)]
    if any("address" in n for n in static_agents):
        return "PASS: RealEstateAgent schema with address in the HTML"
    if js_agents:
        where = "only added by JavaScript -- crawlers that don't run JS (most AI bots) never see it"
        if js_broken:
            return f"FAIL: RealEstateAgent schema is {where}, and that script has a syntax error so it never runs at all"
        return f"PARTIAL: RealEstateAgent schema is {where}"
    if static_agents:
        return (f"PARTIAL: RealEstateAgent only as a person ({static_agents[0].get('name', '?')}) "
                "with no business address")
    found = sorted({t for n in static_nodes for t in types_of(n) if isinstance(t, str)})
    if found:
        return f"FAIL: no RealEstateAgent schema (only {', '.join(found[:6])})"
    return "FAIL: no JSON-LD schema at all"


def grade_geo(business, pin):
    pin_txt = f" (office pin {pin[0]:.4f}, {pin[1]:.4f})" if pin else ""
    for where, node in business:
        geo = node.get("geo") if isinstance(node.get("geo"), dict) else {}
        try:
            lat, lng = float(geo["latitude"]), float(geo["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if pin and (abs(lat - pin[0]) > 0.005 or abs(lng - pin[1]) > 0.005):  # ~500 m
            return f"FAIL: business coords {lat}, {lng} don't match Google pin{pin_txt}"
        return f"{'PARTIAL' if where else 'PASS'}: coords {lat}, {lng}{where}"
    return "FAIL: no latitude/longitude on the business schema" + pin_txt


def grade_schema_data(business, maps_address, maps_phone):
    """Does the address/phone the business schema tells machines match Google Maps? (Beverly-vs-Peabody trap)"""
    if not business:
        return ""
    with_addr = [n for _, n in business if isinstance(n.get("address"), dict)]
    if not with_addr:
        return "FAIL: business schema has no address"
    addr = with_addr[0]["address"]
    street, city = str(addr.get("streetAddress", "")), str(addr.get("addressLocality", ""))
    parts = [p.strip() for p in maps_address.split(",")]
    maps_street, maps_city = (parts[0], parts[1]) if len(parts) > 2 else ("", "")
    conflicts = []
    if city and maps_city and city.strip().lower() != maps_city.lower():
        conflicts.append(f"schema city '{city}' vs Google '{maps_city}'")
    if street and maps_street and norm_street(street).split()[:2] != norm_street(maps_street).split()[:2]:
        conflicts.append(f"schema street '{street}' vs Google '{maps_street}'")
    phones = {re.sub(r"\D", "", str(n.get("telephone", "")))[-10:] for _, n in business} - {""}
    maps10 = re.sub(r"\D", "", maps_phone)[-10:]
    if len(phones) > 1:
        conflicts.append(f"schema lists {len(phones)} different phones ({', '.join(sorted(phones))})")
    elif maps10 and phones and maps10 not in phones:
        conflicts.append(f"schema phone {phones.pop()} vs Google {maps10}")
    if conflicts:
        return "FAIL: " + "; ".join(conflicts)
    same_as = any(n.get("sameAs") for _, n in business)
    return "PASS: schema address/phone match Google" + ("" if same_as else " (but no sameAs social links)")


class ScriptCollector(HTMLParser):
    """Collects <script> blocks exactly as a browser splits them (JSON-LD vs JavaScript)."""
    def __init__(self):
        super().__init__()
        self.scripts, self._cur = [], None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._cur = [dict(attrs).get("type", "").lower(), bool(dict(attrs).get("src")), []]

    def handle_data(self, data):
        if self._cur:
            self._cur[2].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._cur:
            self.scripts.append((self._cur[0], self._cur[1], "".join(self._cur[2])))
            self._cur = None


def types_of(node):
    t = node.get("@type", [])
    return set(t) if isinstance(t, list) else {t}


def walk(obj):
    if isinstance(obj, dict):
        if "@type" in obj:
            yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def json_objects_in_js(js):
    """Schema objects written inside JavaScript (addJsonLd({...}) etc.), parsed as JSON where possible."""
    dec, out = json.JSONDecoder(), []
    for m in re.finditer(r'\{\s*"@(?:context|type)"', js):
        try:
            out.append(dec.raw_decode(js, m.start())[0])
        except ValueError:
            pass
    return out


def js_syntax_errors(scripts):
    """Inline scripts that carry schema/analytics and don't even parse -> the browser skips the whole block."""
    node, broken = shutil.which("node"), []
    if not node:
        return broken
    for kind, has_src, code in scripts:
        if has_src or kind not in ("", "text/javascript", "application/javascript", "module"):
            continue
        what = [label for key, label in (("schema.org", "schema"), ("gtag(", "Google Analytics/Ads"),
                                         ("clarity", "Microsoft Clarity"), ("fbq(", "Facebook Pixel")) if key in code]
        if not what:
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(code)
        try:
            r = subprocess.run([node, "--check", f.name], capture_output=True, text=True, timeout=30)
            if r.returncode:
                err = next((l for l in r.stderr.splitlines() if "Error" in l), "syntax error")
                broken.append(f"{' + '.join(what)} script has a JavaScript {err.strip()} -- the whole block never runs")
        finally:
            os.unlink(f.name)
    return broken


def pagespeed(site):
    key = os.environ.get("PAGESPEED_API_KEY")
    if not key:
        return "CHECK: set PAGESPEED_API_KEY, or test by hand at pagespeed.web.dev"
    try:
        url = ("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?"
               + urlencode({"url": site, "strategy": "mobile", "category": "performance", "key": key}))
        result = json.load(urllib.request.urlopen(url, timeout=120))
        score = round(result["lighthouseResult"]["categories"]["performance"]["score"] * 100)
    except Exception as e:
        return f"CHECK: PageSpeed failed ({str(e)[:60]})"
    return f"{'PASS' if score >= 80 else 'PARTIAL' if score >= 50 else 'FAIL'}: mobile score {score}/100"


def norm_street(s):
    return " ".join(STREET_ABBR.get(w, w) for w in re.findall(r"[a-z0-9]+", s.lower()))


def grade_nap(text, maps_address, maps_phone):
    street = maps_address.split(",")[0].strip()
    m = re.match(r"(\d+[a-z]?)\s+(\w+)", street, re.I)
    if not m:
        return "CHECK: no street address on Google Maps"
    found = re.search(rf"\b{re.escape(m[1])}\s+{re.escape(m[2])}(?:\s+\w+)?", text, re.I)
    maps10 = re.sub(r"\D", "", maps_phone)[-10:]
    phone_note = "" if not maps10 or maps10 in phones_in(text) else f"; phone {maps10} not in page source"
    if not found:
        return f"FAIL: '{street}' not in page source{phone_note}"
    site_st, maps_st = found[0], " ".join(street.split()[:3])
    if norm_street(site_st) != norm_street(maps_st) or site_st.lower() != maps_st.lower():
        return f"PARTIAL: site says '{site_st}', Google says '{maps_st}'{phone_note}"
    return ("PARTIAL: address matches" + phone_note) if phone_note else f"PASS: '{site_st}' matches Google"


def grade_h1(html, city):
    h1s = [" ".join(re.sub(r"<[^>]+>", " ", h).split()) for h in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)]
    h1s = [h for h in h1s if h]
    if not h1s:
        return "FAIL: no <h1> heading"
    h1 = " | ".join(h1s)[:120]
    has_city = city and city.lower() in h1.lower()
    has_service = re.search(r"real estate|realt|homes?\b|houses?\b|broker|propert|agent", h1, re.I)
    if has_city and has_service:
        return f"PASS: h1 = {h1}"
    return f"{'PARTIAL' if has_city or has_service else 'FAIL'}: h1 = {h1} -- lacks {'service' if has_city else 'city' if has_service else 'city and service'}"


def audit_site(place, html=None):
    """Grades a homepage's source like 'View Page Source'. Pass `html` to grade a source you saved yourself."""
    site, grades = place.get("websiteUri", ""), dict.fromkeys(GRADE_COLS, "")
    manual = html is not None
    if not manual:
        if not site:
            grades["Other Issues"] = "no website on Google Maps"
            return grades
        # read it as ChatGPT's search crawler does: bot-protected sites (e.g. Lofty) whitelist crawlers but
        # show a browser-looking checker a challenge page, which would grade the wrong page
        html, site = fetch_page(site, headers=AI_CRAWLER_UA)
        if not html:
            grades["Other Issues"] = "website did not load"
            return grades
        dead = next((label for pattern, label in DEAD_SITE if re.search(pattern, site + " " + html[:5000], re.I)), "")
        if dead:  # grading a suspended/parked page would produce nonsense FAILs
            grades["Other Issues"] = f"WEBSITE DOWN: {dead} (visitors see this instead of the site: {site})"
            return grades
        if len(html) < 30000 and any(b in html.lower() for b in BLOCK_PAGES):  # bot-check page, not their site
            wall = "Cloudflare" if "cloudflare" in html.lower() else "a bot wall"
            grades["Other Issues"] = (f"BLOCKED by {wall}: automated visitors get a challenge page, not the site "
                                      "(AI crawlers may be turned away too -- confirm by hand); to grade it: "
                                      "open it, Ctrl+U, save, run --audit on the file")
            return grades
        host = urlparse(site).netloc.lower()
        os.makedirs("page-sources", exist_ok=True)
        with open(os.path.join("page-sources", host.removeprefix("www.") + ".html"), "w", encoding="utf-8") as f:
            f.write(html)

    address = place.get("formattedAddress", "")
    parts = [p.strip() for p in address.split(",")]
    city = parts[1] if len(parts) > 2 else ""
    collector = ScriptCollector()
    collector.feed(html)
    static_nodes, invalid_ld = [], 0
    for kind, _, code in collector.scripts:
        if kind == "application/ld+json":
            try:
                static_nodes += list(walk(json.loads(code)))
            except ValueError:
                invalid_ld += 1
    js_code = [code for kind, _, code in collector.scripts if kind != "application/ld+json" and "schema.org" in code]
    js_nodes = [n for code in js_code for obj in json_objects_in_js(code) for n in walk(obj)]
    broken = js_syntax_errors(collector.scripts)
    business = ([("", n) for n in static_nodes if types_of(n) & BUSINESS_TYPES]
                + [(" (JavaScript-only)", n) for n in js_nodes if types_of(n) & BUSINESS_TYPES])
    static_ld = " ".join(code for kind, _, code in collector.scripts if kind == "application/ld+json")
    text = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S | re.I))
    phone = place.get("nationalPhoneNumber", "")
    grades["Schema"] = grade_schema(static_nodes, js_nodes, any("schema" in b for b in broken))
    microdata = set(re.findall(r"itemtype=[\"']https?://schema\.org/(\w+)", html, re.I))
    if grades["Schema"].startswith("FAIL") and microdata & {"RealEstateAgent", "LocalBusiness"}:
        # older inline format (itemprop=...) -- Google reads it, so it's not "no schema"
        has_addr = bool(re.search(r"itemprop=[\"']streetAddress", html, re.I))
        grades["Schema"] = ("PARTIAL: RealEstateAgent schema exists as older microdata (itemprop), "
                            f"{'with' if has_addr else 'without'} an address -- no JSON-LD block")
    grades["Geo Pin"] = grade_geo(business, place.get("pin"))
    if grades["Geo Pin"].startswith("FAIL") and re.search(r"itemprop=[\"']latitude", html, re.I):
        grades["Geo Pin"] = "PARTIAL: coordinates only in microdata"
    grades["Schema Data"] = grade_schema_data(business, address, phone)
    grades["NAP"] = grade_nap(text + " " + static_ld, address, phone)
    grades["H1"] = grade_h1(html, city)
    grades["Speed"] = pagespeed(site) if site else ""

    issues, low = list(broken), html.lower()
    if invalid_ld:
        issues.append(f"{invalid_ld} JSON-LD block(s) are invalid JSON -- search engines ignore them")
    if len(text) < 600:
        issues.append(f"page built by JavaScript: only {len(text)} characters of text in the HTML, "
                      "AI crawlers see a near-empty page")
    if site and not site.startswith("https"):
        issues.append("no HTTPS")
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    if not title or not title.group(1).strip():
        issues.append("missing <title>")
    elif city and city.lower() not in title.group(1).lower():
        issues.append(f"<title> doesn't mention {city}")
    if not re.search(r"<meta[^>]+name=[\"']description[\"']", html, re.I):
        issues.append("missing meta description")
    if re.search(r"<meta[^>]+name=[\"']robots[\"'][^>]+noindex", html, re.I):
        issues.append("homepage set to noindex (hidden from search)")
    if not manual:
        robots = RobotFileParser()
        robots.parse(fetch(f"{urlparse(site).scheme}://{host}/robots.txt").splitlines())
        blocked = [bot for bot in AI_BOTS if not robots.can_fetch(bot, site)]
        if blocked:
            issues.append(f"robots.txt blocks AI crawlers: {', '.join(blocked)}")
    if "wp-content" in low and "yoast" not in low and "rank-math" not in low and "rankmath" not in low:
        issues.append("WordPress with no SEO plugin detected")
    grades["Other Issues"] = "; ".join(issues)
    grades["_html"] = html  # kept for the AI Review pass, never written to the sheet
    return grades


def find_contacts(site):
    # ponytail: homepage + a few common contact paths, no JS rendering; add Playwright if too many sites come back empty
    if not site:
        return [], {}
    base = site if site.endswith("/") else site + "/"
    emails, socials = set(), {}
    for path in CONTACT_PATHS:
        html = fetch(urljoin(base, path))
        emails |= extract_emails(html)
        socials = extract_socials(html) | socials  # keep earlier (homepage) links first
        if emails and socials:
            break
    return sorted(emails), socials


_snov_token = None


def snov_emails(site):
    """snov.io domain search, for agencies whose website shows only a contact form."""
    global _snov_token
    domain = urlparse(site).netloc.lower().removeprefix("www.")
    cid, secret = os.environ.get("SNOV_CLIENT_ID"), os.environ.get("SNOV_CLIENT_SECRET")
    if not (domain and cid and secret):
        return []
    try:
        if not _snov_token:  # ponytail: token lives 1h, fine for one run
            body = urlencode({"grant_type": "client_credentials", "client_id": cid, "client_secret": secret}).encode()
            _snov_token = json.load(urllib.request.urlopen("https://api.snov.io/v1/oauth/access_token", body, 20))["access_token"]
        auth = {"Authorization": f"Bearer {_snov_token}"}
        req = urllib.request.Request("https://api.snov.io/v2/domain-search/domain-emails/start",
                                     urlencode({"domain": domain}).encode(), auth)
        task = json.load(urllib.request.urlopen(req, timeout=20))
        task_hash = task.get("task_hash") or task.get("meta", {}).get("task_hash")
        for _ in range(20):  # results are async; poll until done
            time.sleep(3)
            req = urllib.request.Request(f"https://api.snov.io/v2/domain-search/domain-emails/result/{task_hash}", headers=auth)
            res = json.load(urllib.request.urlopen(req, timeout=20))
            if res.get("status") != "in_progress" and res.get("status") != "in progress":
                return [d["email"] for d in res.get("data", []) if d.get("email")]
    except Exception as e:
        print(f"  snov failed for {domain}: {e}")
    return []


def gemini(prompt, search=False, as_json=False):
    """One Gemini call; search=True grounds it in live Google Search (what AI answers actually say today)."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return ""
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if search:
        body["tools"] = [{"google_search": {}}]
    if as_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    # busy/overloaded models are common on the free tier: retry, then fall back to the next model
    models = dict.fromkeys([os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), *GEMINI_FALLBACKS])
    for model in models:
        if model in _gemini_exhausted:  # daily quota already gone this run: don't pay the round trip again
            continue
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": key})
        for attempt in range(2):
            try:
                data = json.load(urllib.request.urlopen(req, timeout=180))
                parts = data["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts).strip()
            except urllib.error.HTTPError as e:
                msg = " ".join(e.read().decode("utf-8", "ignore").split())[:160]
                if e.code not in (429, 500, 503):  # bad key/request: no point retrying
                    print(f"  gemini error {e.code} ({model}): {msg}")
                    return ""
                if "exceeded your current quota" in msg:  # plan limit, not a busy spike: next model, no waiting
                    print(f"  gemini quota used up for {model}{' + Google Search' if search else ''}")
                    if not search:  # search quota is separate; plain-call quota gone = gone for today
                        _gemini_exhausted.add(model)
                    break
                print(f"  gemini {e.code} busy on {model}, retrying...")
                time.sleep(10 * (attempt + 1))
            except Exception as e:  # timeouts on an overloaded model: one more try, then the next model
                print(f"  gemini error ({model}): {e}{', retrying' if attempt == 0 else ''}")
                time.sleep(5)
    return ""


def name_words(name):
    """The distinctive words of a business name ('Cindy Moore Real Estate' -> {'cindy', 'moore'})."""
    return {w for w in re.findall(r"[a-z0-9]+", name.lower()) if len(w) >= 4 and w not in GENERIC_NAME_WORDS}


def mentioned(name, answer):
    words, low = name_words(name), answer.lower()
    return bool(words) and sum(w in low for w in words) >= min(2, len(words))


def city_of(address):
    parts = [p.strip() for p in address.split(",")]  # "7 Buford Rd, Peabody, MA 01960, United States"
    if len(parts) == 2 and parts[1]:  # "Peabody, MA" from a hand-made / Zillow list
        return f"{parts[0]}, {parts[1].split()[0]}"
    if len(parts) >= 3 and re.match(r"[A-Z]{2}\b", parts[2]):  # "street, City, ST ZIP[, Country]"
        return f"{parts[1]}, {parts[2].split()[0]}"
    return ""


_visibility_cache = {}
# Realtor.com 2026 Hottest ZIP Codes (released 2026-08-10, Jan-Jun 2026 data): zip, city, state, median list price.
# ponytail: yearly snapshot -- replace with the new list each August
HOT_ZIPS_2026 = [
    ("01960", "Peabody", "MA", 600000), ("07042", "Montclair", "NJ", 1050000), ("08080", "Sewell", "NJ", 426000),
    ("14450", "Fairport", "NY", 429000), ("01085", "Westfield", "MA", 381000), ("48154", "Livonia", "MI", 338000),
    ("17543", "Lititz", "PA", 598000), ("06473", "North Haven", "CT", 562000), ("53151", "New Berlin", "WI", 445000),
    ("60187", "Wheaton", "IL", 575000), ("06905", "Stamford", "CT", 691000), ("61611", "East Peoria", "IL", 212000),
    ("53140", "Kenosha", "WI", 267000), ("17402", "York", "PA", 394000), ("03051", "Hudson", "NH", 608000),
    ("63011", "Ballwin", "MO", 455000), ("19607", "Reading", "PA", 301000), ("44281", "Wadsworth", "OH", 355000),
    ("07840", "Hackettstown", "NJ", 511000), ("06040", "Manchester", "CT", 392000), ("54911", "Appleton", "WI", 280000),
    ("23229", "Henrico", "VA", 515000), ("48182", "Temperance", "MI", 311000), ("03301", "Concord", "NH", 437000),
    ("61108", "Rockford", "IL", 212000), ("17011", "Camp Hill", "PA", 366000), ("66212", "Overland Park", "KS", 385000),
    ("02886", "Warwick", "RI", 457000), ("44641", "Louisville", "OH", 269000), ("35213", "Birmingham", "AL", 526000),
    ("06795", "Watertown", "CT", 505000), ("43614", "Toledo", "OH", 222000), ("43209", "Columbus", "OH", 448000),
    ("21771", "Mount Airy", "MD", 734000), ("55811", "Duluth", "MN", 552000), ("65109", "Jefferson City", "MO", 344000),
    ("55110", "Saint Paul", "MN", 381000), ("44266", "Ravenna", "OH", 254000), ("62704", "Springfield", "IL", 192000),
    ("13760", "Endicott", "NY", 231000), ("53405", "Racine", "WI", 241000), ("68144", "Omaha", "NE", 333000),
    ("54303", "Green Bay", "WI", 261000), ("01007", "Belchertown", "MA", 626000), ("54401", "Wausau", "WI", 297000),
    ("48813", "Charlotte", "MI", 284000), ("51106", "Sioux City", "IA", 248000), ("25526", "Hurricane", "WV", 350000),
    ("61761", "Normal", "IL", 343000), ("01569", "Uxbridge", "MA", 622000),
]
MAX_QUESTIONS = 6  # 2 general + up to 4 specialty questions per agent (free-tier Gemini is slow/rate-limited)
# (label, pattern found in their menus/headings, question a real buyer or seller asks) -- rare niches first
SPECIALTIES = [
    ("probate", r"probate|inherited (home|property)|estate sales?\b",
     "Who is a good real estate agent for a probate or inherited home sale in {city}?"),
    ("business sales", r"(buy|sell)(ing)? (or sell )?a business|business (brokerage|sales)",
     "Which realtor can help me sell or buy a small business in {city}?"),
    ("international", r"dominican republic|puerto rico|costa rica|mexico|portugal|jamaica|colombia|brazil",
     "Which real estate agent in {city} can help me buy property in {country}?"),
    ("bilingual", r"se habla|español|spanish(?![- ]style)|bilingual",
     "Who is a Spanish-speaking real estate agent in {city}?"),
    ("divorce", r"divorce", "Who is a good real estate agent for selling a house during a divorce in {city}?"),
    ("military / VA", r"\bva loans?\b|military|veterans?",
     "Which real estate agent in {city} is best for military families or VA loan buyers?"),
    ("55+ / seniors", r"55\+|55 plus|active adult|seniors?\b|downsiz",
     "Who is a good real estate agent for seniors downsizing in {city}?"),
    ("luxury", r"luxury|high[- ]end", "Who is the best luxury real estate agent in {city}?"),
    ("waterfront", r"waterfront", "Who is the best agent for waterfront homes in {city}?"),
    ("relocation", r"relocat", "Which real estate agent in {city} is best for people relocating from out of state?"),
    ("first-time buyers", r"first[- ]time", "Who is a good real estate agent for first-time home buyers in {city}?"),
    ("investment", r"invest", "Which real estate agent in {city} works with property investors?"),
    ("short sale / foreclosure", r"short sales?\b", "Who is a good agent for a short sale in {city}?"),
    ("rent to own", r"rent[- ]to[- ]own", "Is there a real estate agent in {city} who helps with rent-to-own homes?"),
    ("commercial", r"commercial (real estate|propert)", "Who is a good commercial real estate agent in {city}?"),
]


def ask_ai(question):
    """Cached AI answer (same question for every agent in a city is asked once). Returns (answer, how)."""
    if question not in _visibility_cache:
        # live Google Search grounding needs a paid plan; without it, ask what Gemini itself knows
        answer = "" if _visibility_cache.get("_no_search") else gemini(question, search=True)
        how = "Gemini + Google Search"
        if not answer:
            _visibility_cache["_no_search"] = True
            answer, how = gemini(question), "Gemini's own knowledge, no live search"
        _visibility_cache[question] = (answer, how)
    return _visibility_cache[question]


def specialties(html):
    """Specialties the agent advertises in menus, headings and meta tags (distinctive niches first)."""
    parts = re.findall(r"<(?:a|h[1-4]|li)\b[^>]*>(.*?)</(?:a|h[1-4]|li)>", html, re.S | re.I)
    parts += re.findall(r"<meta[^>]+(?:description|keywords)[^>]+content=[\"']([^\"']*)", html, re.I)
    text = re.sub(r"<[^>]+>|\s+", " ", " ".join(parts)).lower()
    found = []
    for label, pattern, _ in SPECIALTIES:
        m = re.search(pattern, text)
        if m and label not in found:
            found.append(m.group(0).title() if label == "international" else label)
    return found


def buyer_questions(city, found):
    qs = [f"Who are the best real estate agents in {city}? Name specific agents and agencies.",
          f"Who is the best real estate agent to sell my house in {city}?"]
    templates = {label: q for label, _, q in SPECIALTIES}
    for spec in found:
        q = templates.get(spec) or templates["international"].replace("{country}", spec)
        qs.append(q.replace("{city}", city))
    return qs[:MAX_QUESTIONS]


def ai_visibility(name, city, html=""):
    """Question Matrix: the questions buyers/sellers really ask (general + this agent's own specialties),
    asked to the AI; which ones mention the agent. Answers vary run to run -- a signal, re-check in ChatGPT."""
    if not city:
        return "", ""
    questions = buyer_questions(city, specialties(html))
    rows, hits, how, first_names = [], 0, "", []
    for q in questions:
        answer, how = ask_ai(q)
        if not answer:
            continue
        ok = mentioned(name, answer)
        hits += ok
        rows.append(f"{'✅' if ok else '❌'} {q.split('?')[0]}?")
        if not first_names and not ok:
            first_names = named_in(answer)[:4]
    if not rows:
        return "", "\n".join(questions)
    summary = f"{'MENTIONED' if hits == len(rows) else 'NOT mentioned'} in {hits}/{len(rows)} questions ({how})"
    instead = f" | AI named instead: {', '.join(first_names)}" if first_names else ""
    return summary + instead + "\n" + "\n".join(rows), "\n".join(questions)


def named_in(answer):
    """Agency names the AI recommended, from its '### 1. Name' headings or **bold** names."""
    candidates = (re.findall(r"^#+\s*(?:\d+\.\s*)?(.+?)\s*$", answer, re.M)
                  + re.findall(r"\*\*([^*\n]{3,60})\*\*", answer))
    section = re.compile(r"\b(agents|agencies|how|choose|choosing|tips|top|rated|area|summary|disclaimer|note|"
                         r"consider|questions?|factors|why|what|key|local|recommendations?|options|overview)\b", re.I)
    names = [n.strip(" *:#") for n in candidates if not section.search(n) and len(n.strip()) <= 60]
    return list(dict.fromkeys(n for n in names if n))


def sales_brain(situation, conversation=()):
    """Principles from the user's own Sales Brain (Legacy Sales Coach: their books, PDFs, video transcripts)."""
    key = os.environ.get("SALES_BRAIN_API_KEY")
    if not key or _visibility_cache.get("_no_brain"):
        return []
    req = urllib.request.Request(
        os.environ.get("SALES_BRAIN_URL", "https://iyqwrgqyfsfqgqqhlbec.supabase.co/functions/v1/sales-brain-api"),
        json.dumps({"mode": "context", "message": situation[:7900],  # conversation: last 12 turns, API limit
                    "conversation": [{"role": r, "content": t[:1990]} for r, t in list(conversation)[-12:]]}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=90))
    except urllib.error.HTTPError as e:
        print(f"  sales brain error {e.code}: {' '.join(e.read().decode('utf-8', 'ignore').split())[:160]}")
        if e.code in (401, 403, 404):  # not deployed / bad key: stop asking for the rest of this run
            _visibility_cache["_no_brain"] = True
        return []
    except Exception as e:
        print(f"  sales brain error: {e}")
        return []
    return [f"- {p.get('name')} (from \"{p.get('source', {}).get('title', '')}\"): {p.get('what_it_teaches', '')} "
            f"HOW TO APPLY: {p.get('how_to_apply', '')} WHEN NOT TO USE: {p.get('when_not_to_use', '')}"
            for p in data.get("principles", [])[:6]]


def draft_pitch(name, grades):
    """Outreach message built only from findings the audit proved, written with the user's Sales Brain principles."""
    proven = [f"{col}: {g}" for col, g in grades.items() if g.startswith(("FAIL", "PARTIAL", "NOT mentioned")) or
              (col in ("Other Issues", "AI Review") and g and "did not load" not in g
               and "blocked the checker" not in g)]
    if not proven:
        return ""
    findings = "\n".join(proven)
    principles = sales_brain(
        f"First cold outreach message (email or Instagram DM) to the owner of the real estate business '{name}', "
        "who has never heard of me. I audited their website and found these problems:\n" + findings[:3000] +
        "\nHow should the first message open and be framed so a busy realtor replies, sees what ignoring it "
        "costs them, and finds saying no harder than saying yes, without sounding like spam?")
    playbook = ("\n\nApply these principles from my own sales training (use them, don't name them or the books):\n"
                + "\n".join(principles)) if principles else ""
    return gemini(
        f"Write a cold outreach message (max 110 words) to the real estate business '{name}'. "
        "Lead with the single most costly finding below in plain words a realtor understands, make the cost of "
        "leaving it unfixed clear, and end with one easy low-commitment question. Use ONLY these findings. "
        "Do not invent numbers, addresses, rankings, results or urgency, and do not promise they will appear in "
        "ChatGPT or Google. If a finding is about analytics/ads tracking code not running, say their tracking "
        "'may not be recording' and suggest they check their reports -- never claim their data is lost. "
        "If you mention the AI recommending competitors, say it was what an AI assistant answered when you asked, "
        "and never claim the code problems caused it or that fixing them guarantees a mention -- frame the cost "
        "as a risk ('makes it harder for...'), not a certainty. Greet them by a short natural name, not the full "
        "legal business name. "
        "No subject line, no placeholders.\n\nFindings:\n" + findings + playbook)


def condensed_source(html, limit=60000):
    """The parts of a page source that matter to search/AI engines, minus listing cards and review walls."""
    head = re.search(r"<head.*?</head>", html, re.S | re.I)
    scripts = [s for s in re.findall(r"<script\b(?![^>]*\bsrc=)[^>]*>.*?</script>", html, re.S | re.I)
               if re.search(r"schema\.org|gtag\(|clarity|fbq\(|ld\+json", s)]
    heads = re.findall(r"<h[1-3][^>]*>.*?</h[1-3]>", html, re.S | re.I)
    footer = re.search(r"<footer.*?</footer>", html, re.S | re.I)
    parts = [head[0] if head else "", *scripts, *heads, footer[0] if footer else ""]
    return "\n".join(parts)[:limit]


def ai_review(html, place, grades):
    """Gemini reads the page source for issues the fixed checks don't cover.
    Every issue must quote code as evidence; issues whose quote isn't really in the source are dropped."""
    if not html or not os.environ.get("GEMINI_API_KEY"):
        return ""
    already = "\n".join(f"{c}: {g}" for c, g in grades.items() if g)
    answer = gemini(
        "You are auditing a real estate business website's HTML source for problems that hurt how Google and "
        "AI search engines (ChatGPT, Perplexity, Gemini) read and trust this business. Business on Google Maps: "
        f"{place.get('displayName', {}).get('text', '')}, {place.get('formattedAddress', '')}, "
        f"{place.get('nationalPhoneNumber', '')}.\n"
        "Find NEW concrete technical issues (broken or invalid code, conflicting business data, wrong or missing "
        "tags, anything that prevents schema/tracking/content from working). Skip these, already found:\n"
        f"{already}\n\nReturn a JSON list (max 5) of objects {{\"issue\": short plain-English problem, "
        "\"evidence\": an EXACT short snippet copied character-for-character from the source (under 120 chars)}. "
        "Return [] if nothing solid. Never guess.\n\nSOURCE:\n" + condensed_source(html), as_json=True)
    try:
        items = json.loads(answer or "[]")
    except ValueError:
        return ""
    squash = lambda s: " ".join(str(s).split())
    source = squash(html)
    proven = [f"{squash(i['issue'])} [evidence: {squash(i['evidence'])[:80]}]" for i in items
              if isinstance(i, dict) and i.get("issue") and len(squash(i.get("evidence", ""))) >= 8
              and squash(i["evidence"]) in source]  # the anti-hallucination gate
    return "; ".join(proven)


def add_ai(place, grades, pitch=True):
    """Gemini passes, in order: review the source, check AI visibility, then pitch from everything proven."""
    html = grades.pop("_html", "") + f"<li>{place.get('specialty_text', '')}</li>"  # + Zillow specialties/languages
    name = place.get("displayName", {}).get("text", "")
    city = city_of(place.get("formattedAddress", ""))
    if city:  # the questions to paste into ChatGPT need no AI key
        grades["Test in ChatGPT"] = "\n".join(buyer_questions(city, specialties(html)))
    if not (os.environ.get("GEMINI_API_KEY") and name):
        return
    grades["AI Review"] = ai_review(html, place, grades)
    grades["AI Visibility"], grades["Test in ChatGPT"] = ai_visibility(name, city_of(place.get("formattedAddress", "")),
                                                                       html)
    if pitch:
        grades["Pitch"] = draft_pitch(name, grades)


def load_env_file(path=".env"):
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            key, sep, val = line.strip().partition("=")
            if sep and not key.startswith("#"):
                os.environ.setdefault(key.strip(), val.strip().strip('"'))


def main():
    load_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    if sys.argv[1:2] == ["--audit"]:  # grade a live URL (before/after a fix) or a source saved with Ctrl+U, Ctrl+S
        path, address, phone, biz = (sys.argv[2:6] + ["", "", ""])[:4]
        place = {"formattedAddress": address, "nationalPhoneNumber": phone}
        if path.startswith("http"):
            place["websiteUri"] = path
            grades = audit_site(place)
        else:
            grades = audit_site(place, open(path, encoding="utf-8", errors="ignore").read())
        place["displayName"] = {"text": biz}
        add_ai(place, grades)
        report = "\n".join(f"{col:12} {grade}" for col, grade in grades.items())
        print(report)
        os.makedirs("reports", exist_ok=True)  # dated copy = the before/after proof for the client
        name = re.sub(r"\W+", "-", urlparse(path).netloc or os.path.basename(path)).strip("-")
        with open(os.path.join("reports", f"{name}-{time.strftime('%Y-%m-%d-%H%M')}.txt"), "w", encoding="utf-8") as f:
            f.write(f"{path}\n{address} | {phone}\n{time.ctime()}\n\n{report}\n")
        return
    if sys.argv[1:2] == ["--zillow"]:  # you browse Zillow on your PC, the tool copies each profile you open
        capture_zillow(" ".join(sys.argv[2:]) or input("City and state (e.g. Peabody, MA): "))
        return
    if sys.argv[1:2] == ["--person"]:
        person(sys.argv[2:])
        return
    if sys.argv[1:2] == ["--hunt"]:
        hunt(sys.argv[2:])
        return
    if sys.argv[1:2] == ["--zillow-db"]:  # busy Zillow agents via Apify, then the full audit
        args = sys.argv[2:]
        opt = lambda flag, default: int(args[args.index(flag) + 1]) if flag in args else default
        city = " ".join(a for i, a in enumerate(args) if not a.startswith("--")
                        and (i == 0 or not args[i - 1].startswith("--")))
        build_sheet(zillow_agents(city or sys.exit("Usage: --zillow-db Peabody, MA [--min-reviews 10] "
                                                   "[--min-sales 5] [--max 50]"),
                                  opt("--min-reviews", 10), opt("--min-sales", 0), opt("--max", 50)))
        return
    if sys.argv[1:2] == ["--list"]:  # audit agents you collected yourself: "Name | website | phone | City, ST"
        build_sheet(read_list(sys.argv[2] if len(sys.argv) > 2 else "zillow_agents.txt"))
        return
    zips = sys.argv[1:] or sys.exit(__doc__)

    places, seen = [], set()
    for z in zips:
        for p in search_places(f"Real Estate Agency in {z}"):
            name = p.get("displayName", {}).get("text", "")
            if name in seen or is_chain_office(name):
                continue
            seen.add(name)
            places.append((z, p))
    build_sheet(places)


def pick(item, *keys):
    """First non-empty value for any of these keys, looking into nested dicts too (actor field names vary)."""
    wanted = [k.lower() for k in keys]
    stack = [item]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k.lower() in wanted and v not in (None, "", [], {}):
                    return v
            stack += [v for v in cur.values() if isinstance(v, dict)]
    return ""


def number(value):
    """'$1,250,000' / '1.2M' / 48 -> float (0 when unknown)."""
    s = str(value or "").replace(",", "").replace("$", "").strip().lower()
    m = re.match(r"(\d+(?:\.\d+)?)\s*([km]?)", s)
    return float(m[1]) * {"k": 1e3, "m": 1e6, "": 1}[m[2]] if m else 0.0


def zillow_agents(city, min_reviews=10, min_sales=0, limit=50, teams_only=False, min_avg_price=0, brokerage=""):
    """Zillow agents from the Apify actor memo23/zillow-agents-leads-scraper-ppe (its own 1.1M-agent database,
    ~$0.003/agent). Needs APIFY_TOKEN. Busy agents only: min reviews / min sales in the last 12 months."""
    token = os.environ.get("APIFY_TOKEN") or sys.exit("Set APIFY_TOKEN (console.apify.com -> Settings -> API)")
    town, _, state = [p.strip() for p in city.partition(",")]
    body = {"dbType": "agents", "dbState": state.upper()[:2], "dbCity": town, "dbFullDetail": True,
            # maxItems is applied BEFORE the filters and the actor's dbMinSales returns nothing (tested 2026-09),
            # so: generous maxItems (billing is per record delivered) and the sales filter is applied below
            "maxItems": max(limit * 4, 100), "dbMinReviews": min_reviews or None,
            "teamLeadersOnly": teams_only or None, "dbMinAvgPrice": min_avg_price or None,
            "dbBrokerage": brokerage or None,
            "getPastSales": True}  # recent deal towns = expansion signal (free in database mode, tested)
    body = {k: v for k, v in body.items() if v is not None}
    url = ("https://api.apify.com/v2/acts/memo23~zillow-agents-leads-scraper-ppe/run-sync-get-dataset-items?"
           + urlencode({"token": token, "timeout": 300}))
    print(f"Pulling up to {limit} Zillow agents in {city} (min {min_reviews} reviews) -- about ${limit * 0.0029:.2f}...")
    import hashlib
    cache = os.path.join("zillow-cache", hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest() + ".json")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 7 * 86400:  # same pull this week: free
        items = json.load(open(cache, encoding="utf-8"))
        print(f"  (reusing this week's Zillow pull for {city}, no Apify charge)")
    else:
        req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
        try:
            items = json.load(urllib.request.urlopen(req, timeout=330))
        except urllib.error.HTTPError as e:
            sys.exit(f"Apify error {e.code}: {' '.join(e.read().decode('utf-8', 'ignore').split())[:300]}")
        os.makedirs("zillow-cache", exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(items, f)
    with open("zillow_raw.json", "w", encoding="utf-8") as f:  # full records, to check field names / extra data
        json.dump(items, f, indent=1)
    places = [("zillow", zillow_place(it, city)) for it in items]
    kept = [pl for pl in places if number(pl[1]["zillow"]["Sales (12 mo)"]) >= min_sales][:limit]
    print(f"{len(places)} agents received, {len(kept)} with {min_sales}+ sales in 12 months (raw: zillow_raw.json)")
    return kept


def zillow_count(city, brokerage=""):
    """Free preview: how many Zillow agents match (Apify dbCountOnly -- nothing charged but the run start)."""
    town, _, state = [p.strip() for p in city.partition(",")]
    body = {"dbType": "agents", "dbState": state.upper()[:2], "dbCity": town, "dbCountOnly": True,
            **({"dbBrokerage": brokerage} if brokerage else {})}
    url = ("https://api.apify.com/v2/acts/memo23~zillow-agents-leads-scraper-ppe/run-sync-get-dataset-items?"
           + urlencode({"token": os.environ["APIFY_TOKEN"], "timeout": 120}))
    try:
        res = json.load(urllib.request.urlopen(urllib.request.Request(
            url, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=150))
        return int(res[0].get("matchingRecords", 0)) if res else 0
    except Exception as e:
        print(f"  zillow count failed: {e}")
        return 0


def zillow_place(it, city):
    """One Apify/Zillow agent record -> a place row (field names as returned by memo23's actor, 2026-09)."""
    name = str(it.get("name") or pick(it, "fullName", "screenName"))
    info = {x.get("term", ""): " ".join(map(str, x.get("lines") or [])) for x in it.get("professionalInformation", [])}
    site = str(pick(it, "website", "websiteUrl", "contactWebsite") or info.get("Websites", "") or "").split()[:1]
    site = site[0] if site and site[0].startswith("http") else ""
    stats, phones = it.get("salesStats") or {}, it.get("phoneNumbers") or {}
    email = str(it.get("email") or "").lower()
    home = str((it.get("businessAddress") or {}).get("city") or city.split(",")[0]).strip()
    # where the business actually happens: towns of recent closings (listing URLs can't split street from town)
    towns = [s.get("city", "") for s in (it.get("pastSales") or {}).get("past_sales", []) if s.get("city")]
    away = [t for t in dict.fromkeys(towns) if t.lower() != home.lower()]
    team = (it.get("teamDisplayInformation") or {}).get("teamLeadInfo") or {}
    know = it.get("getToKnowMe") or {}
    sales12 = stats.get("salesLastTwelveMonths") or (it.get("professional") or {}).get("salesLastYear") or ""
    avg = stats.get("averagePrice") or ""
    volume = number(sales12) * number(avg)
    return {
        "displayName": {"text": name}, "websiteUri": site,
        "nationalPhoneNumber": str(phones.get("cell") or phones.get("business") or ""),
        "formattedAddress": f"{home}, {city.split(',')[-1].strip()}", "socials": {},
        "emails": [email] if EMAIL.fullmatch(email or "-") else [],
        "specialty_text": " ".join(map(str, (know.get("specialties") or []) + (know.get("languages") or []))),
        "zillow": {
            "Brokerage": it.get("businessName") or "",
            "Zillow Rating": (it.get("ratings") or {}).get("average", ""),
            "Zillow Reviews": (it.get("ratings") or {}).get("count", ""),
            "Sales (12 mo)": sales12, "Total Sales": stats.get("totalSales", ""), "Avg Price": avg,
            "Est. Volume (12 mo)": f"${volume / 1e6:.1f}M" if volume else "", "_volume": volume,
            "Active Listings": (it.get("forSaleListings") or {}).get("listing_count", 0),
            "Recent Deal Towns": ", ".join(dict.fromkeys(towns)),
            "Expansion": (f"{len([t for t in towns if t.lower() != home.lower()])} of {len(towns)} recent deals "
                          f"outside {home}: {', '.join(away[:4])}") if away else "",
            "Team": (team.get("teamName") or "").strip() if team.get("children") else "",
            "Team Size": len(team.get("children") or []),
            "Zillow Premier (pays Zillow)": "yes" if it.get("isPremium") else "",
            "Zillow Specialties": ", ".join(map(str, know.get("specialties") or [])),
            "Languages": ", ".join(map(str, know.get("languages") or [])),
            "Zillow Profile": it.get("url") or "",
        }}


def prospect_score(p, grades):
    """EXCELLENT / OKAY / POOR per the playbook: money + ambition + a visible gap (not the biggest team in town)."""
    z = p.get("zillow", {})
    sales, reviews = number(z.get("Sales (12 mo)")), number(z.get("Zillow Reviews")) or number(z.get("Google Reviews"))
    fails = sum(grades.get(c, "").startswith("FAIL") for c in GRADE_COLS)
    ai_gap = grades.get("AI Visibility", "").count("❌")
    gap = fails >= 2 or ai_gap >= 2 or bool(grades.get("AI Review")) or not p.get("websiteUri")
    growth = [s for s in (z.get("Expansion") and "expanding", z.get("Team") and f"team of {z.get('Team Size')}",
                          z.get("Zillow Premier (pays Zillow)") and "pays for Zillow ads") if s]
    facts = [f"{sales:.0f} sales/yr" if sales else "", f"{reviews:.0f} reviews" if reviews else "",
             f"{z.get('Active Listings')} active listings" if z.get("Active Listings") else "", *growth,
             f"{fails} fails" if fails else "", f"missing from {ai_gap} AI questions" if ai_gap else "",
             "no website" if not p.get("websiteUri") else ""]
    why = ", ".join(f for f in facts if f)
    if sales and sales < 10:
        return f"POOR: too little business to spend $1,500 ({why})"
    if sales > 150 and fails <= 1 and ai_gap == 0:
        return f"POOR: dominant and already visible, little pain ({why})"
    if 20 <= sales <= 100 and reviews >= 50 and gap and (growth or number(z.get("Active Listings"))):
        return f"EXCELLENT: {why}"
    if sales >= 20 or reviews >= 50:
        return f"OKAY: {why}" + ("" if gap else " -- no clear gap found")
    return f"UNKNOWN: no sales data ({why})" if not sales else f"OKAY: {why}"


def maps_lookup(query):
    """One business on Google Maps (the top result): name, address, phone, website, office pin, rating."""
    from urllib.parse import quote_plus
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context("browser-profile", locale="en-US",
                                                        headless=os.environ.get("HEADLESS") == "1")
        page = browser.new_page()
        page.goto(f"https://www.google.com/maps/search/{quote_plus(query)}", timeout=60000)
        if "consent.google" in page.url:
            page.click("button:has-text('Accept all')")
            page.wait_for_url("**/maps/**", timeout=30000)
        page.wait_for_timeout(6000)
        if page.locator("a.hfpxzc").count():  # a results list -> open the best match
            page.locator("a.hfpxzc").first.click()
            page.wait_for_timeout(5000)
        get = lambda sel, attr: page.locator(sel).first.get_attribute(attr) if page.locator(sel).count() else ""
        stars = page.locator("div.F7nice")
        pin = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", page.url)
        found = {"name": page.locator("h1").last.inner_text().strip() if page.locator("h1").count() else "",
                 "address": (get("button[data-item-id=address]", "aria-label") or "").removeprefix("Address: ").strip(),
                 "phone": (get("button[data-item-id^='phone:tel:']", "data-item-id") or "").removeprefix("phone:tel:"),
                 "site": get("a[data-item-id=authority]", "href") or "",
                 "pin": (float(pin[1]), float(pin[2])) if pin else None,
                 "rating": (re.search(r"\d\.\d", stars.first.inner_text()) or [""])[0] if stars.count() else ""}
        browser.close()
    return found


BROKERAGE = re.compile(r"((?:[A-Z][\w&'./-]*\s){0,5}(?:Realty|Real Estate|Realtors|REALTORS|Homes|Properties|Group|"
                       r"Solutions|Associates|Brokerage|Partners|Sotheby's International Realty)(?:,?\s+(?:LLC|Inc)\.?)?)")
PORTALS = {"zillow.com": "Zillow", "realtor.com": "Realtor.com", "homes.com": "Homes.com", "homelight.com": "HomeLight",
           "redfin.com": "Redfin", "linkedin.com": "LinkedIn", "facebook.com": "Facebook", "instagram.com": "Instagram",
           "fastexpert.com": "FastExpert", "signalhire.com": "SignalHire", "rocketreach.co": "RocketReach",
           "trulia.com": "Trulia", "yelp.com": "Yelp"}
NOT_BROKERAGE = re.compile(r"^(the |real estate$|real estate agents?|homes? for sale|luxury homes$|new homes|"
                           r"top real estate|real estate (news|market)|properties$|group$|realtors?$|recent properties|"
                           r"section image|image)", re.I)


def google_search(queries):
    """Google results as data via Apify's official Google Search Scraper (~$0.0045 per query page)."""
    url = ("https://api.apify.com/v2/acts/apify~google-search-scraper/run-sync-get-dataset-items?"
           + urlencode({"token": os.environ["APIFY_TOKEN"], "timeout": 250}))
    body = {"queries": "\n".join(queries), "maxPagesPerQuery": 1, "countryCode": "us"}
    import hashlib
    cache = os.path.join("search-cache", hashlib.sha1(body["queries"].encode()).hexdigest() + ".json")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < 7 * 86400:  # re-runs this week: free
        pages = json.load(open(cache, encoding="utf-8"))
    else:
        try:
            pages = json.load(urllib.request.urlopen(urllib.request.Request(
                url, json.dumps(body).encode(), {"Content-Type": "application/json"}), timeout=280))
        except Exception as e:
            print(f"  google search failed: {e}")
            return []
        os.makedirs("search-cache", exist_ok=True)
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(pages, f)
    return [r for page in pages for r in page.get("organicResults", [])]


def web_identity(name, city):
    """Find a person with no website: search Google for their name, keep results that really mention them,
    and pull what each source says (brokerage, phone, email, stats). Mismatches across sources = the audit angle."""
    first = name.split()[0]
    queries = [f'"{name}" realtor', f'"{name}" zillow', f'"{name}" realtor.com',
               f'"{name}" real estate {city.split(",")[0]}']
    results = [r for r in google_search(queries) if name.lower() in f"{r.get('title')} {r.get('description')}".lower()]
    sources, sites, brokerages, phones, emails, stats = {}, [], {}, {}, set(), []
    name_hosts = {w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 2}
    for r in {r["url"]: r for r in results}.values():
        host = urlparse(r["url"]).netloc.lower().removeprefix("www.")
        portal = next((label for dom, label in PORTALS.items() if host == dom or host.endswith("." + dom)), None)
        source = portal or host
        text = f"{r.get('title', '')} . {r.get('description', '')}"
        at = text.lower().find(name.lower())
        # listing pages name several agents: only the snippet chunk with their name + the next 2 chunks are theirs
        chunks = [c.strip() for c in re.split(r"\.\s+|\s[·|•]\s|;\s|\s-\s", text) if c.strip()]
        idx = next((i for i, c in enumerate(chunks) if name.lower() in c.lower()), None)
        near = " . ".join(chunks[idx:idx + 3]) if idx is not None else ""
        squash = lambda s: re.sub(r"[^a-z]", "", s.lower())
        found_b = [b.strip(" ,.") for b in BROKERAGE.findall(near) if not NOT_BROKERAGE.search(b.strip(" ,."))
                   and first.lower() not in b.lower()
                   and squash(b.split(",")[0]) not in squash(host)]  # the website owner's own name isn't theirs
        for b in found_b:
            brokerages.setdefault(b, set()).add(source)
        for ph in phones_in(near):
            phones.setdefault(ph, set()).add(source)
        emails.update(e for e in EMAIL.findall(near) if is_personal_email(e.lower()))
        after = text[at:at + 220]
        if portal == "Realtor.com" and (m := re.search(r"(\d\.\d)\.?\s*(\d+) reviews.*?(\d+) sales in last 12", after)):
            stats.append(f"Realtor.com: {m[1]} stars, {m[2]} reviews, {m[3]} sales in last 12 months")
        if portal == "Homes.com" and (m := re.search(r"(\d+) Total Sales", after)):
            stats.append(f"Homes.com: {m[1]} total sales")
        if (m := re.search(r"(\d+) Years of Experience", after)):
            stats.append(f"{source}: {m[1]} years of experience")
        if not portal and any(w in host for w in name_hosts):  # e.g. veoresdean.brokerage.com, veoresdeanslist.com
            sites.append(f"https://{host}/")
        sources.setdefault(source, []).append(r["url"])
    ranked = sorted(brokerages.items(), key=lambda kv: -len(kv[1]))
    return {"results": len(results), "sources": sources, "sites": list(dict.fromkeys(sites)),
            "brokerages": {b: sorted(s) for b, s in ranked},
            "phones": {p: sorted(s) for p, s in phones.items()}, "emails": sorted(emails),
            "stats": list(dict.fromkeys(stats))}


def domain_exists(url):
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    try:
        answer = json.load(urllib.request.urlopen("https://dns.google/resolve?" + urlencode({"name": host, "type": "A"}),
                                                  timeout=15))
        return answer.get("Status") != 3  # 3 = NXDOMAIN: the domain isn't registered / has no DNS at all
    except Exception:
        return True  # can't tell -> don't claim it's dead


def person(args):
    """Everything for one person you connected with: Maps + Zillow (Apify) + every website (page source, DNS)
    + Gemini (AI Review, Question Matrix) + Sales Brain -> LinkedIn first message + follow-up. Saved to reports/."""
    get = lambda flag: args[args.index(flag) + 1] if flag in args else ""
    name, city = get("--name"), get("--city")
    if not (name and city):
        sys.exit('Usage: --person --name "Petar Mandic" --city "Louisville, KY" [--sites "a.com b.com"] '
                 '[--brokerage Semonin] [--phone ...] [--address "..."] [--notes "what his LinkedIn says"]')
    sites, brokerage, notes = get("--sites").split(), get("--brokerage"), get("--notes")
    facts, log = [], lambda s: print("  " + s)
    print(f"== {name} ({city}) ==")

    print("1. Google Maps")
    gm = maps_lookup(f"{name} {brokerage} {city}")
    log(f"{gm['name']} | {gm['address']} | {gm['phone']} | {gm['site']} | {gm['rating']} stars")
    if gm["name"]:
        facts.append(f"Google Maps listing: '{gm['name']}', {gm['address']}, phone {gm['phone']}, website {gm['site'] or 'none'}")
    li_addr, li_phone = get("--address"), get("--phone")
    if li_addr and gm["address"] and norm_street(li_addr).split()[:2] != norm_street(gm["address"]).split()[:2]:
        facts.append(f"Address mismatch: LinkedIn says '{li_addr}', Google Maps says '{gm['address']}'")
    if li_phone and gm["phone"] and re.sub(r"\D", "", li_phone)[-10:] != re.sub(r"\D", "", gm["phone"])[-10:]:
        facts.append(f"Phone mismatch: LinkedIn {li_phone}, Google Maps {gm['phone']}")

    print("1b. Web identity sweep (Google via Apify): what every site says about them")
    web = web_identity(name, city) if os.environ.get("APIFY_TOKEN") else None
    if web:
        tag = lambda srcs: f"{', '.join(srcs)}" + (" -- 1 source, verify" if len(srcs) == 1 else "")
        log(f"{web['results']} results mention them, on: {', '.join(list(web['sources'])[:12])}")
        for b, srcs in web["brokerages"].items():
            log(f"brokerage '{b}': {tag(srcs)}")
        for ph, srcs in web["phones"].items():
            log(f"phone {ph}: {tag(srcs)}")
        for s in web["stats"]:
            log(s)
        facts += web["stats"]
        solid = [b for b, srcs in web["brokerages"].items() if len(srcs) > 1]
        if len(web["brokerages"]) > 1:
            facts.append("Different brokerages attached to their name across the web: " + "; ".join(
                f"{b} ({tag(srcs)})" for b, srcs in web["brokerages"].items()))
        if len(web["phones"]) > 1:
            facts.append("Different phone numbers attached to their name: " + "; ".join(
                f"{ph} ({tag(srcs)})" for ph, srcs in web["phones"].items()))
        if web["emails"]:
            facts.append("Emails found next to their name: " + ", ".join(web["emails"]))
        sites += [s for s in web["sites"] if s not in sites]
        brokerage = brokerage or (solid or list(web["brokerages"]) or [""])[0].split(",")[0]

    print("2. Zillow (Apify)")
    z = {}
    count = zillow_count(city, brokerage) if os.environ.get("APIFY_TOKEN") and brokerage else 0
    if count > 150:
        log(f"{count} agents at '{brokerage}' in {city} -- too many to pull (~${count * 0.0029:.2f}); "
            "use a more specific --brokerage")
    elif count:
        words = name_words(name) or set(name.lower().split())
        for _, p in zillow_agents(city, 0, 0, count, brokerage=brokerage):  # billed per delivered record only
            if words and all(w in p["displayName"]["text"].lower() for w in words):
                z = p["zillow"]
                break
        log(", ".join(f"{k}: {v}" for k, v in z.items() if v and not k.startswith("_")) or "not found on Zillow")
        if z:
            facts.append("Zillow: " + ", ".join(f"{k} {v}" for k, v in z.items()
                                                 if v and not k.startswith("_") and k != "Zillow Profile"))
    else:
        log("skipped (needs APIFY_TOKEN and --brokerage, and the brokerage must be in Zillow's US data)")

    print("3. Websites")
    host_of = lambda s: urlparse(s if "//" in s else "https://" + s).netloc.lower().removeprefix("www.")
    all_sites = list({host_of(s): s for s in reversed(sites + ([gm["site"]] if gm["site"] else []))}.values())[::-1]
    place = {"displayName": {"text": name}, "formattedAddress": gm["address"] or city,
             "nationalPhoneNumber": gm["phone"] or li_phone, "pin": gm["pin"],
             "specialty_text": " ".join([notes, z.get("Zillow Specialties", ""), z.get("Languages", "")])}
    grades, seen_pages = {}, {}
    for s in all_sites:
        url = s if s.startswith("http") else "https://" + s
        if not domain_exists(url):
            facts.append(f"The website {s} does not exist (DNS: no such domain) - anyone clicking it gets an error")
            log(f"{s}: DOMAIN DOES NOT EXIST")
            continue
        g = audit_site({**place, "websiteUri": url})
        fingerprint = re.sub(r"\s+", "", re.sub(r"<script.*?</script>", "", g.get("_html", ""), flags=re.S))[:20000]
        if fingerprint and fingerprint in seen_pages:  # a second domain showing the very same page
            facts.append(f"{s} shows the same page as {seen_pages[fingerprint]} (two addresses for one site)")
            log(f"{s}: same page as {seen_pages[fingerprint]}")
            continue
        if fingerprint:
            seen_pages[fingerprint] = s
        issues = {k: v for k, v in g.items() if k != "_html" and v and not v.startswith(("PASS", "CHECK"))}
        log(f"{s}: " + ("; ".join(f"{k}: {v[:90]}" for k, v in issues.items()) or "all checks passed"))
        other = issues.pop("Other Issues", "")
        if other.startswith("BLOCKED"):  # say exactly what's true: people can open it, bots can't
            facts.append(f"{s} opens normally for people, but automated checkers get a security challenge page "
                         "instead of the site, so some AI crawlers may be turned away too (not proven)")
        elif other == "website did not load":
            log(f"   ({s} couldn't be reached from the server -- left out of the facts, check it by hand)")
        elif other:
            facts.append(f"{s} - {other}")
        facts += [f"{s} - {k}: {v}" for k, v in issues.items()]
        if not grades and g.get("_html"):
            grades = g  # the first readable site feeds the AI steps

    print("4. Gemini: AI Review + Question Matrix")
    grades.setdefault("_html", "")
    add_ai(place, grades, pitch=False)  # AI Review, AI Visibility, questions (the messages are written below)
    for key in ("AI Review", "AI Visibility"):
        if grades.get(key):
            log(f"{key}: {grades[key][:300]}")
            facts.append(f"{key}: {grades[key]}")
    if notes:
        facts.append(f"From their LinkedIn: {notes}")

    print("5. Sales Brain + messages")
    fact_text = "\n".join(f"- {f}" for f in facts)
    principles = sales_brain(f"{name} ({city}) just accepted my LinkedIn connection. First message to someone who "
                             "never heard of me; I help agents get read correctly by Google and AI assistants. How do "
                             "I open so they reply and saying yes to a next step feels obvious? Facts:\n" + fact_text)
    messages = gemini(
        f"Write TWO LinkedIn messages from me to {name}, who just accepted my connection request.\n"
        "Pick angles in this priority order: (1) a site that's DOWN or a domain that doesn't exist, (2) different "
        "brokerages/phones/addresses showing for them across the web, (3) specialties or questions where AI "
        "assistants don't mention them, (4) page problems -- translated into what it means for their business "
        "(e.g. 'your homepage never actually says you're a St. Louis realtor'), never the technical term.\n"
        "MESSAGE 1 (max 80 words): no pitch, no link; if they're successful, acknowledge it in one plain honest line "
        "(no flattery); if they have a memorable brand/tagline, mention it; give ONE free, instantly checkable "
        "observation from the top angle available; end with one easy question about their business.\n"
        "MESSAGE 2 (after they reply, max 120 words): frame it as protecting/extending what they built, use at most "
        "two more facts in plain words, offer to send a short breakdown (not a proposal, scope or price). "
        "Never call a fix 'quick' or 'small' (it's paid work).\n"
        "BANNED WORDS (the reader is a realtor, not a developer): H1, heading tag, schema, microdata, JSON-LD, meta, "
        "Open Graph, og:type, coordinates, latitude, crawler, DNS, subdomain, tags, markup, backend, scope of work.\n"
        "Apply the sales principles below; use ONLY the facts; no invented numbers, results or urgency; never claim "
        "cause and effect or promise they'll appear in ChatGPT/Google; keep 'likely'/'may'/'not proven' where the "
        "facts say so. NEVER say people, visitors or clients can't open a site unless the facts say the site is DOWN "
        "or the domain does not exist. No URLs in backticks; no technical words like DNS, subdomain, bot-challenge. "
        "Anything marked '1 source, verify' must not be stated as fact to them (say 'some sites still show...'). "
        "After the messages, list which principle you used for each line.\n\nFACTS:\n" + fact_text +
        "\n\nMY SALES TRAINING PRINCIPLES:\n" + "\n".join(principles)) if os.environ.get("GEMINI_API_KEY") else ""
    report = (f"{name} | {city} | {time.ctime()}\n\nFACTS (checked by the tool):\n{fact_text}\n\n"
              f"TEST IN CHATGPT:\n{grades.get('Test in ChatGPT', '')}\n\n"
              f"SALES BRAIN PRINCIPLES:\n" + "\n".join(p[:220] for p in principles) + f"\n\nMESSAGES:\n{messages}\n")
    os.makedirs("reports", exist_ok=True)
    path = os.path.join("reports", re.sub(r"\W+", "-", name).strip("-") + f"-{time.strftime('%Y-%m-%d-%H%M')}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n" + report + f"\nSaved -> {path}")


def hunt(args):
    """Hot areas -> money signals -> reputation -> the gap (full audit), per the targeting playbook."""
    opt = lambda flag, default: int(args[args.index(flag) + 1]) if flag in args else default
    top, min_price = opt("--top", 10), opt("--min-price", 400000)
    # sweet spot = money + ambition + gap, not the biggest team in town: the Prospect Score ranks, filters stay loose
    min_sales, min_reviews = opt("--min-sales", 20), opt("--min-reviews", 20)
    min_volume, per_city = opt("--min-volume", 0), opt("--per-city", 25)
    areas = [a for a in HOT_ZIPS_2026[:top] if a[3] >= min_price]
    print(f"Hot areas (Realtor.com 2026 Hottest ZIPs, top {top}, median list >= ${min_price:,}):")
    for z, c, s, price in areas:
        print(f"  {z} {c}, {s}  ${price:,}")
    places = []
    if os.environ.get("APIFY_TOKEN"):  # Zillow: sales count, volume, team, reviews
        for z, c, s, _ in areas:
            for label, p in zillow_agents(f"{c}, {s}", min_reviews, min_sales, per_city, teams_only="--teams" in args):
                vol = p["zillow"].get("_volume", 0)
                if vol and vol < min_volume:
                    continue  # known volume under the bar (unknown volume is kept, the min-sales filter applied)
                places.append((z, p))
    else:  # no Apify key: Google Maps, reputation = Google reviews (no sales data there)
        print("(no APIFY_TOKEN: using Google Maps -- no sales data there, and Google hides review COUNTS from "
              f"automated visitors, so: {min_reviews}+ reviews when a count is shown, else rating 4.5+)")
        for z, c, s, _ in areas:
            for p in search_places(f"Real Estate Agency in {z}"):
                g = p["google"]
                count, stars = g["Google Reviews"], number(g["Google Rating"])
                if is_chain_office(p["displayName"]["text"]):
                    continue
                if (count is not None and count >= min_reviews) or (count is None and stars >= 4.5):
                    g["Google Reviews"] = count if count is not None else "hidden by Google"
                    places.append((z, p))
    seen, unique = set(), []
    for z, p in places:
        key = p["displayName"]["text"].lower()
        if key not in seen:
            seen.add(key)
            unique.append((z, p))
    money = lambda p: (p.get("zillow", {}).get("_volume", 0), number(p.get("zillow", {}).get("Sales (12 mo)")),
                       number(p.get("zillow", {}).get("Zillow Reviews")) + number(p.get("google", {}).get("Google Reviews")))
    unique.sort(key=lambda zp: money(zp[1]), reverse=True)  # biggest producers first
    print(f"{len(unique)} qualified leads -- now hunting the gaps...")
    build_sheet(unique)


def read_list(path):
    places = []
    for line in open(path, encoding="utf-8"):
        cols = [c.strip() for c in line.split("|")] + ["", "", "", "", ""]
        if not cols[0] or cols[0].startswith("#"):
            continue
        socials = extract_socials(cols[4]) if cols[4] else {}
        places.append(("list", {"displayName": {"text": cols[0]}, "websiteUri": cols[1],
                                "nationalPhoneNumber": cols[2], "formattedAddress": cols[3], "socials": socials}))
    return places


def capture_zillow(city):
    """Opens Zillow's agent directory in a normal browser window on YOUR PC. You click an agent and press Enter;
    the tool copies what's on that page. No automatic clicking, no captcha dodging -- you solve any captcha yourself."""
    from playwright.sync_api import sync_playwright
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
    out = "zillow_agents.txt"
    with sync_playwright() as pw:
        browser = pw.chromium.launch_persistent_context("zillow-profile", headless=False, locale="en-US",
                                                        viewport=None)
        page = browser.pages[0] if browser.pages else browser.new_page()
        page.goto(f"https://www.zillow.com/professionals/real-estate-agent-reviews/{slug}/", timeout=60000)
        print("\nOpen an agent's profile in the browser, then press Enter here to copy it. "
              "Type 'done' + Enter when finished.\n")
        count = 0
        while input(f"[{count} saved] Enter = copy this profile, done = finish: ").strip().lower() != "done":
            agent = read_profile(browser.pages[-1])
            print(f"   name: {agent['name']}\n   phone: {agent['phone']}\n   website: {agent['website'] or '(none found)'}"
                  f"\n   socials: {', '.join(agent['socials'].values()) or '(none)'}")
            if not agent["website"]:
                agent["website"] = input("   Paste their website (or Enter to keep without one): ").strip()
            with open(out, "a", encoding="utf-8") as f:
                f.write(" | ".join([agent["name"], agent["website"], agent["phone"], city,
                                    " ".join(agent["socials"].values())]) + "\n")
            count += 1
        browser.close()
    print(f"Saved {count} agents to {out}")
    vps = os.environ.get("VPS_HOST")
    if count and vps:  # heavy part (audits, Gemini, Sales Brain) runs on the VPS, results come back here
        print(f"Auditing on {vps}...")
        for cmd in (["scp", out, f"{vps}:/root/maps-leads/{out}"],
                    ["ssh", vps, f"cd /root/maps-leads && python3 maps_leads.py --list {out}"],
                    ["scp", f"{vps}:/root/maps-leads/leads.csv", "leads.csv"]):
            subprocess.run(cmd, check=True)
        print("Done -> leads.csv")
    elif count:
        build_sheet(read_list(out))


def read_profile(page):
    """Name, phone, own website and socials from the profile page currently open."""
    html = page.content()
    name = page.locator("h1").first.inner_text().strip() if page.locator("h1").count() else ""
    tel = page.locator("a[href^='tel:']")
    phone = tel.first.get_attribute("href")[4:] if tel.count() else next(iter(phones_in(page.inner_text("body"))), "")
    links = page.eval_on_selector_all("a[href^='http']", "els => els.map(e => [e.href, e.innerText])")
    external = [(h, t) for h, t in links if not re.search(r"zillow|facebook|instagram|linkedin|twitter|x\.com|"
                                                          r"youtube|tiktok|google|apple\.com|equalhousing", h, re.I)]
    website = next((h for h, t in external if "website" in t.lower()), external[0][0] if external else "")
    return {"name": name, "phone": phone, "website": website, "socials": extract_socials(html)}


def build_sheet(places):
    """Contacts, audits, AI passes and the CSV for any list of (label, place) rows."""
    if not places:  # never replace a good sheet with an empty one
        print("No businesses matched -- leads.csv left unchanged. Try looser filters or more areas.")
        return
    print(f"{len(places)} businesses, scanning websites for emails...")
    with ThreadPoolExecutor(4) as pool:  # more parallel = small hosts drop connections
        emails, socials = map(list, zip(*pool.map(find_contacts, [p.get("websiteUri", "") for _, p in places]))) if places else ([], [])
        audits = list(pool.map(audit_site, [p for _, p in places]))
    if os.environ.get("GEMINI_API_KEY"):
        print("asking Gemini: AI review of page sources, AI visibility per city, drafting pitches...")
    for (_, p), g in zip(places, audits):  # sequential: free-tier rate limits
        add_ai(p, g)
    sources = ["website" if e else "" for e in emails]
    for i, (_, p) in enumerate(places):
        given = [e for e in p.get("emails", []) if is_personal_email(e) and e not in emails[i]]
        if given:  # e.g. the agent's own email from Zillow
            emails[i], sources[i] = [*emails[i], *given], "; ".join(filter(None, [sources[i], "zillow"]))
        if not emails[i] and (found := [e for e in snov_emails(p.get("websiteUri", "")) if is_personal_email(e)]):
            emails[i], sources[i] = found, "snov.io"
    seen_emails = set()  # the same inbox listed for several agencies (brokerage-wide) is kept only on its first row
    for i, found in enumerate(emails):
        emails[i] = [e for e in found if e not in seen_emails and has_mail_server(e.split("@")[1])]
        seen_emails.update(emails[i])
        if not emails[i]:
            sources[i] = ""

    zillow_cols = ["Brokerage", "Zillow Rating", "Zillow Reviews", "Sales (12 mo)", "Total Sales", "Avg Price",
                   "Est. Volume (12 mo)", "Active Listings", "Expansion", "Recent Deal Towns", "Team", "Team Size",
                   "Zillow Premier (pays Zillow)", "Zillow Specialties", "Languages", "Zillow Profile",
                   "Google Rating", "Google Reviews"]
    has_zillow = any(p.get("zillow") or p.get("google") for _, p in places)
    for (_, p), g in zip(places, audits):  # one flat dict for the money/reputation columns, whichever source had them
        p["zillow"] = {**p.get("google", {}), **p.get("zillow", {})}
        g["Prospect Score"] = prospect_score(p, g)
    rank = {"EXCELLENT": 0, "OKAY": 1, "UNKNOWN": 2, "POOR": 3}
    rows = sorted(zip(places, emails, sources, socials, audits),  # best prospects first, then biggest producers
                  key=lambda r: (rank.get(r[4]["Prospect Score"].split(":")[0], 2), -r[0][1]["zillow"].get("_volume", 0)))
    out = os.environ.get("LEADS_OUT", "leads.csv")  # the web app gives every job its own file
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ZIP", "Prospect Score", "Business Name", "Website URL", "Main Office Phone", "Emails",
                    "Email Source", *(zillow_cols if has_zillow else []),
                    *(n.title() for n in SOCIAL_NETS), "Fails", *GRADE_COLS, "AI Review", "AI Visibility", "Test in ChatGPT", "Pitch",
                    "Address"])
        for (z, p), e, src, soc, g in rows:
            soc = {**p.get("socials", {}), **soc}  # website's links win, Zillow's fill the gaps
            fails = sum(g.get(c, "").startswith("FAIL") for c in GRADE_COLS)
            w.writerow([z, g["Prospect Score"], p.get("displayName", {}).get("text", ""), p.get("websiteUri", ""),
                        p.get("nationalPhoneNumber", ""), "; ".join(e), src,
                        *([p.get("zillow", {}).get(c, "") for c in zillow_cols] if has_zillow else []),
                        *(soc.get(n, "") for n in SOCIAL_NETS), fails, *(g.get(c, "") for c in GRADE_COLS),
                        g.get("AI Review", ""), g.get("AI Visibility", ""), g.get("Test in ChatGPT", ""), g.get("Pitch", ""),
                        p.get("formattedAddress", "")])
    print(f"Saved {len(places)} rows ({sum(bool(e) for e in emails)} with email) -> {out}")


if __name__ == "__main__":
    # self-check for the email parser
    assert is_chain_office("RE/MAX Advantage") and not is_chain_office("The Smith Team at Keller Williams")
    assert not is_chain_office("North Shore Realty")
    assert extract_socials('<a href="https://www.facebook.com/sharer/sharer.php?u=x"></a>'
                           '<a href="https://instagram.com/j9sellshomes/">ig</a> https://www.facebook.com/MooreRE') == {
        "instagram": "https://www.instagram.com/j9sellshomes", "facebook": "https://www.facebook.com/MooreRE"}
    assert phones_in("Call (978) 580-7044 or +1 781.521.3491") == {"9785807044", "7815213491"}
    assert grade_nap("Visit us at 200 Lynnfield Street, Peabody", "200 Lynnfield St, Peabody, MA 01960", "").startswith("PARTIAL")
    assert grade_nap("200 Lynnfield St Peabody", "200 Lynnfield St, Peabody, MA 01960", "").startswith("PASS")
    assert grade_nap("no address here", "200 Lynnfield St, Peabody, MA 01960", "").startswith("FAIL")
    office = {"@type": "RealEstateAgent", "geo": {"latitude": "42.5235", "longitude": -70.9575},
              "telephone": "+1-978-394-6736",
              "address": {"streetAddress": "228 Cabot Street", "addressLocality": "Beverly"}}
    assert grade_geo([("", office)], (42.5236, -70.9574)).startswith("PASS")
    assert grade_geo([(" (JavaScript-only)", office)], None).startswith("PARTIAL")
    assert grade_geo([], (42.5, -70.9)).startswith("FAIL")
    assert grade_h1("<h1>Top-Rated Real Estate Brokerage in Peabody, MA</h1>", "Peabody").startswith("PASS")
    assert grade_h1("<h1>Welcome</h1>", "Peabody").startswith("FAIL")
    assert grade_schema([office], []).startswith("PASS")
    assert grade_schema([], [office]).startswith("PARTIAL")
    assert grade_schema([], [office], js_broken=True).startswith("FAIL")
    assert grade_schema([{"@type": "RealEstateAgent", "name": "Jim"}], []).startswith("PARTIAL: RealEstateAgent only as a person")
    assert grade_schema_data([("", office)], "200 Lynnfield St, Peabody, MA 01960, United States",
                             "+19783946736").startswith("FAIL: schema city")
    assert json_objects_in_js('addJsonLd({"@context":"https://schema.org","@type":"RealEstateAgent"});') == [
        {"@context": "https://schema.org", "@type": "RealEstateAgent"}]
    real_gemini, os.environ["GEMINI_API_KEY"] = gemini, os.environ.get("GEMINI_API_KEY") or "test"
    gemini = lambda *a, **k: json.dumps([  # one real quote, one made-up quote
        {"issue": "script tag pasted inside JS", "evidence": 'function runPageScript(){ <script type="application/ld+json">'},
        {"issue": "invented problem", "evidence": '<meta name="robots" content="noindex">'}])
    page = '<html><script>function runPageScript(){\n   <script type="application/ld+json">{}</script></html>'
    assert ai_review(page, {}, {}) == ('script tag pasted inside JS [evidence: function runPageScript(){ '
                                       '<script type="application/ld+json">]'), "hallucination gate broken"
    gemini = real_gemini
    if os.environ["GEMINI_API_KEY"] == "test":
        del os.environ["GEMINI_API_KEY"]
    assert named_in("Intro\n### 1. J. Barrett & Company\ntext\n### 2. **Keller Williams Beverly**\n### Tips") == [
        "J. Barrett & Company", "Keller Williams Beverly"]
    menu = ('<li><a href="/p">Probate</a></li><li><a>Buy or Sell a Business</a></li><h2>Luxury Homes</h2>'
            '<meta name="description" content="Maryland, Washington DC, Dominican Republic">')
    assert specialties(menu) == ["probate", "business sales", "Dominican Republic", "luxury"]
    qs = buyer_questions("Glen Burnie, MD", specialties(menu))
    assert len(qs) == MAX_QUESTIONS and "probate" in qs[2] and "Dominican Republic" in qs[4] and "Glen Burnie" in qs[4]
    assert named_in("### Top-Producing Individual Agents\n* **Marina Yousefian (Long & Foster):** great\n"
                    "### How to Choose the Right Agent\n* **Local Neighborhood Expertise:** x") == [
        "Marina Yousefian (Long & Foster)"]
    sample = {"name": "Viviane Alvarenga", "email": "VivianeRealtor77@gmail.com", "businessName": "Century 21 North shore",
              "businessAddress": {"city": "Peabody"}, "phoneNumbers": {"cell": "(978) 930-4273"},
              "ratings": {"average": 5, "count": 60}, "isPremium": True,
              "salesStats": {"salesLastTwelveMonths": 39, "totalSales": 191, "averagePrice": "$796K"},
              "getToKnowMe": {"specialties": ["Listing Agent", "Relocation"], "languages": ["Spanish"]},
              "pastSales": {"past_sales": [{"city": "Methuen"}, {"city": "Peabody"}, {"city": "Lynn"}]},
              "forSaleListings": {"listing_count": 1, "listings": [
                  {"listing_url": "/homedetails/41-Morse-Ave-Wilmington-MA-01887/57140917_zpid/"}]},
              "teamDisplayInformation": {"teamLeadInfo": {"teamName": "Team V", "children": [{}, {}]}}}
    zp = zillow_place(sample, "Peabody, MA")
    zz = zp["zillow"]
    assert zp["emails"] == ["vivianerealtor77@gmail.com"] and zp["nationalPhoneNumber"] == "(978) 930-4273"
    assert zz["Est. Volume (12 mo)"] == "$31.0M" and zz["Team Size"] == 2 and zz["Active Listings"] == 1
    assert zz["Expansion"] == "2 of 3 recent deals outside Peabody: Methuen, Lynn", zz["Expansion"]
    found = specialties(f"<li>{zp['specialty_text']}</li>")
    assert "relocation" in found and "bilingual" in found, found
    assert prospect_score(zp, {"Schema": "FAIL: x", "NAP": "FAIL: y"}).startswith("EXCELLENT")
    assert prospect_score({"zillow": {"Sales (12 mo)": 5}, "websiteUri": "x"}, {}).startswith("POOR")
    assert prospect_score({"zillow": {"Sales (12 mo)": 300, "Zillow Reviews": 900}, "websiteUri": "x"},
                          {"Schema": "PASS"}).startswith("POOR: dominant")
    assert re.search(DEAD_SITE[0][0], "https://c21peopleschoice.com/cgi-sys/suspendedpage.cgi", re.I)
    assert number("$1,250,000") == 1250000 and number("1.2M") == 1200000 and number(48) == 48 and number("") == 0
    assert len(HOT_ZIPS_2026) == 50 and HOT_ZIPS_2026[0][:2] == ("01960", "Peabody")
    real_search = google_search
    google_search = lambda q: [
        {"url": "https://www.realtor.com/realestateagents/X", "title": "Agents in X",
         "description": "7 sales in last 12 months. Jane Roe. Acme Realty, LLC. 5.0. 7 reviews•2 testimonials. "
                        "8 sales in last 12 months. Bob Smith. Other Homes"},
        {"url": "https://acmerealty.com/l/1", "title": "12 Oak St", "description": "Sold by Acme Realty, LLC, Jane Roe. "
                                                                                  "Direct: 314-504-4662."},
        {"url": "https://janeroe.acmerealty.com/p", "title": "Jane Roe", "description": "Call 314-504-4662"},
        {"url": "https://x.com/y", "title": "unrelated", "description": "no match here"}]
    web = web_identity("Jane Roe", "X, MO")
    google_search = real_search
    assert web["results"] == 3 and web["brokerages"] == {"Acme Realty, LLC": ["Realtor.com"]}, web["brokerages"]
    assert web["phones"] == {"3145044662": ["acmerealty.com", "janeroe.acmerealty.com"]}, web["phones"]
    assert web["stats"] == ["Realtor.com: 5.0 stars, 7 reviews, 8 sales in last 12 months"]
    assert web["sites"] == ["https://janeroe.acmerealty.com/"]
    assert city_of("Peabody, MA") == "Peabody, MA"
    assert city_of("13906 Promenade Green Way Ste 100, Louisville, KY 40245") == "Louisville, KY"
    assert city_of("1780 Albion Rd # 2, Etobicoke, ON M9V 1C1, Canada") == "Etobicoke, ON"
    assert pick({"agent": {"fullName": "Jim", "reviewCount": 0}, "reviewCount": ""}, "fullName") == "Jim"
    assert pick({"stats": {"reviewCount": 72}}, "totalReviews", "reviewCount") == 72
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write("# comment\nJim Smith | https://jimsmith.com | 978-555-1234 | Peabody, MA | https://instagram.com/jimsells\n")
    listed = read_list(f.name)
    os.unlink(f.name)
    assert listed == [("list", {"displayName": {"text": "Jim Smith"}, "websiteUri": "https://jimsmith.com",
                                "nationalPhoneNumber": "978-555-1234", "formattedAddress": "Peabody, MA",
                                "socials": {"instagram": "https://www.instagram.com/jimsells"}})]
    assert city_of("7 Buford Rd, Peabody, MA 01960, United States") == "Peabody, MA"
    assert mentioned("Cindy Moore Real Estate", "Top picks: Cindy Moore (Moore Real Estate Team), ...")
    assert not mentioned("Cindy Moore Real Estate", "Top picks: Lori Penney, Barry Realty Group")
    assert mentioned("Armstrong Field Group at ALUXETY Real Estate", "the Armstrong Field Group in Beverly")
    assert extract_emails('<a href="mailto:Info@Shop.com">x</a> Jim.Smith@Shop.com logo@2x.png jane@example.com '
                          'sales2@shop.com you@yourdomain.com 8f3a9c2b1d4e5f60718293a4b5c6d7e8@sentry.io') == {
        "jim.smith@shop.com"}
    assert is_personal_email("cmoore@moorerealestateteamllc.com") and not is_personal_email("noreply@x.com")
    main()
