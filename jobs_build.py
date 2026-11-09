#!/usr/bin/env python3
"""
jobs_build.py  -  Healthcare Hiring Demand dashboard data builder
=================================================================

Turns raw Indeed job-posting snapshots into the small JSON files that the static
dashboard in ./jobs reads. Standard library only (Python 3.9+).

The idea
--------
Every job posting is a demand signal from a facility: who is short-staffed, in which
role, how badly (bonuses, nights, weekends, per diem, months-old postings) and at what
pay. Grouped by employer and market, and tracked across pulls, that is a prospect list
for a staffing agency and a pay benchmark for setting bill rates. Postings from other
staffing agencies are kept but flagged as competitors, not leads.

Inputs
------
jobs/in/<YYYY-MM-DD>/*.md     one file per Indeed query, pasted verbatim from the
                              Indeed connector's search_jobs output. Optional header
                              lines:  search: ... / location: ... / job_type: ...
jobs/in/<YYYY-MM-DD>/*.csv    any CSV with a header row containing at least
                              title, company, location, posted, job_type, compensation, url
                              (e.g. an export from the Indeed Publisher API or a scraper)
jobs/queries.json             the standing query plan (search x location) so every pull
                              covers the same ground and postings can be tracked over time
data/search/facilities.json.gz (optional) the referral directory's national facility
                              index, used to link employers to their CMS record

Outputs (jobs/data/)
--------------------
meta.json        build date, snapshot dates, counts, coverage, role/setting labels
jobs.json        every distinct posting, normalized, with flags and history
employers.json   one row per employer with demand score, tier, signals, talking points
markets.json     per state and per metro: volume, role mix, median pay, urgency
benchmarks.json  hourly pay p25/median/p75 by role family x state (and national)
trends.json      per snapshot: postings seen, new, closed

Usage
-----
python jobs_build.py                 # build from every snapshot under jobs/in
python jobs_build.py --print-queries # list the standing query plan to run again
python jobs_build.py --in jobs/in --out jobs/data --cms-index data/search/facilities.json.gz
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import glob
import gzip
import json
import math
import os
import re
import statistics
import sys

# --------------------------------------------------------------------------- labels

ROLE_FAMILIES = {
    "RN": "Registered nurse",
    "LPN": "LPN / LVN",
    "CNA": "CNA / aide / caregiver",
    "LEAD": "Nursing leadership",
    "MDS": "MDS / clinical specialist",
    "THER": "Therapy / respiratory",
    "APP": "NP / PA / physician",
    "OTHER": "Other",
}
# Fixed display order (also the fixed categorical color order in app.js). Never reorder.
ROLE_ORDER = ["CNA", "LPN", "RN", "LEAD", "MDS", "THER", "APP", "OTHER"]

SETTINGS = {
    "SNF": "Nursing home / post-acute",
    "AL": "Assisted / senior living",
    "HH": "Home health / home care",
    "HOS": "Hospice",
    "HOSP": "Hospital / health system",
    "AGENCY": "Staffing agency",
    "OTHER": "Other / unknown",
}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "US": "Multi-state / remote",
}
STATE_BY_NAME = {v.lower(): k for k, v in STATES.items()}

HOURS_PER_YEAR = 2080.0

# Known staffing / placement firms seen in postings. Matched case-insensitively on the
# employer name; extend freely. Keyword rules below catch most others.
AGENCY_NAMES = [
    "forum group", "atlas search", "humanedge", "russell tobin", "leoforce", "trustaff",
    "fastaff", "gifted healthcare", "white glove placement", "volto", "rn staff", "metasense",
    "specialty professional services", "clover health services", "compass healthcare consulting",
    "alvin kahn", "ram recruiting", "centra healthcare solutions", "towne nursing",
]
AGENCY_WORDS = re.compile(r"\b(staffing|placement|recruit\w*|travel nurs\w*|per diem staff|locum\w*|consulting & placement|talent)\b", re.I)

URGENCY_RULES = [
    ("bonus", re.compile(r"(sign[- ]?on|bonus|\$\s?\d{1,3}(,\d{3})?\s?k?\s*(sign|bonus)|retention)", re.I)),
    ("night", re.compile(r"\b(night|overnight|noc|11p|10pm|7p-7|3p-11p|3p to 11p|3pm-11pm|evening|pm shift)\b", re.I)),
    ("weekend", re.compile(r"\b(weekend|friday-saturday|sat(urday)?[- /]sun(day)?|baylor)\b", re.I)),
    ("perdiem", re.compile(r"\b(per[- ]?diem|prn|pool|float|seasonal|temporary|contract|travel)\b", re.I)),
    ("now", re.compile(r"(apply today|hiring event|immediate|urgent|asap|now hiring|start (this|next) week)", re.I)),
    ("multi", re.compile(r"(multiple (locations|specialties)|covering .* / |all shifts|ft & pt|ft and pt|am/pm & pt)", re.I)),
]
URGENCY_LABEL = {"bonus": "Sign-on / retention bonus", "night": "Nights / evenings", "weekend": "Weekends",
                 "perdiem": "Per diem / PRN / temp", "now": "Hiring now", "multi": "Multiple sites or shifts"}

# --------------------------------------------------------------------------- helpers

def norm_text(s: str) -> str:
    s = (s or "").lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def employer_key(name: str) -> str:
    s = norm_text(name)
    s = re.sub(r"\b(inc|llc|l l c|ltd|corp|corporation|co|company)\b", " ", s)
    s = re.sub(r"^the ", "", s)
    return re.sub(r"\s+", " ", s).strip() or "unknown"


CHAIN_SPLIT = re.compile(r"\s+(at|of)\s+", re.I)


def chain_name(name: str) -> str:
    """'Excelcare at Norwood' -> 'Excelcare'; 'The Terrace of Kissimmee' -> 'The Terrace'.
    Only split when the remainder looks like a place (short, capitalized)."""
    m = CHAIN_SPLIT.split(name, maxsplit=1)
    if len(m) == 3:
        head, _, tail = m
        if 1 <= len(tail.split()) <= 3 and head.strip() and tail[:1].isupper() and not re.search(r"\b(nursing|health|care|living|rehab\w*|center)\b", tail, re.I):
            return head.strip()
    return name.strip()


def parse_posted(s: str):
    s = (s or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")
UNIT = re.compile(r"\b(an? hour|hourly|/hr|per hour|a year|annually|per year|/yr|a week|weekly|per week|a month|monthly|per month|a day|daily|per day)\b", re.I)


def parse_pay(text: str) -> dict:
    """Return pay fields: unit, min, max, mid, hourly_mid, open_ended, note."""
    out = {"unit": None, "min": None, "max": None, "mid": None, "hourly_mid": None, "open_ended": None, "note": None}
    t = (text or "").strip()
    if not t or t.upper() == "N/A":
        return out
    nums = [float(n.replace(",", "")) for n in MONEY.findall(t)]
    if not nums:
        return out
    u = UNIT.search(t)
    unit = "hour"
    if u:
        w = u.group(1).lower()
        unit = "hour" if ("hour" in w or "hr" in w) else "year" if ("year" in w or "annual" in w or "yr" in w) else "week" if "week" in w else "month" if "month" in w else "day"
    lo, hi = min(nums), max(nums)
    if re.search(r"\bup to\b", t, re.I):
        lo = None; out["open_ended"] = "max"
    elif re.search(r"\bfrom\b", t, re.I):
        hi = None; out["open_ended"] = "min"
    # Obvious data-entry mistakes: "$32 - $39 a year" is hourly.
    ref = hi if hi is not None else lo
    if unit == "year" and ref is not None and ref < 500:
        unit = "hour"; out["note"] = "Listed as yearly; treated as hourly"
    if unit == "hour" and ref is not None and ref > 400:
        unit = "year" if ref > 15000 else unit; out["note"] = "Implausible hourly figure"
    out["unit"] = unit
    out["min"], out["max"] = lo, hi
    mid = (lo + hi) / 2 if (lo is not None and hi is not None) else (lo if lo is not None else hi)
    out["mid"] = mid
    div = {"hour": 1.0, "year": HOURS_PER_YEAR, "week": 40.0, "month": HOURS_PER_YEAR / 12, "day": 8.0}[unit]
    out["hourly_mid"] = round(mid / div, 2) if mid is not None else None
    return out


def role_family(title: str) -> str:
    t = " " + norm_text(title) + " "
    def has(*words):
        return any(re.search(r"\b" + w + r"\b", t) for w in words)
    def first_pos(*words):
        best = None
        for w in words:
            m = re.search(r"\b" + w + r"\b", t)
            if m and (best is None or m.start() < best):
                best = m.start()
        return best
    if has("case manager", "rncm", "mds", "care planner"):
        return "MDS"
    if has("business development", "sales", "marketing", "pharmacist", "pharmacy", "veterinary", "receptionist", "dietary", "housekeeping"):
        return "OTHER"
    if has("director of nursing", "don", "adon", "adns", "assistant director", "regional director", "chief nursing", "cno", "director",
           "vp", "vice president", "manager", "associate director",
           "clinical director", "program director", "wellness director", "director of health", "nurse manager", "unit manager",
           "supervisor", "supv", "team lead", "clinical team lead", "associate manager", "rn manager", "nursing manager"):
        return "LEAD"
    if has("mds", "assessor", "wound care", "infection control", "infection preventionist", "staff educator", "educator",
           "instructor", "case manager", "rncm", "admissions", "admission nurse", "coordinator", "care planner", "quality assurance", "qapi"):
        return "MDS"
    if has("nurse practitioner", "np", "physician assistant", "advanced practice", "app", "physician", "md"):
        return "APP"
    # The hands-on families: when a title lists several (e.g. "CNA/HHA/PCA", "RN's, LVN's, PT's"),
    # the first one mentioned wins. "PT" alone means part-time, so therapy needs an explicit term.
    cands = {
        "THER": first_pos("physical therapist", "physical therapy", "pta", "occupational therapist", "occupational therapy", "cota",
                          "speech", "slp", "respiratory therapist", "respiratory", "rrt", "therapist", r"pt s", "pt pta"),
        "LPN": first_pos("lpn", "lvn", "licensed practical", "licensed vocational", "license practical", "charge nurse", "lpns", "lvns"),
        "CNA": first_pos("cna", "certified nursing assistant", "nursing assistant", "hha", "home health aide", "pca", "personal care",
                         "caregiver", "care giver", "companion", "resident assistant", "resident care", "resident service aide",
                         "medication aide", "cma", "aide", "chha", "dsp", "direct support", "cnas", "hhas"),
        "RN": first_pos("rn", "registered nurse", "nurse", "nurses", "rns", "rn s"),
    }
    cands = {k: v for k, v in cands.items() if v is not None}
    if cands:
        return min(cands.items(), key=lambda kv: kv[1])[0]
    return "OTHER"


OVERRIDES = {"employers": {}}


def load_overrides(path: str):
    """jobs/overrides.json lets the team pin an employer's setting/chain/agency flag without code changes."""
    global OVERRIDES
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            OVERRIDES = json.load(fh)
        OVERRIDES["employers"] = {employer_key(k): v for k, v in (OVERRIDES.get("employers") or {}).items()}
        OVERRIDES["prefixes"] = {norm_text(k): v for k, v in (OVERRIDES.get("prefixes") or {}).items()}


def override_for(company: str):
    o = OVERRIDES.get("employers", {}).get(employer_key(company))
    if o:
        return o
    c = norm_text(company)
    for pfx, v in OVERRIDES.get("prefixes", {}).items():
        if c.startswith(pfx):
            return v
    return None


def setting_for(company: str, title: str) -> str:
    c = " " + norm_text(company) + " "
    t = " " + norm_text(title) + " "
    o = override_for(company)
    if o and o.get("setting"):
        return o["setting"]
    if o and o.get("agency"):
        return "AGENCY"
    if any(a in c for a in AGENCY_NAMES) or AGENCY_WORDS.search(company or ""):
        return "AGENCY"
    if re.search(r"\b(hospice)\b", c):
        return "HOS"
    if re.search(r"\b(home health\w*|home care|homecare\w*|homehealth\w*|caregiving|companion|at home|vns|visiting nurse|infusion|caring)\b", c) or "homecare" in c.replace(" ", ""):
        return "HH"
    if re.search(r"\b(assisted living|senior living|memory care|retirement|senior|the bristal|the arbors|brookdale|sunrise|benchmark|brightview|erickson|atria)\b", c):
        return "AL"
    if re.search(r"\b(nursing|rehabilitation|rehab|post acute|post-acute|postacute|care center|healthcare center|health center|skilled|snf|manor|nursing home|subacute|restorative|terrace)\b", c):
        return "SNF"
    if re.search(r"\b(hospital|health system|medical center|medicine|hospitals|health$|health resources|baptist health|parkland|methodist|tenet|hca|ascension|commonspirit|rush|hartford healthcare|middlesex health)\b", c):
        return "HOSP"
    # fall back to the title
    if re.search(r"\b(hospice)\b", t):
        return "HOS"
    if re.search(r"\b(home health|home care|in home|live in|live-in)\b", t):
        return "HH"
    if re.search(r"\b(nursing home|skilled nursing|snf|ltc|long term care|long-term care|post acute|subacute)\b", t):
        return "SNF"
    if re.search(r"\b(assisted living|memory care|senior living)\b", t):
        return "AL"
    if re.search(r"\b(icu|er|emergency|telemetry|operating room|or|labor and delivery|nicu|inpatient|hospital)\b", t):
        return "HOSP"
    return "OTHER"


def parse_location(loc: str):
    loc = (loc or "").strip()
    m = re.search(r"^(.*?),\s*([A-Z]{2})$", loc)
    if m:
        return m.group(1).strip(), m.group(2)
    st = STATE_BY_NAME.get(loc.lower())
    if st:
        return "", st
    if loc.lower() in ("united states", "remote", "usa"):
        return "", "US"
    return loc, ""


def urgency_flags(title: str, job_type: str, comp: str) -> list:
    text = f"{title} {job_type} {comp}"
    flags = [k for k, rx in URGENCY_RULES if rx.search(text)]
    if (job_type or "").lower() in ("per diem", "prn", "temporary", "contract", "travel nursing", "seasonal") and "perdiem" not in flags:
        flags.append("perdiem")
    return flags


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return round(s[int(k)], 2)
    return round(s[f] + (s[c] - s[f]) * (k - f), 2)


# --------------------------------------------------------------------------- ingest

REC_FIELD = re.compile(r"^\s*\*\*(.+?):\*\*\s*(.*)$")
HEADER_FIELD = re.compile(r"^(search|location|job_type|pulled|source|country)\s*:\s*(.*)$", re.I)
FIELD_MAP = {"job title": "title", "job id": "job_id", "company": "company", "location": "location",
             "posted on": "posted", "job type": "job_type", "compensation": "compensation", "view job url": "url", "url": "url"}


def read_md(path: str, snapshot: str) -> list:
    meta = {"search": "", "location": "", "job_type": ""}
    recs, cur = [], {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            m = REC_FIELD.match(line)
            if m:
                key = FIELD_MAP.get(m.group(1).strip().lower())
                if key:
                    if key == "title" and cur:
                        recs.append(cur); cur = {}
                    cur[key] = m.group(2).strip()
                continue
            h = HEADER_FIELD.match(line)
            if h and not cur:
                meta[h.group(1).lower()] = h.group(2).strip()
    if cur:
        recs.append(cur)
    for r in recs:
        r["q_search"], r["q_location"], r["snapshot"], r["source_file"] = meta["search"], meta["location"], snapshot, os.path.basename(path)
    return recs


def read_csv(path: str, snapshot: str) -> list:
    recs = []
    with open(path, encoding="utf-8", newline="") as fh:
        rd = csv.DictReader(fh)
        cols = {c.lower().strip(): c for c in (rd.fieldnames or [])}
        def col(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None
        c_title, c_comp, c_loc = col("title", "job title", "jobtitle"), col("company", "employer"), col("location", "formattedlocation")
        c_posted, c_type, c_pay, c_url = col("posted", "posted on", "date", "date_posted"), col("job_type", "job type", "jobtype"), col("compensation", "salary", "pay"), col("url", "link", "view job url")
        c_search, c_qloc = col("search", "query"), col("query_location", "search_location")
        for row in rd:
            if not c_title or not row.get(c_title):
                continue
            recs.append({"title": row.get(c_title, ""), "company": row.get(c_comp, "") if c_comp else "",
                         "location": row.get(c_loc, "") if c_loc else "", "posted": row.get(c_posted, "") if c_posted else "",
                         "job_type": row.get(c_type, "") if c_type else "", "compensation": row.get(c_pay, "") if c_pay else "",
                         "url": row.get(c_url, "") if c_url else "", "q_search": row.get(c_search, "") if c_search else "",
                         "q_location": row.get(c_qloc, "") if c_qloc else "", "snapshot": snapshot, "source_file": os.path.basename(path)})
    return recs


def load_snapshots(in_dir: str):
    snaps = sorted(d for d in os.listdir(in_dir) if re.match(r"^\d{4}-\d{2}-\d{2}$", d) and os.path.isdir(os.path.join(in_dir, d)))
    if not snaps:
        sys.exit(f"No snapshot folders (YYYY-MM-DD) under {in_dir}. Paste Indeed results into {in_dir}/<date>/<query>.md first.")
    raw, queries_by_snap = [], collections.defaultdict(set)
    for s in snaps:
        folder = os.path.join(in_dir, s)
        for p in sorted(glob.glob(os.path.join(folder, "*.md"))):
            recs = read_md(p, s)
            raw.extend(recs)
            for r in recs:
                queries_by_snap[s].add((norm_text(r["q_search"]), norm_text(r["q_location"])))
        for p in sorted(glob.glob(os.path.join(folder, "*.csv"))):
            raw.extend(read_csv(p, s))
        logp = os.path.join(folder, "_queries.log")
        if os.path.exists(logp):
            with open(logp, encoding="utf-8") as fh:
                for line in fh:
                    parts = [x.strip() for x in line.split("|")]
                    if len(parts) == 3 and parts[0] == "no-results":
                        queries_by_snap[s].add((norm_text(parts[1]), norm_text(parts[2])))
    return snaps, raw, queries_by_snap


# --------------------------------------------------------------------------- normalize

def fingerprint(r: dict) -> str:
    return "|".join([norm_text(r.get("title")), norm_text(r.get("company")), norm_text(r.get("location")), (r.get("posted") or "").strip()])


def normalize(raw: list, snaps: list, queries_by_snap: dict) -> list:
    latest = snaps[-1]
    by_key = {}
    for r in raw:
        url = (r.get("url") or "").strip()
        key = url if url.startswith("http") else "fp:" + fingerprint(r)
        rec = by_key.get(key)
        if rec is None:
            rec = by_key[key] = {"raw": r, "snaps": set(), "queries": set(), "fp": fingerprint(r)}
        rec["snaps"].add(r["snapshot"])
        rec["queries"].add((norm_text(r.get("q_search")), norm_text(r.get("q_location"))))
        if r["snapshot"] >= rec["raw"]["snapshot"]:
            rec["raw"] = r
    # Same posting re-listed under a new URL: merge by fingerprint too.
    by_fp = {}
    for key, rec in list(by_key.items()):
        other = by_fp.get(rec["fp"])
        if other is not None and other is not rec:
            other["snaps"] |= rec["snaps"]; other["queries"] |= rec["queries"]
            if rec["raw"]["snapshot"] >= other["raw"]["snapshot"]:
                other["raw"] = rec["raw"]
            del by_key[key]
        else:
            by_fp[rec["fp"]] = rec

    jobs = []
    for i, rec in enumerate(sorted(by_key.values(), key=lambda x: (x["raw"].get("company", ""), x["raw"].get("title", "")))):
        r = rec["raw"]
        city, st = parse_location(r.get("location"))
        posted = parse_posted(r.get("posted"))
        pay = parse_pay(r.get("compensation"))
        first_seen, last_seen = min(rec["snaps"]), max(rec["snaps"])
        asof = dt.date.fromisoformat(last_seen)
        age = (asof - posted).days if posted else None
        # A posting counts as closed only when one of the queries that found it was re-run
        # in a later snapshot and the posting did not come back.
        status = "active"
        if last_seen != latest:
            later = [s for s in snaps if s > last_seen]
            if any(q in queries_by_snap.get(s, set()) for s in later for q in rec["queries"]):
                status = "closed"
            else:
                status = "unverified"
        company = (r.get("company") or "Unknown").strip()
        fam = role_family(r.get("title", ""))
        sett = setting_for(company, r.get("title", ""))
        flags = urgency_flags(r.get("title", ""), r.get("job_type", ""), r.get("compensation", ""))
        jobs.append({
            "id": f"j{i + 1:04d}",
            "title": (r.get("title") or "").strip(),
            "company": company,
            "employer_key": employer_key(company),
            "chain": (override_for(company) or {}).get("chain") or chain_name(company),
            "city": city, "state": st,
            "location": (r.get("location") or "").strip(),
            "posted": posted.isoformat() if posted else None,
            "age_days": age,
            "job_type": (r.get("job_type") or "").strip() or None,
            "compensation": (r.get("compensation") or "").strip() or None,
            "pay": pay,
            "role": fam,
            "setting": sett,
            "is_agency": sett == "AGENCY",
            "is_confidential": norm_text(company) in ("confidential", "unknown"),
            "flags": flags,
            "url": (r.get("url") or "").strip() or None,
            "first_seen": first_seen, "last_seen": last_seen, "seen": len(rec["snaps"]),
            "status": status,
            "queries": sorted(f"{a} @ {b}" for a, b in rec["queries"] if a or b),
        })
    return jobs


# --------------------------------------------------------------------------- analytics

def mark_pay_outliers(jobs: list):
    """Flag pay figures far from the role's national median (stipend artifacts, typos)."""
    by_role = collections.defaultdict(list)
    for j in jobs:
        h = j["pay"]["hourly_mid"]
        if h:
            by_role[j["role"]].append(h)
    med = {k: statistics.median(v) for k, v in by_role.items() if len(v) >= 3}
    for j in jobs:
        h = j["pay"]["hourly_mid"]
        m = med.get(j["role"])
        livein = j["pay"]["unit"] == "day" and re.search(r"live[- ]?in", j["title"], re.I)
        j["pay"]["outlier"] = bool(h and ((m and (h < 0.45 * m or h > 2.6 * m)) or livein))
        if livein:
            j["pay"]["note"] = "Live-in day rate; not comparable to hourly"


def benchmarks(jobs: list) -> dict:
    rows = []
    groups = collections.defaultdict(list)
    for j in jobs:
        h = j["pay"]["hourly_mid"]
        if not h or j["pay"].get("outlier") or j["status"] == "closed":
            continue
        groups[(j["role"], j["state"])].append(h)
        groups[(j["role"], "ALL")].append(h)
    for (role, st), vals in groups.items():
        rows.append({"role": role, "state": st, "n": len(vals), "p25": pct(vals, .25), "median": pct(vals, .5), "p75": pct(vals, .75),
                     "min": round(min(vals), 2), "max": round(max(vals), 2)})
    rows.sort(key=lambda r: (ROLE_ORDER.index(r["role"]), r["state"]))
    return {"rows": rows}


def market_median(bench_rows, role, st):
    for r in bench_rows:
        if r["role"] == role and r["state"] == st and r["n"] >= 3:
            return r["median"]
    for r in bench_rows:
        if r["role"] == role and r["state"] == "ALL" and r["n"] >= 3:
            return r["median"]
    return None


def employers(jobs: list, bench: dict, asof: dt.date, cms_index) -> list:
    groups = collections.defaultdict(list)
    for j in jobs:
        if j["status"] == "closed":
            continue
        groups[j["employer_key"]].append(j)
    out = []
    for key, js in groups.items():
        names = collections.Counter(j["company"] for j in js)
        name = names.most_common(1)[0][0]
        states = collections.Counter(j["state"] for j in js if j["state"])
        cities = collections.Counter(j["city"] for j in js if j["city"])
        roles = collections.Counter(j["role"] for j in js)
        settings = collections.Counter(j["setting"] for j in js)
        setting = settings.most_common(1)[0][0]
        is_agency = setting == "AGENCY"
        flags = collections.Counter(f for j in js for f in j["flags"])
        ages = [j["age_days"] for j in js if j["age_days"] is not None]
        n = len(js)
        urgent_share = sum(1 for j in js if j["flags"]) / n
        stale_share = (sum(1 for a in ages if a > 45) / len(ages)) if ages else 0
        repost = sum(c - 1 for c in collections.Counter(norm_text(j["title"]) for j in js).values() if c > 1)
        # Pay position vs market, per role.
        pay_pos, pay_notes = [], []
        for role, cnt in roles.items():
            hs = [j["pay"]["hourly_mid"] for j in js if j["role"] == role and j["pay"]["hourly_mid"] and not j["pay"].get("outlier")]
            st = states.most_common(1)[0][0] if states else "ALL"
            mm = market_median(bench["rows"], role, st)
            if hs and mm:
                emp_med = statistics.median(hs)
                diff = (emp_med - mm) / mm
                pay_pos.append(diff)
                pay_notes.append({"role": role, "employer_median": round(emp_med, 2), "market_median": mm, "diff_pct": round(diff * 100, 1), "n": len(hs)})
        # ---- score (0-100): volume 40, breadth 15, urgency 20, aging 15, pay pressure 10
        # Evidence from one or two postings is thin: shrink the share-based parts toward zero.
        conf = 1.0 - 0.5 ** n
        s_volume = min(40.0, 12.0 * math.log1p(n))
        s_breadth = min(15.0, 5.0 * len(roles))
        s_urgency = 20.0 * urgent_share * conf
        s_aging = min(15.0, 15.0 * stale_share * conf + 2.0 * repost)
        s_pay = 0.0
        if pay_pos:
            avg = sum(pay_pos) / len(pay_pos)
            s_pay = (10.0 if avg < -0.03 else 6.0 if avg > 0.08 else 3.0) * conf
        score = round(s_volume + s_breadth + s_urgency + s_aging + s_pay)
        tier = "A" if score >= 60 else "B" if score >= 40 else "C"
        # ---- plain-language signals and talking points
        signals = []
        if n >= 3:
            signals.append(f"{n} open postings across {len(cities) or 1} location{'s' if len(cities) != 1 else ''}")
        top_role = roles.most_common(1)[0]
        if top_role[1] >= 2:
            signals.append(f"{top_role[1]} {ROLE_FAMILIES[top_role[0]]} openings")
        for f, c in flags.most_common(3):
            signals.append(f"{URGENCY_LABEL[f]} on {c} posting{'s' if c != 1 else ''}")
        if ages and max(ages) > 60:
            signals.append(f"Oldest posting open {max(ages)} days")
        if repost:
            signals.append(f"Same title posted {repost + 1} times")
        for pn in pay_notes:
            if abs(pn["diff_pct"]) >= 5:
                signals.append(f"{ROLE_FAMILIES[pn['role']]} pay ${pn['employer_median']:.0f}/hr vs ${pn['market_median']:.0f}/hr market median ({pn['diff_pct']:+.0f}%)")
        talking = []
        if not is_agency:
            if top_role[1] >= 2 or n >= 3:
                talking.append(f"They are carrying {n} open role{'s' if n != 1 else ''}; lead with {ROLE_FAMILIES[top_role[0]].lower()} coverage.")
            if "night" in flags or "weekend" in flags:
                talking.append("Hard-to-fill shifts (nights/weekends) are posted; offer shift-specific per diem coverage.")
            if "bonus" in flags:
                talking.append("They are already paying sign-on bonuses; compare bonus-plus-vacancy cost against an agency fill.")
            if stale_share >= 0.5 and ages:
                talking.append(f"Postings have been open a median {int(statistics.median(ages))} days; the vacancy cost argument is strong.")
            for pn in pay_notes:
                if pn["diff_pct"] <= -5:
                    talking.append(f"Their {ROLE_FAMILIES[pn['role']].lower()} pay is below market; agency staff fill the gap without resetting their pay scale.")
                    break
            if not talking:
                talking.append("Single posting so far; add to watch list and re-check on the next pull.")
        else:
            talking.append("Competitor agency active in this market; note their advertised rates when pricing bills.")
        match = cms_match(name, states.most_common(1)[0][0] if states else "", cities, cms_index) if cms_index else None
        out.append({
            "key": key, "name": name, "chain": (override_for(name) or {}).get("chain") or chain_name(name), "setting": setting, "is_agency": is_agency,
            "is_confidential": all(j["is_confidential"] for j in js),
            "states": [s for s, _ in states.most_common()], "cities": [c for c, _ in cities.most_common(6)],
            "postings": n, "roles": dict(roles), "flags": dict(flags), "urgent_share": round(urgent_share, 2),
            "median_age": int(statistics.median(ages)) if ages else None, "oldest_age": max(ages) if ages else None,
            "newest_posted": max((j["posted"] for j in js if j["posted"]), default=None),
            "pay": pay_notes, "score": score, "tier": tier,
            "score_parts": {"volume": round(s_volume, 1), "breadth": round(s_breadth, 1), "urgency": round(s_urgency, 1), "aging": round(s_aging, 1), "pay": round(s_pay, 1)},
            "signals": signals, "talking_points": talking, "job_ids": [j["id"] for j in js], "cms": match,
        })
    out.sort(key=lambda e: (e["is_agency"], -e["score"], -e["postings"], e["name"]))
    return out


# --------------------------------------------------------------------------- CMS link

CMS_STOP = {"the", "of", "at", "and", "for", "inc", "llc", "ltd", "corp", "co", "a", "an"}
CMS_WEAK = {"center", "centre", "ctr", "nursing", "rehabilitation", "rehab", "healthcare", "health", "care", "home", "facility",
            "skilled", "living", "senior", "community", "manor", "park", "hospital", "medical"}


def load_cms_index(path: str):
    if not path or not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:  # noqa: BLE001
        print(f"  ! could not read {path}: {e}")
        return None
    rows = data.get("rows") or []
    index = collections.defaultdict(list)
    for r in rows:
        if len(r) < 5:
            continue
        toks = set(norm_text(r[2]).split()) - CMS_STOP
        if toks:
            index[r[4]].append((toks, r))
    print(f"  CMS facility index: {sum(len(v) for v in index.values()):,} facilities")
    return index


def cms_match(name: str, state: str, cities: collections.Counter, index):
    if not state or state not in index:
        return None
    toks = set(norm_text(name).split()) - CMS_STOP
    if len(toks) < 1:
        return None
    best, best_s = None, 0.0
    for ftoks, row in index[state]:
        inter = len(toks & ftoks)
        if inter == 0:
            continue
        jac = inter / len(toks | ftoks)
        bonus = 0.15 if norm_text(row[3]) in {norm_text(c) for c in cities} else 0.0
        s = jac + bonus
        if s > best_s:
            best, best_s = row, s
    if best is not None and best_s >= 0.6:
        overlap = toks & (set(norm_text(best[2]).split()) - CMS_STOP)
        strong = overlap - CMS_WEAK - {norm_text(c) for c in cities} - {norm_text(best[3])}
        # Need two shared words, and at least one that is not generic and not just the city name.
        if len(overlap) >= 2 and strong:
            return {"npi": best[0], "type": best[1], "name": best[2], "city": best[3], "state": best[4], "confidence": round(min(1.0, best_s), 2)}
    return None


# --------------------------------------------------------------------------- markets & trends

def markets(jobs: list, emps: list) -> dict:
    live = [j for j in jobs if j["status"] != "closed"]
    def summarize(js, emp_filter):
        roles = collections.Counter(j["role"] for j in js)
        settings = collections.Counter(j["setting"] for j in js)
        pays = collections.defaultdict(list)
        for j in js:
            h = j["pay"]["hourly_mid"]
            if h and not j["pay"].get("outlier"):
                pays[j["role"]].append(h)
        emp_keys = {j["employer_key"] for j in js}
        facility_emps = [e for e in emps if e["key"] in emp_keys and not e["is_agency"] and emp_filter(e)]
        agencies = [e for e in emps if e["key"] in emp_keys and e["is_agency"]]
        return {
            "postings": len(js), "employers": len(facility_emps), "agencies": len(agencies),
            "tier_a": sum(1 for e in facility_emps if e["tier"] == "A"), "tier_b": sum(1 for e in facility_emps if e["tier"] == "B"),
            "roles": dict(roles), "settings": dict(settings),
            "urgent_share": round(sum(1 for j in js if j["flags"]) / len(js), 2) if js else 0,
            "median_pay": {r: pct(v, .5) for r, v in pays.items() if len(v) >= 2},
            "median_age": int(statistics.median([j["age_days"] for j in js if j["age_days"] is not None])) if any(j["age_days"] is not None for j in js) else None,
            "top_employers": [e["key"] for e in sorted(facility_emps, key=lambda e: -e["score"])[:5]],
        }
    by_state = collections.defaultdict(list)
    by_metro = collections.defaultdict(list)
    for j in live:
        by_state[j["state"] or "US"].append(j)
        if j["city"]:
            by_metro[(j["city"], j["state"])].append(j)
    states = {st: dict(name=STATES.get(st, st), **summarize(js, lambda e: True)) for st, js in by_state.items()}
    metros = [dict(city=c, state=st, **summarize(js, lambda e: True)) for (c, st), js in by_metro.items() if len(js) >= 2]
    metros.sort(key=lambda m: -m["postings"])
    return {"states": states, "metros": metros[:60]}


def trends(jobs: list, snaps: list) -> list:
    rows = []
    for i, s in enumerate(snaps):
        seen = [j for j in jobs if j["first_seen"] <= s <= j["last_seen"]]
        new = [j for j in seen if j["first_seen"] == s]
        closed = [j for j in jobs if j["status"] == "closed" and j["last_seen"] == snaps[i - 1]] if i > 0 else []
        rows.append({"snapshot": s, "postings": len(seen), "new": len(new), "closed": len(closed),
                     "employers": len({j["employer_key"] for j in seen if not j["is_agency"]}),
                     "roles": dict(collections.Counter(j["role"] for j in seen))})
    return rows


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="in_dir", default="jobs/in", help="snapshot root (default jobs/in)")
    ap.add_argument("--out", dest="out_dir", default="jobs/data", help="output folder (default jobs/data)")
    ap.add_argument("--queries", default="jobs/queries.json", help="standing query plan")
    ap.add_argument("--cms-index", default="data/search/facilities.json.gz", help="referral directory facility index for CMS links")
    ap.add_argument("--overrides", default="jobs/overrides.json", help="employer setting/chain/agency overrides")
    ap.add_argument("--print-queries", action="store_true", help="print the query plan and exit")
    args = ap.parse_args()

    plan = []
    if os.path.exists(args.queries):
        with open(args.queries, encoding="utf-8") as fh:
            plan = json.load(fh).get("queries", [])
    if args.print_queries:
        for q in plan:
            print(f"{q['search']} | {q['location']}" + (f" | {q['job_type']}" if q.get("job_type") else ""))
        return

    load_overrides(args.overrides)
    print(f"Reading snapshots from {args.in_dir} ...")
    snaps, raw, queries_by_snap = load_snapshots(args.in_dir)
    print(f"  {len(snaps)} snapshot(s): {', '.join(snaps)}; {len(raw):,} raw rows")
    jobs = normalize(raw, snaps, queries_by_snap)
    mark_pay_outliers(jobs)
    print(f"  {len(jobs):,} distinct postings")
    bench = benchmarks(jobs)
    cms_index = load_cms_index(args.cms_index)
    asof = dt.date.fromisoformat(snaps[-1])
    emps = employers(jobs, bench, asof, cms_index)
    mk = markets(jobs, emps)
    tr = trends(jobs, snaps)

    live = [j for j in jobs if j["status"] != "closed"]
    facility_emps = [e for e in emps if not e["is_agency"]]
    plan_keys = {(norm_text(q["search"]), norm_text(q["location"])) for q in plan}
    ran = queries_by_snap.get(snaps[-1], set())
    meta = {
        "built": dt.date.today().isoformat(),
        "asof": snaps[-1], "snapshots": snaps,
        "source": "Indeed job postings (search results pulled through the Indeed connector)",
        "counts": {
            "postings": len(live), "postings_all": len(jobs), "closed": sum(1 for j in jobs if j["status"] == "closed"),
            "employers": len(facility_emps), "agencies": len(emps) - len(facility_emps),
            "tier_a": sum(1 for e in facility_emps if e["tier"] == "A"), "tier_b": sum(1 for e in facility_emps if e["tier"] == "B"),
            "tier_c": sum(1 for e in facility_emps if e["tier"] == "C"),
            "with_pay": sum(1 for j in live if j["pay"]["hourly_mid"]),
            "urgent": sum(1 for j in live if j["flags"]), "states": len(mk["states"]),
            "cms_matched": sum(1 for e in emps if e.get("cms")),
        },
        "roles": ROLE_FAMILIES, "role_order": ROLE_ORDER, "settings": SETTINGS, "flags": URGENCY_LABEL, "states": STATES,
        "coverage": {"queries_run": len(ran), "queries_planned": len(plan), "planned_not_run": sorted(f"{a} @ {b}" for a, b in plan_keys - ran),
                     "run_not_planned": sorted(f"{a} @ {b}" for a, b in ran - plan_keys)},
        "limits": [
            "Each Indeed query returns at most 10 postings, so counts are a sample of demand, not a census. Coverage grows with the query plan.",
            "Posting age is measured from Indeed's 'posted on' date to the pull date; evergreen postings inflate it.",
            "Pay is the advertised range midpoint converted to hourly (2,080 hours/year, 40 hours/week); stipends and travel packages are flagged as outliers.",
            "Role family, care setting and agency status are inferred from the title and employer name by keyword rules; check before you call.",
        ],
    }
    os.makedirs(args.out_dir, exist_ok=True)
    def dump(name, obj):
        with open(os.path.join(args.out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        print(f"  wrote {name} ({os.path.getsize(os.path.join(args.out_dir, name)):,} bytes)")
    dump("meta.json", meta)
    dump("jobs.json", {"rows": jobs})
    dump("employers.json", {"rows": emps})
    dump("markets.json", mk)
    dump("benchmarks.json", bench)
    dump("trends.json", {"rows": tr})
    print(f"Done. {meta['counts']['postings']} live postings, {meta['counts']['employers']} facility employers "
          f"({meta['counts']['tier_a']} tier A, {meta['counts']['tier_b']} tier B), {meta['counts']['agencies']} agencies, "
          f"{meta['counts']['cms_matched']} CMS matches.")


if __name__ == "__main__":
    main()
