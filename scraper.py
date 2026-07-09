#!/usr/bin/env python3
"""
Steelwatch collector.
Runs on a schedule (GitHub Actions), pulls steel/metallurgy engineering roles from
several sources, scores each against Siva's profile, and writes jobs.json for the dashboard.

Design rule: every source is isolated. If one fails, it is logged and the run continues.
The dashboard is never left empty — previous jobs.json is merged forward.
"""

import os, re, json, time, hashlib, datetime, traceback
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
JOBS_PATH = os.path.join(HERE, "jobs.json")
SEEN_PATH = os.path.join(HERE, "data", "seen.json")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "").strip()
NOW = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

def scrub(text):
    """Remove any token-like string so a secret can never reach a committed file or the logs."""
    text = re.sub(r"apify_api_[A-Za-z0-9]{20,}", "[redacted]", text)
    if APIFY_TOKEN:
        text = text.replace(APIFY_TOKEN, "[redacted]")
    return text

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json"}

# ----------------------------------------------------------------------------
# Seed data: real openings pulled at build time. Always present so the dashboard
# has content from the very first second, even before any live source succeeds.
# Live jobs are merged on top of these; seed rows age out like any other.
# ----------------------------------------------------------------------------
SEED = [
  {"t":"Werkstoffingenieur / Physiker – Entwicklung neuer Stahlwerkstoffe (w/m/d)","co":"Salzgitter AG","loc":"Salzgitter","country":"DE","cat":"Materials","fit":92,"posted":"2026-02-28","url":"https://to.indeed.com/aajbmdbckwyj","tags":[["Steel",1],["Materials R&D",1],["New alloys",1],["Development",1]]},
  {"t":"Werkstoffingenieur:in Stahl / Stahltechnologie / Umformtechnik (w/m/d)","co":"GMH Gruppe","loc":"Gröditz","country":"DE","cat":"Materials","fit":90,"posted":"2026-04-13","url":"https://to.indeed.com/aaby8kwz6x2g","tags":[["Steel",1],["Materials",1],["Steel technology",1]]},
  {"t":"Entwicklungsingenieur Werkstoffentwicklung (m/w/d)","co":"Eisenwerk Sulzau-Werfen","loc":"Sulzau","country":"AT","cat":"Development","fit":88,"posted":"2026-02-27","url":"https://to.indeed.com/aafsbt4xcvps","tags":[["Steel castings",1],["Materials",1],["Development",1]]},
  {"t":"Produktionsingenieur – Metallurge (m/w/d)","co":"DK Recycling und Roheisen","loc":"Duisburg","country":"DE","cat":"Process","fit":87,"posted":"2026-05-20","url":"https://to.indeed.com/aajwp6glntmf","tags":[["Metallurgy",1],["Production",1],["Iron",1]]},
  {"t":"Research Engineer – Refractories (m/f/d)","co":"Calderys","loc":"Oberhausen","country":"DE","cat":"R&D","fit":84,"posted":"2026-02-28","url":"https://to.indeed.com/aasht7lbgks2","tags":[["Refractories",1],["R&D",1],["Tundish / ladle",1]]},
  {"t":"Produktingenieur Blockstahl und Schmiedeerzeugnis (w/m/d)","co":"GMH Gruppe","loc":"Gröditz","country":"DE","cat":"Product","fit":80,"posted":"2026-04-13","url":"https://to.indeed.com/aa26l6plf6v4","tags":[["Steel",1],["Product",0],["Forging",0]]},
  {"t":"Prozessingenieur:in Materialrecycling","co":"Plansee Group","loc":"Reutte","country":"AT","cat":"Process","fit":76,"posted":"2026-06-09","url":"https://to.indeed.com/aawqyvqn2l9s","tags":[["Process",1],["Metallurgy",1]]},
  {"t":"Qualitätsingenieur:in – Reduktion / Sinterei","co":"Plansee Group","loc":"Reutte","country":"AT","cat":"Quality","fit":74,"posted":"2026-05-13","url":"https://to.indeed.com/aarf7ws4yhy4","tags":[["Quality",1],["Metallurgy",1]]},
  {"t":"Qualitätsingenieur Schmiede Unna (m|w|d)","co":"VDM Metals International","loc":"Unna","country":"DE","cat":"Quality","fit":73,"posted":"2026-06-10","url":"https://to.indeed.com/aactz28zsdf2","tags":[["Quality",1],["Special alloys",1]]},
  {"t":"Engineer Process – Germany","co":"Kennametal","loc":"Mistelgau","country":"DE","cat":"Process","fit":72,"posted":"2026-05-28","url":"https://to.indeed.com/aasysmqcmgrr","tags":[["Process",1],["Metals",1]]},
  {"t":"Trainee Qualitätssicherung / Technische Klärung (m|w|d)","co":"VDM Metals International","loc":"Altena","country":"DE","cat":"Quality","fit":70,"posted":"2026-06-05","url":"https://to.indeed.com/aakgxn7ztdt8","tags":[["Entry level",1],["Quality",1]]},
  {"t":"Materials Engineer","co":"Element Materials Technology","loc":"Linköping","country":"SE","cat":"Materials","fit":66,"posted":"2026-06-16","url":"https://to.indeed.com/aajmpp7r4qx9","tags":[["Materials",1],["English-speaking",1]]},
  {"t":"Kalibrations- / Applikationsingenieur (m/w/d)","co":"Quantolux Innovation","loc":"Kleve","country":"DE","cat":"Process","fit":58,"posted":"2026-07-03","url":"https://to.indeed.com/aa996rdbs4tb","tags":[["Measurement / sensing",1],["Adjacent to LiDAR work",1]]},
  {"t":"Trainee Engineering (m/w/d)","co":"HME Brass Germany","loc":"Berlin","country":"DE","cat":"Development","fit":60,"posted":"2026-04-14","url":"https://to.indeed.com/aahns9dwl6wy","tags":[["Entry level",1],["Metals",0]]},
  {"t":"Risk Engineer","co":"Höganäs AB","loc":"Höganäs","country":"SE","cat":"Other","fit":52,"posted":"2026-04-24","url":"https://to.indeed.com/aarqcdyrxpjf","tags":[["Steel / powder co.",1]]},
  {"t":"Trader Pulvermetallurgie (m/w/d)","co":"thyssenkrupp","loc":"Essen","country":"DE","cat":"Other","fit":38,"posted":"2026-06-22","url":"https://to.indeed.com/aahdxcfzgbx6","tags":[["Steel major",1],["Sales / trading",0]]}
]

# ----------------------------------------------------------------------------
# Fit scoring
# ----------------------------------------------------------------------------
# Concept-based, multilingual skill model built from Siva's profile.
# Each concept bundles its German / English / French / Swedish variants, so a role
# scores the same whether the ad is written in DE, EN, FR or SV — the language of the
# posting never costs a match. (label, weight, [variant terms, lowercase]).
CONCEPTS = [
  ("Continuous casting", 22, ["continuous cast","strand cast","stranggie","strangguss","coulée continue","coulee continue","stränggjut","stranggjut","kokille","tundish","verteiler"]),
  ("SEN & clogging", 24, ["submerged entry","nozzle","clogging","tauchrohr","tauchausguss","busette"]),
  ("Secondary metallurgy / ladle", 20, ["secondary metall","sekundärmetall","sekundaermetall","ladle","pfannenmetall","poche de coulée","casi","casi-draht","casi wire","calcium treat","kalziumbehand","ca-behandlung","calcium wire","kalziumdraht"," cas "]),
  ("Steel", 16, ["steel","stahl","acier","stål","edelstahl","stahlverarbeitung"]),
  ("Metallurgy", 16, ["metallurg","métallurg","metallurgi"]),
  ("Refractories", 14, ["refractor","feuerfest","réfractaire","refractaire","eldfast"]),
  ("Materials", 14, ["material","werkstoff","matériaux","materiaux","materialtekn","werkstoffwissenschaft"]),
  ("Inclusions / clean steel", 12, ["non-metallic inclusion","nichtmetallische einschl","inclusion","einschluss","einschlüsse","clean steel","reinheitsgrad"]),
  ("Thermo simulation (FactSage)", 12, ["factsage","thermodynam","thermo-calc","thermocalc","phase diagram","phasendiagramm","liquidus","flüssigfenster","equilibrium","gleichgewicht"]),
  ("SEM / EDX characterization", 12, ["rasterelektron","rem-edx","metallograf","metallograph","lichtmikroskop","light microscop","mikroskop","microscop"," sem "," edx "," eds "]),
  ("LiDAR / sensing / automation", 12, ["lidar","ouster","os1-64","xnav","navsuite","global mapper","point cloud","punktwolke","jetson","edge device","rtk","sapos","laser scan","3d scan","3d-scan","3d-mess","sensor","messtechnik","vermessung","inventory","scrap yard","schrottplatz","schrottvolumen"]),
  ("Plant data / Level-2 analysis", 9, ["level-2","level 2","chargenbericht","schichtprotokoll","shift report","heat data","batch report","anlagendaten","plant data"]),
  ("Digitalization / Industry 4.0", 8, ["digitalisierung","digitalization","industrie 4.0","industry 4.0","digital transformation"]),
  ("Data & programming", 7, ["python","power bi","informatica"," sql ","data analysis","datenanalyse","sap s/4hana"," erp "]),
  ("Mechanical engineering base", 7, ["mechanical engineer","maschinenbau","finite element","finite-elemente"," fea ","fluid mechanic","strömungsmechanik"]),
  ("Casting / foundry", 10, ["casting","foundry","gießerei","giesserei","fonderie","gjuteri"," guss"]),
  ("Iron / blast furnace", 10, ["blast furnace","hochofen","roheisen","pig iron","fonte brute"]),
  ("Rolling / forming", 8, ["rolling mill","walzwerk","walzen","umform","laminage","forming"]),
  ("Process engineering", 12, ["process engineer","prozessingenieur","verfahrensingenieur","verfahrenstechnik","ingénieur procédés","ingenieur procedes","process engineering"]),
  ("R&D / development", 10, ["research","forschung","entwicklung","développement","developpement","recherche","research and development"]),
  ("Quality engineering", 9, ["quality","qualität","qualitaet","qualité","qualite","kvalitet","six sigma"]),
  ("Production", 8, ["production","produktion","fertigung"]),
  ("English-speaking role", 5, ["english","englisch"]),
]
LEVEL    = ("Entry-level friendly", 8, ["entry level","entry-level","junior","graduate","absolvent","berufseinsteiger","young professional","jeune diplômé","new graduate"])
ENGINEER = ("Engineering role", 6, ["engineer","ingenieur","ingénieur","ingenjör"])
NEGATIVES = [
  ("Sales / trading", 16, ["sales","vertrieb","vente","trader","trading","einkauf","purchasing","achat","einkäufer"]),
  ("Internship / apprenticeship / student role", 15, ["ausbildung","apprentice","apprenti","lehrling","azubi","werkstudent","working student","studentische","praktikum","praktikant","internship","duales studium","dual study","dual-study","dualer student","duale studentin","trainee","bachelorarbeit","masterarbeit","abschlussarbeit","diplomarbeit"," thesis"]),
  ("Non-engineering / worker / admin", 18, ["technician","techniker","mechaniker","facharbeiter","schlosser","elektriker","laborant","lab assistant","laboratory assistant","specialist","spezialist","controller","accountant","buchhalt","referent","sachbearbeiter","kaufmann","kauffrau","recruiter","human resources","marketing","kommunikation","communications","receptionist","reinigung","fahrer"," driver ","security","koch","pförtner","operator","bediener"]),
  ("Senior / management / executive", 22, ["senior","head of","teamleiter","abteilungsleiter"," manager","meister"," lead ","team lead","gruppenleiter","group leader","principal","chief","cfo"," ceo"," coo","director","vorstand","geschäftsführer","geschaeftsfuehrer","vice president"]),
]

# Roles Siva does NOT want at all (internships, Ausbildung, dual study, theses, working-student,
# trainee programmes). Flagged so the dashboard can hide them by default, with a toggle to show.
OFFTYPE_TERMS = ["ausbildung","ausbildungsplatz","azubi","apprentice","apprenti","lehrling",
  "werkstudent","working student","studentische","praktikum","praktikant"," intern ","internship",
  "duales studium","dual study","dual-study","dualer student","duale studentin",
  "trainee","bachelorarbeit","masterarbeit","abschlussarbeit","diplomarbeit"," thesis","schülerpraktikum"]
def is_offtype(text):
    t = " " + text.lower() + " "
    return any(term in t for term in OFFTYPE_TERMS)

# Requirement notes: languages/skills Siva may lack. These are INFORMATIONAL ONLY — they never
# lower a role's fit. A great-but-partial match still appears in the list, just flagged so he can
# decide for himself. (He has: English C1, German B1 improving, Telugu native, Tamil B1.)
LANG_NOTES = [
  ("Asks for fluent German", ["fließend deutsch","fliessend deutsch","verhandlungssicheres deutsch","verhandlungssichere deutsch","deutschkenntnisse","muttersprache deutsch","deutsch c1","deutsch c2","native german","fluent german","german language skills"]),
  ("Asks for Swedish", ["swedish","svenska"]),
  ("Asks for French", ["français","francais"," french"]),
  ("Asks for Italian", ["italian","italiano"]),
]
def requirement_notes(text):
    notes = [label for label, terms in LANG_NOTES if any(t in text for t in terms)]
    return notes[:2]

CAT_ORDER = [("Materials",["material","werkstoff","matériaux","materiaux"]),
             ("R&D",["research","forschung","recherche"," r&d"]),
             ("Development",["entwicklung","développement","development"]),
             ("Quality",["quality","qualität","qualitaet","qualité","kvalitet"]),
             ("Process",["process","prozess","verfahren","production","produktion","metallurg"]),
             ("Product",["product","produkt"])]

# ---------------------------------------------------------------------------
# Shortlist filter — keep ONLY entry/mid engineering roles in Siva's fields, in Europe.
# ---------------------------------------------------------------------------
TARGET_ROLE = ["engineer","ingenieur","ingénieur","ingenjör","ingegnere","metallurg","métallurg",
  "materials","werkstoff","matériaux","process","prozess","verfahren","procédés","procedes",
  "r&d","forschung","research","entwicklung","development","quality","qualität","qualitaet","qualité",
  "casting","gieß","giess","foundry","strangguss","stranggie","walz","rolling","umform","forming",
  "refractor","feuerfest","metallurgy","metallurgie"]
EXCLUDE_ROLE = ["sales","vertrieb","vente","commercial","account manager","business development",
  "trader","trading","cfo","chief","finance","financial","controll","accountant","buchhalt","treasur",
  "human resources"," hr ","recruit","talent acquisition","marketing",
  "purchasing","einkauf","procurement","buyer","supply chain","logistic",
  "assistant","assistenz","laborant","lab technician","technician","techniker","mechaniker",
  "electrician","elektriker","operator","bediener","schlosser","fitter","welder","schweißer","warehouse",
  "facharbeiter","helfer","aushilfe","reinigung","auxiliar","limpeza","lehre",
  "senior","lead ","teamlead","team lead","principal","head of","director","vice president"," vp ",
  "manager","leiter","meister","specialist","spezialist","expert",
  "praktik","werkstudent","ausbildung","trainee","intern","apprentice","thesis","student","azubi","duales"]

# Non-target COUNTRY NAMES (dropped anywhere they appear in the location).
NON_EUROPE = ["united states","usa","u.s.a","u.s.","america","canada","mexico","brazil","brasil",
  "argentina","chile","colombia","india","pune","mumbai","bangalore","bengaluru","chennai","hyderabad",
  "new delhi","delhi","gurgaon","gurugram","kolkata","china","shanghai","beijing","shenzhen","japan",
  "korea","singapore","malaysia","indonesia","thailand","vietnam","philippines","taiwan","australia",
  "new zealand","south africa","egypt","nigeria","morocco","kenya","uae","dubai","abu dhabi","qatar",
  "saudi","riyadh","jeddah","kuwait","bahrain","oman","israel","russia","kazakh",
  "italy","italia","italie","spain","españa","espana","espagne","poland","polska","pologne",
  "netherlands","nederland","pays-bas","belgium","belgië","belgique","finland","suomi","finlande",
  "norway","norge","norvège","denmark","danmark","danemark","united kingdom","england","scotland",
  "ireland","irland","portugal","czech","tschechien","slovak","hungary","ungarn","romania","rumänien",
  "greece","griechenland","croatia","slovenia","serbia","bulgaria","estonia","latvia","lithuania"]
# Target countries: Germany, Austria, Switzerland, Sweden, Luxembourg, France.
TARGET_CODES = {"DE","AT","CH","SE","LU","FR"}
# ISO country codes to drop when a "City, CC" location names a non-target country.
NON_TARGET_CODES = {"US","IN","BR","CN","GB","IE","IT","ES","PT","PL","NL","BE","FI","NO","DK",
  "CZ","SK","HU","RO","BG","GR","TR","RU","UA","CA","MX","AR","CL","CO","JP","KR","SG","MY",
  "ID","TH","VN","PH","TW","AU","NZ","ZA","EG","NG","MA","AE","SA","QA","KW","BH","OM","IL","KZ"}

# Simple language guess so French-only postings can be dropped (Siva has no French).
FR_STOP = [" le "," la "," les "," des "," une "," pour "," vous "," nous "," avec "," dans "," est ",
           " au "," du "," sur "," par "," qui "," votre "," notre "," afin "]
EN_STOP = [" the "," and "," for "," you "," with "," are "," this "," our "," to "," of "," in ",
           " on "," we "," your "," as "," will "]
def looks_french(text):
    t = " " + (text or "").lower() + " "
    fr = sum(t.count(w) for w in FR_STOP); en = sum(t.count(w) for w in EN_STOP)
    return fr > en and fr >= 3

def in_europe(j):
    loc = (j.get("loc") or "")
    low = loc.lower()
    if any(n in low for n in NON_EUROPE): return False
    for c in re.findall(r",\s*([A-Za-z]{2})(?:,|\s|$)", loc):
        if c.upper() in NON_TARGET_CODES: return False
    return True

def keep_job(j):
    if j.get("french"): return False                         # French-only role → Siva can't do French
    title = " " + (j.get("t") or "").lower() + " "
    if not any(k in title for k in TARGET_ROLE): return False
    if any(k in title for k in EXCLUDE_ROLE): return False
    return in_europe(j)

def _has(text, terms):
    return any(t in text for t in terms)

def score_job(job):
    """Return (fit, tags, category). Scores full title+description in any language against
    the concept model. Respects a pre-set 'fit' (seed rows keep their curated scores)."""
    text = " " + (job.get("t","") + " " + job.get("co","") + " " + job.get("desc","")).lower() + " "

    matched = []
    total = 42
    for label, weight, terms in CONCEPTS:
        if _has(text, terms):
            matched.append((label, weight)); total += weight
    if _has(text, ENGINEER[2]):
        total += ENGINEER[1]
    if _has(text, LEVEL[2]):
        total += LEVEL[1]; matched.append((LEVEL[0], LEVEL[1]))
    neg_labels = []
    for label, weight, terms in NEGATIVES:
        if _has(text, terms):
            total -= weight; neg_labels.append(label)

    fit = max(0, min(100, total))

    cat = "Other"
    for name, kws in CAT_ORDER:
        if _has(text, kws):
            cat = name; break

    if "fit" in job and isinstance(job["fit"], (int, float)):
        fit = job["fit"]
    if job.get("tags"):
        tags = job["tags"]
    else:
        matched.sort(key=lambda x: -x[1])
        tags = [[l, 1] for l, _ in matched[:4]]
        if neg_labels:
            tags.append([neg_labels[0] + " (off-target)", 0])
        if not tags:
            tags = [[cat, 1]]
    return fit, tags, cat

# ----------------------------------------------------------------------------
# Normalisation — tolerant to differing field names across sources
# ----------------------------------------------------------------------------
def _first(d, *keys):
    for k in keys:
        v = d.get(k)
        if v: return v
    return ""

def norm_date(v):
    if not v: return ""
    v = str(v)
    m = re.search(r"\d{4}-\d{2}-\d{2}", v)
    if m: return m.group(0)
    low = v.lower()
    days = 0
    m2 = re.search(r"(\d+)\s*(day|tag)", low)
    if m2: days = int(m2.group(1))
    if "today" in low or "heute" in low: days = 0
    d = NOW - datetime.timedelta(days=days)
    return d.strftime("%Y-%m-%d")

def job_id(co, title, loc):
    raw = re.sub(r"\s+"," ",(co+"|"+title+"|"+loc).lower()).strip()
    return hashlib.sha1(raw.encode()).hexdigest()[:12]

def make_job(title, co, loc, country, url, posted, source, desc=""):
    j = {"t":title.strip(),"co":(co or "").strip(),"loc":(loc or "").strip(),
         "country":(country or "").upper(),"url":url or "","posted":norm_date(posted),
         "source":source,"desc":desc}
    j["fit"], j["tags"], j["cat"] = score_job(j)
    j["note"] = requirement_notes(" " + (title + " " + (desc or "")).lower() + " ")
    j["offtype"] = is_offtype(title)
    j["french"] = ("Asks for French" in j["note"]) or looks_french(desc)
    j["id"] = job_id(j["co"], j["t"], j["loc"])
    j.pop("desc", None)
    return j

# ----------------------------------------------------------------------------
# Apify helper
# ----------------------------------------------------------------------------
def apify_run(actor, payload, timeout=280):
    if not APIFY_TOKEN:
        raise RuntimeError("no APIFY_TOKEN set")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={APIFY_TOKEN}"
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()

# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------
def _flatten(d, prefix=""):
    """Flatten nested dicts to dot-keys, e.g. {'employer':{'name':'X'}} -> {'employer.name':'X'}."""
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out

def src_indeed(cfg, status):
    out = []
    s = cfg["sources"]["indeed"]
    if not s.get("enabled"): return out
    for q in s["queries"]:
        try:
            items = apify_run(s["actor"], {
                "title": q["title"], "location": q.get("location",""),
                "country": q["country"], "limit": s.get("limit_per_query",25),
                "datePosted": s.get("date_posted","14")})
            for raw in items:
                it = _flatten(raw)
                title = _first(it,"title","positionName","jobTitle")
                if not title: continue
                city = _first(it,"location.city","location.admin1Code","location.countryName")
                out.append(make_job(title,
                    _first(it,"employer.name","company","companyName"),
                    city,
                    q["country"],
                    _first(it,"jobUrl","url","link"),
                    _first(it,"datePublished","dateOnIndeed","datePosted","date"),
                    "Indeed",
                    _first(it,"description.text","descriptionText","snippet")))
        except Exception as e:
            status.setdefault("Indeed", []).append(f"query '{q['title']}' failed: {e}")
    status["Indeed"] = status.get("Indeed") or f"ok ({len(out)})"
    return out

def src_google(cfg, status):
    out = []
    s = cfg["sources"]["google_jobs"]
    if not s.get("enabled"): return out
    for q in s["queries"]:
        try:
            items = apify_run(s["actor"], {
                "query": q["query"], "location": q.get("location",""),
                "country": q.get("country","").lower(),
                "max_pagination": s.get("pages_per_query",1)})
            for raw in items:
                it = _flatten(raw)
                title = _first(it,"title","jobTitle","position")
                if not title: continue
                out.append(make_job(title,
                    _first(it,"company_name","company","companyName","employer.name"),
                    _first(it,"location","place"),
                    q.get("country",""),
                    _first(it,"share_link","apply_link","applyLink","url","link"),
                    _first(it,"posted_at","postedAt","date"),
                    "Google Jobs",
                    _first(it,"description","snippet")))
        except Exception as e:
            status.setdefault("Google Jobs", []).append(f"query '{q['query']}' failed: {e}")
    status["Google Jobs"] = status.get("Google Jobs") or f"ok ({len(out)})"
    return out

def src_career_feed(cfg, status):
    """Broad company career-site coverage (voestalpine, Swiss Steel, Feralpi, BSW, Paul Wurth,
    Salzgitter, GMH and many more) via the Fantastic.jobs feed on Apify — one source, many companies."""
    out = []
    s = cfg["sources"].get("career_feed", {})
    if not s.get("enabled"): return out
    SENIOR = {"5-10", "6-10", "10-15", "10+", "15+"}
    try:
        payload = {"limit": s.get("limit", 80)}
        if s.get("organizations"): payload["organizationSearch"] = s["organizations"]
        if s.get("locations"): payload["locationSearch"] = s["locations"]
        if s.get("titles"): payload["titleSearch"] = s["titles"]
        items = apify_run(s["actor"], payload, timeout=180)
        for raw in items:
            title = raw.get("title") or ""
            if not title: continue
            if str(raw.get("ai_experience_level", "")) in SENIOR: continue   # drop senior
            cities = raw.get("cities_derived") or []
            countries = raw.get("countries_derived") or []
            loc = ", ".join([*map(str, cities[:1]), *map(str, countries[:1])]) or (raw.get("locations_alt") or "")
            j = make_job(title, raw.get("organization") or "", loc, "",
                raw.get("url") or "", raw.get("date_posted") or raw.get("date_created") or "",
                "Career page", raw.get("description_text") or "")
            if str(raw.get("ai_job_language", "")).lower().startswith("fr"):
                j["french"] = True
            out.append(j)
        status["Company feeds"] = f"ok ({len(out)})"
    except Exception as e:
        status["Company feeds"] = f"error: {e}"
    return out

def src_successfactors(cfg, status):
    """All SuccessFactors companies (Outokumpu, RHI, Benteler, SMS) via one Apify actor call."""
    out = []
    s = cfg["sources"].get("successfactors", {})
    if not s.get("enabled"): return out
    try:
        items = apify_run(s["actor"], {
            "startUrls": [{"url": u} for u in s.get("startUrls", [])],
            "maxJobsPerSource": s.get("max_jobs", 60),
            "details": True, "descriptionType": "text",
            "postedLastDays": s.get("posted_last_days", 30)}, timeout=280)
        for raw in items:
            it = _flatten(raw)
            title = _first(it, "title")
            if not title: continue
            loc = _first(it, "location")
            m = re.search(r",\s*([A-Za-z]{2})(?:,|\s|$)", loc or "")
            cc = m.group(1).upper() if m else ""
            out.append(make_job(title, _first(it, "company"), loc, cc,
                _first(it, "applyUrl", "url"), _first(it, "postedAt", "posted"),
                "Career page", _first(it, "description")))
        status["SuccessFactors"] = f"ok ({len(out)})"
    except Exception as e:
        status["SuccessFactors"] = f"error: {e}"
    return out

def src_workday(company, status):
    """Direct, free ATS feed — no Apify needed. Demonstrates the ATS-API strategy."""
    out = []
    host, tenant, site = company["host"], company["tenant"], company["site"]
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    try:
        body = {"appliedFacets":{},"limit":20,"offset":0,"searchText":company.get("search","")}
        r = requests.post(api, json=body, timeout=40, headers={
            "Accept":"application/json","Content-Type":"application/json",
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
        r.raise_for_status()
        for p in r.json().get("jobPostings", []):
            path = p.get("externalPath","")
            url = f"https://{host}/en-US/{site}{path}" if path else company["url"]
            out.append(make_job(p.get("title",""), company["name"],
                p.get("locationsText",""), company["country"], url,
                p.get("postedOn",""), "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

def src_recruitee(company, status):
    out = []; slug = company.get("slug", "")
    try:
        r = requests.get(f"https://{slug}.recruitee.com/api/offers/", timeout=40, headers=UA)
        r.raise_for_status()
        for o in r.json().get("offers", []):
            out.append(make_job(o.get("title",""), company["name"],
                o.get("location") or o.get("city") or "", company["country"],
                o.get("careers_url") or o.get("careers_apply_url") or company["url"],
                o.get("published_at",""), "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

def src_greenhouse(company, status):
    out = []; slug = company.get("slug", "")
    try:
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", timeout=40, headers=UA)
        r.raise_for_status()
        for j in r.json().get("jobs", []):
            out.append(make_job(j.get("title",""), company["name"],
                (j.get("location") or {}).get("name",""), company["country"],
                j.get("absolute_url",""), j.get("updated_at",""), "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

def src_lever(company, status):
    out = []; slug = company.get("slug", "")
    try:
        r = requests.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=40, headers=UA)
        r.raise_for_status()
        for p in r.json():
            out.append(make_job(p.get("text",""), company["name"],
                (p.get("categories") or {}).get("location",""), company["country"],
                p.get("hostedUrl",""), p.get("createdAt",""), "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

def src_smartrecruiters(company, status):
    out = []; slug = company.get("slug", "")
    try:
        r = requests.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100", timeout=40, headers=UA)
        r.raise_for_status()
        for p in r.json().get("content", []):
            loc = (p.get("location") or {})
            out.append(make_job(p.get("name",""), company["name"],
                loc.get("city","") or loc.get("country",""), company["country"],
                f"https://jobs.smartrecruiters.com/{slug}/{p.get('id','')}",
                p.get("releasedDate",""), "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

def src_oracle(company, status):
    """Oracle Recruiting Cloud (SSAB, Calderys). Discovers the siteNumber at runtime from the
    host + site name, then reads job requisitions. Tolerant field extraction (schema varies slightly)."""
    out = []; host = company["host"]; site_name = company.get("site", "")
    try:
        s = requests.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCESites?onlyData=true&limit=100",
                         headers=UA, timeout=40).json()
        site_number = None
        for it in s.get("items", []):
            f = _flatten(it)
            name = f.get("Name") or f.get("SiteName") or ""
            if str(name).lower() == site_name.lower():
                site_number = f.get("SiteNumber") or f.get("Number"); break
        if not site_number and s.get("items"):
            site_number = _flatten(s["items"][0]).get("SiteNumber")
        if not site_number:
            raise RuntimeError("could not resolve siteNumber")
        q = (f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
             f"&expand=requisitionList.secondaryLocations"
             f"&finder=findReqs;siteNumber={site_number},limit=100,sortBy=POSTING_DATES_DESC")
        d = requests.get(q, headers=UA, timeout=60).json()
        items = d.get("items", [])
        reqs = (items[0].get("requisitionList") or items[0].get("RequisitionList") or []) if items else []
        for r in reqs:
            rf = _flatten(r)
            title = rf.get("Title") or rf.get("PostingTitle")
            if not title: continue
            rid = rf.get("Id") or rf.get("RequisitionId") or ""
            out.append(make_job(title, company["name"],
                rf.get("PrimaryLocation") or rf.get("Location") or "", company["country"],
                f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_name}/job/{rid}",
                rf.get("PostedDate") or rf.get("PostingStartDate") or "", "Career page"))
        status[company["name"]] = f"ok ({len(out)})"
    except Exception as e:
        status[company["name"]] = f"error: {e}"
    return out

# Which function handles each ATS type. Adding a company = a config block with the right "ats".
HANDLERS = {"workday": src_workday, "recruitee": src_recruitee,
            "greenhouse": src_greenhouse, "lever": src_lever,
            "smartrecruiters": src_smartrecruiters, "oracle": src_oracle}

# ----------------------------------------------------------------------------
# Merge, dedup, persist
# ----------------------------------------------------------------------------
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except Exception: return default

def dedup(jobs):
    best = {}
    prio = {"Career page":3, "Indeed":2, "Google Jobs":1, "Seed":2}
    for j in jobs:
        k = re.sub(r"[^a-z0-9]","", (j["co"]+j["t"]).lower())[:60]
        cur = best.get(k)
        if not cur or prio.get(j.get("source",""),0) > prio.get(cur.get("source",""),0):
            best[k] = j
    return list(best.values())

def main():
    cfg = load_json(CONFIG_PATH, {})
    settings = cfg.get("settings", {})
    keep_days = settings.get("keep_job_days", 45)
    status = {}

    collected = []
    # seed
    for s in SEED:
        j = dict(s); j["source"] = j.get("source","Seed")
        j["id"] = job_id(j["co"], j["t"], j["loc"])
        j["fit"], j["tags"], j["cat"] = score_job(j)
        j["note"] = j.get("note", [])
        j["offtype"] = is_offtype(j["t"])
        collected.append(j)
    status["Seed"] = f"ok ({len(SEED)})"

    # live sources
    try: collected += src_indeed(cfg, status)
    except Exception as e: status["Indeed"] = f"error: {e}"
    try: collected += src_google(cfg, status)
    except Exception as e: status["Google Jobs"] = f"error: {e}"
    try: collected += src_successfactors(cfg, status)
    except Exception as e: status["SuccessFactors"] = f"error: {e}"
    try: collected += src_career_feed(cfg, status)
    except Exception as e: status["Company feeds"] = f"error: {e}"
    for c in cfg.get("companies", []):
        if c.get("enabled") and c.get("ats") in HANDLERS:
            collected += HANDLERS[c["ats"]](c, status)

    # merge with previous run so a bad day never empties the board
    prev = load_json(JOBS_PATH, {}).get("jobs", [])
    collected = [j for j in dedup(collected + prev) if keep_job(j)]

    # first-seen tracking → the basis for the "New" badge
    seen = load_json(SEEN_PATH, {})
    now_iso = NOW.strftime("%Y-%m-%d")
    fresh = []
    for j in collected:
        jid = j["id"]
        j["firstSeen"] = seen.get(jid, now_iso)
        seen[jid] = j["firstSeen"]
        # keep only recent
        try:
            age = (NOW - datetime.datetime.strptime(j["firstSeen"], "%Y-%m-%d")).days
        except Exception:
            age = 0
        if age <= keep_days:
            fresh.append(j)
    fresh.sort(key=lambda x: x["fit"], reverse=True)

    out = {"generated": NOW.strftime("%Y-%m-%d %H:%M UTC"),
           "count": len(fresh), "status": status, "jobs": fresh}

    with open(JOBS_PATH, "w") as f:
        f.write(scrub(json.dumps(out, ensure_ascii=False, indent=1)))
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f: json.dump(seen, f, indent=1)

    print(scrub(f"Steelwatch: wrote {len(fresh)} jobs. Sources: {json.dumps(status)}"))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import io
        buf = io.StringIO()
        traceback.print_exc(file=buf)
        print(scrub(buf.getvalue()))   # scrub token from any error trace before it hits the log
        raise SystemExit(0)
