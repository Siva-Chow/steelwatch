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
LEVEL    = ("Entry-level friendly", 8, ["entry level","entry-level","junior","graduate","absolvent","berufseinsteiger","young professional","trainee","jeune diplômé","new graduate"])
ENGINEER = ("Engineering role", 6, ["engineer","ingenieur","ingénieur","ingenjör"])
NEGATIVES = [
  ("Sales / trading", ["sales","vertrieb","vente","trader","trading","einkauf","purchasing","achat"]),
  ("Apprenticeship / working student", ["ausbildung","apprentice","apprenti","lehrling","werkstudent","praktikant","internship"]),
  ("Senior / management", ["senior","head of","teamleiter","abteilungsleiter"," manager","meister"]),
]
NEG_PENALTY = 15

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
    for label, terms in NEGATIVES:
        if _has(text, terms):
            total -= NEG_PENALTY; neg_labels.append(label)

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
    j["id"] = job_id(j["co"], j["t"], j["loc"])
    j.pop("desc", None)
    return j

# ----------------------------------------------------------------------------
# Apify helper
# ----------------------------------------------------------------------------
def apify_run(actor, payload, timeout=280):
    if not APIFY_TOKEN:
        raise RuntimeError("no APIFY_TOKEN set")
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    r = requests.post(url, json=payload, timeout=timeout,
                      headers={"Authorization": f"Bearer {APIFY_TOKEN}"})
    r.raise_for_status()
    return r.json()

# ----------------------------------------------------------------------------
# Sources
# ----------------------------------------------------------------------------
def src_indeed(cfg, status):
    out = []
    s = cfg["sources"]["indeed"]
    if not s.get("enabled"): return out
    for q in s["queries"]:
        try:
            items = apify_run(s["actor"], {
                "title": q["title"], "location": q.get("location",""),
                "country": q["country"], "limit": s.get("limit_per_query",25),
                "datePosted": s.get("date_posted","month")})
            for it in items:
                title = _first(it,"title","positionName","jobTitle")
                if not title: continue
                out.append(make_job(title,
                    _first(it,"company","companyName","company_name"),
                    _first(it,"location","jobLocation","formattedLocation"),
                    q["country"],
                    _first(it,"url","jobUrl","link","applyUrl","externalApplyLink"),
                    _first(it,"datePosted","postedAt","date","postingDateParsed","postedDate"),
                    "Indeed",
                    _first(it,"description","descriptionText","snippet")))
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
            for it in items:
                title = _first(it,"title","jobTitle","position")
                if not title: continue
                out.append(make_job(title,
                    _first(it,"company_name","company","companyName"),
                    _first(it,"location","place"),
                    q.get("country",""),
                    _first(it,"share_link","apply_link","applyLink","url","link"),
                    _first(it,"posted_at","postedAt","detected_extensions","date"),
                    "Google Jobs",
                    _first(it,"description","snippet")))
        except Exception as e:
            status.setdefault("Google Jobs", []).append(f"query '{q['query']}' failed: {e}")
    status["Google Jobs"] = status.get("Google Jobs") or f"ok ({len(out)})"
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
        collected.append(j)
    status["Seed"] = f"ok ({len(SEED)})"

    # live sources
    try: collected += src_indeed(cfg, status)
    except Exception as e: status["Indeed"] = f"error: {e}"
    try: collected += src_google(cfg, status)
    except Exception as e: status["Google Jobs"] = f"error: {e}"
    for c in cfg.get("companies", []):
        if c.get("enabled") and c.get("ats") == "workday":
            collected += src_workday(c, status)

    # merge with previous run so a bad day never empties the board
    prev = load_json(JOBS_PATH, {}).get("jobs", [])
    collected = dedup(collected + prev)

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

    # Safety net: never allow a token-like string into the committed file, whatever a source returned.
    def scrub(text):
        text = re.sub(r"apify_api_[A-Za-z0-9]{20,}", "[redacted]", text)
        if APIFY_TOKEN:
            text = text.replace(APIFY_TOKEN, "[redacted]")
        return text

    with open(JOBS_PATH, "w") as f:
        f.write(scrub(json.dumps(out, ensure_ascii=False, indent=1)))
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w") as f: json.dump(seen, f, indent=1)

    print(scrub(f"Steelwatch: wrote {len(fresh)} jobs. Sources: {json.dumps(status)}"))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        # never hard-fail the scheduled run
        raise SystemExit(0)
