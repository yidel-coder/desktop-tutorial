#!/usr/bin/env python3
"""
build.py  -  Hospital & Doctor Referral Directory data builder
===============================================================

Downloads free public government data, cleans and joins it, and writes
compressed JSON files into ./data that the static site (index.html,
style.css, app.js) loads with hash routes.

Data model (two logical tables, see README):
    providers(npi, ccn, name, type, address, city, state, zip, specialty)
    flows(source_npi, dest_npi, year, patients, share)

Sources
  1. Provider names / IDs
       - CMS Hospital, SNF, Home Health Agency and Hospice Enrollment files (data.cms.gov)
       - NPPES NPI Registry monthly dissemination file (download.cms.gov/nppes)
  2. Patient-sharing pairs
       - CMS Physician Shared Patient Patterns (NBER mirror, data.nber.org)
         Any other feed (Trella, Definitive, CareSet, VRDC extract) can be
         dropped in with --flows-file as a CSV: source_npi,dest_npi,patients
  3. Volume context
       - CMS Medicare Post-Acute Care & Hospice - by Provider and Service (data.cms.gov)
       - Care Compare star ratings (data.cms.gov/provider-data)

Usage
  python build.py --demo                  # synthetic data, no downloads (preview the site)
  python build.py                         # full national build, newest PSPP year (2015, 30-day)
  python build.py --states NY,NJ,CT       # only providers located in these states
  python build.py --prior-year 2014       # also compute fastest-growing relationships
  python build.py --flows-file my.csv --year 2024 --flows-label "Trella Health 2024"

Only the Python standard library is required (3.9+).
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import heapq
import html
import io
import json
import math
import os
import random
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

USER_AGENT = "referral-directory-build/1.0 (+https://github.com/; python-urllib)"

# Provider type codes used everywhere (data files + app.js)
TYPES = {
    "H": "Hospital",
    "R": "Rehab hospital",
    "L": "Long-term care hospital",
    "S": "Nursing home (SNF)",
    "A": "Home health agency",
    "C": "Hospice",
    "D": "Doctor",
}
FACILITY_TYPES = ("H", "R", "L", "S", "A", "C")

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
    "PR": "Puerto Rico", "VI": "U.S. Virgin Islands", "GU": "Guam", "AS": "American Samoa",
    "MP": "Northern Mariana Islands",
}

# data.cms.gov catalogue (data.json) titles, with UUID fallbacks (the "latest" dataset ids).
CMS_DATASETS = {
    "hospital_enroll": ("Hospital Enrollments", "f6f6505c-e8b0-4d57-b258-e2b94133aaf2"),
    "snf_enroll": ("Skilled Nursing Facility Enrollments", "5f2c306f-3b1c-42cd-b037-187b2ce22126"),
    "hha_enroll": ("Home Health Agency Enrollments", "15f64ab4-3172-4a27-b589-ebd67a6d28aa"),
    "hospice_enroll": ("Hospice Enrollments", "25704213-e833-4b8b-9dbc-58dd17149209"),
    "hospital_npis": ("Hospital Additional NPIs", None),
    "snf_npis": ("Skilled Nursing Facility Additional NPIs", None),
    "hha_npis": ("Home Health Agency Additional NPIs", None),
    "hospice_npis": ("Hospice Additional NPIs", None),
    "pac_snf": ("Medicare Post-Acute Care Utilization - Skilled Nursing Facility by Geography and Provider", None),
    "pac_hos": ("Medicare Post-Acute Care Utilization - Hospice by Geography and Provider", None),
    "pac_hh": ("Medicare Post-Acute Care Utilization - Home Health Agency by Geography and Provider", None),
    "pac_irf": ("Medicare Post-Acute Care Utilization - Inpatient Rehabilitation Facility by Geography and Provider", None),
    "pac_ltc": ("Medicare Post-Acute Care Utilization - Long-Term Care Hospital by Geography and Provider", None),
    "taxonomy": ("Medicare Provider and Supplier Taxonomy Crosswalk", None),
}

# Care Compare (data.cms.gov/provider-data) dataset ids
CARE_COMPARE = {
    "H": "xubh-q36u",  # Hospital General Information
    "S": "4pq5-n9py",  # Nursing homes - Provider Information
    "A": "6jpm-sxkc",  # Home Health Care - Agencies
    "C": "252m-zfp9",  # Hospice - General Information
}

NPPES_INDEX = "https://download.cms.gov/nppes/NPI_Files.html"

# Built-in taxonomy -> specialty map (used when the crosswalk download is unavailable)
TAXONOMY = {
    "207K00000X": "Allergy & Immunology", "207L00000X": "Anesthesiology", "207LP2900X": "Pain Medicine",
    "207N00000X": "Dermatology", "207P00000X": "Emergency Medicine", "207Q00000X": "Family Medicine",
    "207QG0300X": "Geriatric Medicine", "207QH0002X": "Hospice & Palliative Medicine",
    "207QS0010X": "Sports Medicine", "207R00000X": "Internal Medicine", "207RA0401X": "Addiction Medicine",
    "207RC0000X": "Cardiology", "207RC0001X": "Cardiac Electrophysiology", "207RI0011X": "Interventional Cardiology",
    "207RC0200X": "Critical Care Medicine", "207RE0101X": "Endocrinology", "207RG0100X": "Gastroenterology",
    "207RG0300X": "Geriatric Medicine", "207RH0000X": "Hematology", "207RH0003X": "Hematology & Oncology",
    "207RX0202X": "Medical Oncology", "207RH0002X": "Hospice & Palliative Medicine", "207RI0200X": "Infectious Disease",
    "207RN0300X": "Nephrology", "207RP1001X": "Pulmonary Disease", "207RR0500X": "Rheumatology",
    "207RS0012X": "Sleep Medicine", "207RB0002X": "Obesity Medicine", "207RT0003X": "Transplant Hepatology",
    "207T00000X": "Neurosurgery", "207U00000X": "Nuclear Medicine", "207V00000X": "Obstetrics & Gynecology",
    "207VG0400X": "Gynecology", "207VX0201X": "Gynecologic Oncology", "207VM0101X": "Maternal & Fetal Medicine",
    "207W00000X": "Ophthalmology", "207X00000X": "Orthopedic Surgery", "207XS0114X": "Orthopedic Surgery (Joint Reconstruction)",
    "207XS0117X": "Orthopedic Spine Surgery", "207XX0004X": "Foot & Ankle Surgery", "207XX0005X": "Sports Medicine (Orthopedic)",
    "207XS0106X": "Hand Surgery", "207XX0801X": "Orthopedic Trauma", "207Y00000X": "Otolaryngology (ENT)",
    "207ZP0102X": "Pathology", "207ZP0105X": "Clinical Pathology", "208000000X": "Pediatrics",
    "208100000X": "Physical Medicine & Rehabilitation", "2081P2900X": "Pain Medicine", "208200000X": "Plastic Surgery",
    "208600000X": "General Surgery", "2086S0129X": "Vascular Surgery", "2086X0206X": "Surgical Oncology",
    "2086S0127X": "Trauma Surgery", "2086S0102X": "Surgical Critical Care", "2086S0122X": "Plastic & Reconstructive Surgery",
    "208800000X": "Urology", "208C00000X": "Colon & Rectal Surgery", "208D00000X": "General Practice",
    "208G00000X": "Thoracic & Cardiac Surgery", "208M00000X": "Hospitalist", "208VP0000X": "Pain Medicine",
    "208VP0014X": "Interventional Pain Medicine", "2084N0400X": "Neurology", "2084P0800X": "Psychiatry",
    "2084P0805X": "Geriatric Psychiatry", "2084P0804X": "Child & Adolescent Psychiatry", "2084A0401X": "Addiction Medicine",
    "2084V0102X": "Vascular Neurology", "2084N0008X": "Neuromuscular Medicine", "2084S0012X": "Sleep Medicine",
    "2085R0202X": "Diagnostic Radiology", "2085R0001X": "Radiation Oncology", "2085R0204X": "Interventional Radiology",
    "2085N0904X": "Neuroradiology", "2085R0203X": "Therapeutic Radiology", "2083P0901X": "Preventive Medicine",
    "2083X0100X": "Occupational Medicine", "363L00000X": "Nurse Practitioner", "363LA2200X": "Nurse Practitioner (Adult Health)",
    "363LF0000X": "Nurse Practitioner (Family)", "363LG0600X": "Nurse Practitioner (Gerontology)",
    "363LP0200X": "Nurse Practitioner (Pediatrics)", "363LA2100X": "Nurse Practitioner (Acute Care)",
    "363LX0001X": "Nurse Practitioner (Obstetrics & Gynecology)", "363LP0808X": "Nurse Practitioner (Psychiatric)",
    "363A00000X": "Physician Assistant", "363AM0700X": "Physician Assistant (Medical)",
    "363AS0400X": "Physician Assistant (Surgical)", "213E00000X": "Podiatry", "213ES0103X": "Podiatry (Foot & Ankle Surgery)",
    "213ES0131X": "Podiatry (Foot Surgery)", "213EP1101X": "Podiatry (Primary Care)",
}
TAXONOMY_PREFIX = {
    "207Q": "Family Medicine", "207R": "Internal Medicine", "2080": "Pediatrics", "2084": "Psychiatry & Neurology",
    "2085": "Radiology", "2086": "Surgery", "2083": "Preventive Medicine", "207X": "Orthopedic Surgery",
    "207V": "Obstetrics & Gynecology", "207L": "Anesthesiology", "207Z": "Pathology", "2081": "Physical Medicine & Rehabilitation",
    "363L": "Nurse Practitioner", "363A": "Physician Assistant", "213E": "Podiatry", "208V": "Pain Medicine",
}
PRIMARY_CARE = {"Family Medicine", "Internal Medicine", "General Practice", "Geriatric Medicine", "Pediatrics",
                "Nurse Practitioner", "Physician Assistant", "Hospitalist"}


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def norm_header(h: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (h or "").upper()).strip("_")


def pick(row: dict, *candidates: str, default: str = "") -> str:
    """Return the first non-empty value whose normalized header matches a candidate (exact, then substring)."""
    for c in candidates:
        if c in row and row[c] not in (None, ""):
            return str(row[c]).strip()
    for c in candidates:
        for k, v in row.items():
            if c in k and v not in (None, ""):
                return str(v).strip()
    return default


def normalize_row(row: dict) -> dict:
    return {norm_header(k): (v.strip() if isinstance(v, str) else v) for k, v in row.items() if k is not None}


def clean_name(s: str) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if not s:
        return s
    if s.isupper() or s.islower():
        s = s.title()
        # Keep common acronyms upper case
        s = re.sub(r"\b(Llc|Llp|Inc|Pc|Pa|Md|Do|Snf|Hha|Lp|Ltd|Ii|Iii|Iv|Dba|Usa|Va|Uc|Ucla|Ucsf|Nyu|Ny|Nj|Ct|Ma|Tx|Ca|Fl)\b",
                   lambda m: m.group(1).upper(), s)
        s = s.replace("'S", "'s").replace("Of ", "of ").replace(" And ", " and ").replace(" The ", " the ")
    return s


def zip5(z: str) -> str:
    z = re.sub(r"\D", "", z or "")
    return z[:5] if len(z) >= 5 else z


def safe_int(x) -> int:
    try:
        return int(float(str(x).replace(",", "").strip()))
    except Exception:
        return 0


def safe_float(x):
    try:
        v = float(str(x).replace(",", "").replace("$", "").strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None


def write_json_gz(path: str, obj) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with gzip.open(path, "wb", compresslevel=9) as f:
        f.write(raw)
    return os.path.getsize(path)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, separators=(",", ":"), ensure_ascii=False)


# ----------------------------------------------------------------------------
# Download layer (with on-disk cache)
# ----------------------------------------------------------------------------

class Downloader:
    def __init__(self, cache_dir: str, offline: bool = False):
        self.cache_dir = cache_dir
        self.offline = offline
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, url: str, name: str | None = None) -> str:
        if not name:
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.urlparse(url).path.strip("/"))[-120:] or "index"
        return os.path.join(self.cache_dir, name)

    def fetch(self, url: str, name: str | None = None, retries: int = 4, quiet: bool = False) -> str:
        """Download url to the cache (if not present) and return the local path."""
        path = self._cache_path(url, name)
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        if self.offline:
            raise FileNotFoundError(f"offline and not cached: {url}")
        tmp = path + ".part"
        delay = 2
        for attempt in range(1, retries + 1):
            try:
                if not quiet:
                    log(f"GET {url}")
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                    total = resp.headers.get("Content-Length")
                    total = int(total) if total and total.isdigit() else None
                    done = 0
                    last = time.time()
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        if not quiet and time.time() - last > 5:
                            last = time.time()
                            pct = f" {done * 100 // total}%" if total else ""
                            log(f"   ... {done / 1e6:,.0f} MB{pct}")
                os.replace(tmp, path)
                return path
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError, OSError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404, 410):
                    raise
                if attempt == retries:
                    raise
                log(f"   retry {attempt}/{retries} after error: {e}")
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")

    def fetch_text(self, url: str, name: str | None = None) -> str:
        with open(self.fetch(url, name), "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    def try_fetch(self, url: str, name: str | None = None):
        try:
            return self.fetch(url, name)
        except Exception as e:  # noqa: BLE001
            log(f"   not available: {url} ({e})")
            return None


# ----------------------------------------------------------------------------
# data.cms.gov helpers
# ----------------------------------------------------------------------------

class CmsCatalog:
    """Resolves dataset titles on data.cms.gov to CSV download URLs using the public data.json catalogue."""

    def __init__(self, dl: Downloader):
        self.dl = dl
        self._catalog = None

    def catalog(self):
        if self._catalog is None:
            path = self.dl.try_fetch("https://data.cms.gov/data.json", "cms_data.json")
            self._catalog = []
            if path:
                try:
                    with open(path, encoding="utf-8") as f:
                        self._catalog = json.load(f).get("dataset", [])
                except Exception as e:  # noqa: BLE001
                    log(f"   could not parse data.json: {e}")
        return self._catalog

    @staticmethod
    def _family(title) -> str:
        return (title or "").split(" : ")[0].strip().lower()

    @staticmethod
    def _snapshot_key(d):
        m = re.search(r":\s*(\d{4}(?:-\d{2}-\d{2})?)\s*$", d.get("title", ""))
        return (m.group(1) if m else "", d.get("modified", ""))

    def find(self, title: str):
        """data.cms.gov lists every monthly snapshot as 'Title : YYYY-MM-DD'; return the newest one."""
        t = title.lower()
        fam = [d for d in self.catalog() if self._family(d.get("title")) == t]
        if not fam:
            fam = [d for d in self.catalog() if t in self._family(d.get("title"))]
        if not fam:
            return None
        return max(fam, key=self._snapshot_key)

    def rows(self, key: str, required: bool = True):
        """Return list[dict] rows for a CMS dataset (CSV preferred, API fallback)."""
        title, uuid = CMS_DATASETS[key]
        ds = self.find(title)
        csv_url = None
        if ds:
            dists = ds.get("distribution") or []
            # Prefer a CSV distribution that is not a dated snapshot
            for d in dists:
                url = d.get("downloadURL") or ""
                if url.lower().endswith(".csv") and (d.get("mediaType", "").endswith("csv") or True):
                    csv_url = url
                    break
            if not uuid:
                m = re.search(r"dataset/([0-9a-f-]{36})", (ds.get("identifier") or "") + " " +
                              " ".join(d.get("accessURL", "") for d in dists))
                uuid = m.group(1) if m else None
        rows = []
        if csv_url:
            path = self.dl.try_fetch(csv_url, f"{key}.csv")
            if path:
                with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
                    rows = [normalize_row(r) for r in csv.DictReader(f)]
        if not rows and uuid:
            rows = self.api_rows(uuid, key)
        if not rows and required:
            raise RuntimeError(f"Could not download '{title}'. Pass --offline with cached files or check network access.")
        log(f"   {title}: {len(rows):,} rows")
        return rows

    def api_rows(self, uuid: str, key: str):
        rows = []
        offset, size = 0, 5000
        while True:
            url = f"https://data.cms.gov/data-api/v1/dataset/{uuid}/data?size={size}&offset={offset}"
            path = self.dl.try_fetch(url, f"{key}_api_{offset}.json")
            if not path:
                break
            with open(path, encoding="utf-8") as f:
                try:
                    page = json.load(f)
                except Exception:
                    break
            if not page:
                break
            rows.extend(normalize_row(r) for r in page)
            if len(page) < size:
                break
            offset += size
        return rows


def care_compare_rows(dl: Downloader, dataset_id: str, key: str):
    """Download a Care Compare dataset (data.cms.gov/provider-data) as list[dict]."""
    meta_url = f"https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{dataset_id}?show-reference-ids"
    csv_url = None
    p = dl.try_fetch(meta_url, f"cc_{key}_meta.json")
    if p:
        try:
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
            for d in meta.get("distribution", []):
                url = (d.get("data") or d).get("downloadURL")
                if url:
                    csv_url = url
                    break
        except Exception:  # noqa: BLE001
            pass
    if not csv_url:
        csv_url = f"https://data.cms.gov/provider-data/api/1/datastore/query/{dataset_id}/0/download?format=csv"
    path = dl.try_fetch(csv_url, f"cc_{key}.csv")
    if not path:
        return []
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        return [normalize_row(r) for r in csv.DictReader(f)]


# ----------------------------------------------------------------------------
# Provider table
# ----------------------------------------------------------------------------

class Provider:
    __slots__ = ("npi", "ccn", "name", "type", "address", "city", "state", "zip", "specialty",
                 "rating", "pac_benes", "pac_pay", "pac_stays")

    def __init__(self, npi, ccn, name, type_, address, city, state, zip_, specialty=""):
        self.npi = npi
        self.ccn = ccn
        self.name = name
        self.type = type_
        self.address = address
        self.city = city
        self.state = state
        self.zip = zip_
        self.specialty = specialty
        self.rating = None
        self.pac_benes = None
        self.pac_pay = None
        self.pac_stays = None

    def profile(self):
        # Compact positional profile used in data files:
        # [npi, type, name, city, state, zip, specialty, ccn, address, rating, pac_benes, pac_pay, pac_stays]
        return [self.npi, self.type, self.name, self.city, self.state, self.zip, self.specialty, self.ccn,
                self.address, self.rating, self.pac_benes, self.pac_pay, self.pac_stays]


PROFILE_COLS = ["npi", "type", "name", "city", "state", "zip", "specialty", "ccn", "address", "rating",
                "pac_benes", "pac_payments", "pac_stays"]


def hospital_subtype(row: dict, ccn: str) -> str:
    """Classify a hospital enrollment row as H (acute/general), R (rehab) or L (LTCH)."""
    def flag(*names):
        return any(str(row.get(n, "")).upper().startswith("Y") for n in names)
    if flag("SUBGROUP_GENERAL", "SUBGROUP_ACUTE_CARE", "SUBGROUP_SHORT_TERM"):
        return "H"
    if flag("SUBGROUP_REHABILITATION"):
        return "R"
    if flag("SUBGROUP_LONG_TERM"):
        return "L"
    tail = re.sub(r"\D", "", ccn or "")[-4:]
    if tail.isdigit():
        n = int(tail)
        if 3025 <= n <= 3099:
            return "R"
        if 2000 <= n <= 2299:
            return "L"
    return "H"


def load_facilities(cat: CmsCatalog, states_filter) -> tuple[dict, dict]:
    """Returns (providers_by_npi, alias_map) for hospitals, SNFs, HHAs and hospices."""
    providers: dict[int, Provider] = {}
    alias: dict[int, int] = {}
    sources = [("hospital_enroll", "H"), ("snf_enroll", "S"), ("hha_enroll", "A"), ("hospice_enroll", "C")]
    for key, code in sources:
        log(f"Loading {CMS_DATASETS[key][0]} ...")
        for r in cat.rows(key):
            npi = re.sub(r"\D", "", pick(r, "NPI"))
            if len(npi) != 10:
                continue
            state = pick(r, "STATE", "PRACTICE_LOCATION_STATE", "ENROLLMENT_STATE").upper()[:2]
            if states_filter and state not in states_filter:
                continue
            ccn = pick(r, "CCN", "PROVIDER_ID", "MEDICARE_ID")
            name = clean_name(pick(r, "DOING_BUSINESS_AS_NAME") or pick(r, "ORGANIZATION_NAME", "PROVIDER_NAME"))
            if not name:
                continue
            loc = pick(r, "PRACTICE_LOCATION_TYPE").upper()
            if int(npi) in providers and loc and "MAIN" not in loc and "PRIMARY" not in loc:
                continue  # keep the main location already recorded
            t = hospital_subtype(r, ccn) if code == "H" else code
            p = Provider(int(npi), ccn, name, t,
                         clean_name(pick(r, "ADDRESS_LINE_1", "ADDRESS")), clean_name(pick(r, "CITY")),
                         state, zip5(pick(r, "ZIP_CODE", "ZIP")))
            providers[p.npi] = p
    # Additional NPIs for the same enrollment -> alias to the primary NPI
    enroll_to_primary = {}
    for key in ("hospital_enroll", "snf_enroll", "hha_enroll", "hospice_enroll"):
        for r in cat.rows(key, required=False):
            eid, npi = pick(r, "ENROLLMENT_ID"), re.sub(r"\D", "", pick(r, "NPI"))
            if eid and len(npi) == 10 and int(npi) in providers:
                enroll_to_primary[eid] = int(npi)
    for key in ("hospital_npis", "snf_npis", "hha_npis", "hospice_npis"):
        try:
            rows = cat.rows(key, required=False)
        except Exception:  # noqa: BLE001
            rows = []
        for r in rows:
            eid, npi = pick(r, "ENROLLMENT_ID"), re.sub(r"\D", "", pick(r, "NPI"))
            if eid in enroll_to_primary and len(npi) == 10:
                extra = int(npi)
                if extra != enroll_to_primary[eid] and extra not in providers:
                    alias[extra] = enroll_to_primary[eid]
    log(f"   facilities: {len(providers):,}  (additional NPIs mapped: {len(alias):,})")
    return providers, alias


def load_taxonomy(cat: CmsCatalog) -> dict:
    tax = dict(TAXONOMY)
    try:
        for r in cat.rows("taxonomy", required=False):
            code = pick(r, "PROVIDER_TAXONOMY_CODE", "TAXONOMY_CODE")
            desc = pick(r, "PROVIDER_TAXONOMY_DESCRIPTION_TYPE_CLASSIFICATION_SPECIALIZATION", "TAXONOMY_DESCRIPTION",
                        "MEDICARE_SPECIALTY_CODE_DESCRIPTION")
            if code and desc and code not in tax:
                # "Allopathic & Osteopathic Physicians/Internal Medicine, Cardiovascular Disease" -> last segment
                tax[code] = clean_name(desc.split("/")[-1].strip())
    except Exception as e:  # noqa: BLE001
        log(f"   taxonomy crosswalk not used: {e}")
    return tax


def specialty_for(code: str, tax: dict) -> str:
    if code in tax:
        return tax[code]
    for n in (4, 3):
        if code[:n] in TAXONOMY_PREFIX:
            return TAXONOMY_PREFIX[code[:n]]
    return "Other specialist"


def nppes_zip_url(dl: Downloader) -> str:
    page = dl.fetch_text(NPPES_INDEX, "NPI_Files.html")
    m = re.findall(r'href=[\'"]\.?/?(NPPES_Data_Dissemination_[A-Za-z]+_\d{4}(?:_V\d+)?\.zip)[\'"]', page)
    if not m:
        raise RuntimeError("Could not find the NPPES monthly file link on " + NPPES_INDEX)
    # The first full-replacement file is the current month
    return "https://download.cms.gov/nppes/" + m[0]


def load_doctors(dl: Downloader, keep_npis: set, providers: dict, tax: dict, states_filter, include_app: bool,
                 nppes_path: str | None = None) -> int:
    """Stream the NPPES dissemination zip and add individual clinicians whose NPI appears in the flow data."""
    path = nppes_path or dl.fetch(nppes_zip_url(dl), "nppes.zip")
    log(f"Streaming NPPES from {path} (this is a 9+ GB CSV inside the zip; takes a while) ...")
    added = 0
    with zipfile.ZipFile(path) as zf:
        members = [n for n in zf.namelist() if n.lower().startswith("npidata_pfile") and "fileheader" not in n.lower()
                   and n.lower().endswith(".csv")]
        if not members:
            raise RuntimeError("npidata_pfile CSV not found inside NPPES zip")
        with zf.open(members[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
            reader = csv.reader(text)
            header = [norm_header(h) for h in next(reader)]
            idx = {h: i for i, h in enumerate(header)}

            def col(name, default=None):
                return idx.get(name, default)

            i_npi = col("NPI")
            i_ent = col("ENTITY_TYPE_CODE")
            i_last = col("PROVIDER_LAST_NAME_LEGAL_NAME")
            i_first = col("PROVIDER_FIRST_NAME")
            i_cred = col("PROVIDER_CREDENTIAL_TEXT")
            i_addr = col("PROVIDER_FIRST_LINE_BUSINESS_PRACTICE_LOCATION_ADDRESS")
            i_city = col("PROVIDER_BUSINESS_PRACTICE_LOCATION_ADDRESS_CITY_NAME")
            i_state = col("PROVIDER_BUSINESS_PRACTICE_LOCATION_ADDRESS_STATE_NAME")
            i_zip = col("PROVIDER_BUSINESS_PRACTICE_LOCATION_ADDRESS_POSTAL_CODE")
            i_deact = col("NPI_DEACTIVATION_DATE")
            tax_cols = [(idx[f"HEALTHCARE_PROVIDER_TAXONOMY_CODE_{k}"], idx.get(f"HEALTHCARE_PROVIDER_PRIMARY_TAXONOMY_SWITCH_{k}"))
                        for k in range(1, 16) if f"HEALTHCARE_PROVIDER_TAXONOMY_CODE_{k}" in idx]
            n = 0
            for row in reader:
                n += 1
                if n % 1_000_000 == 0:
                    log(f"   ... {n:,} NPPES rows, {added:,} clinicians kept")
                try:
                    npi = int(row[i_npi])
                except (ValueError, IndexError):
                    continue
                if npi not in keep_npis or npi in providers:
                    continue
                if row[i_ent] != "1":
                    continue
                if i_deact is not None and row[i_deact]:
                    continue
                state = (row[i_state] or "").upper()[:2]
                if states_filter and state not in states_filter:
                    continue
                primary, first_code = None, None
                for ci, si in tax_cols:
                    code = row[ci]
                    if not code:
                        continue
                    first_code = first_code or code
                    if si is not None and row[si] == "Y":
                        primary = code
                        break
                code = primary or first_code or ""
                ok = code.startswith("20") or (include_app and (code.startswith("363") or code.startswith("213E")))
                if not ok:
                    continue
                name = f"{clean_name(row[i_first])} {clean_name(row[i_last])}".strip()
                cred = re.sub(r"[.\s]", "", row[i_cred] or "").upper()[:12]
                if cred:
                    name = f"{name}, {cred}"
                providers[npi] = Provider(npi, "", name, "D", clean_name(row[i_addr]), clean_name(row[i_city]),
                                          state, zip5(row[i_zip]), specialty_for(code, tax))
                added += 1
    log(f"   doctors added: {added:,}")
    return added


def attach_volume_context(cat: CmsCatalog, dl: Downloader, providers: dict) -> dict:
    """Join PAC utilization (by CCN) and Care Compare star ratings (by CCN) onto facilities."""
    info = {"pac_year": None, "ratings": {}}
    by_ccn = collections.defaultdict(list)
    for p in providers.values():
        if p.type != "D" and p.ccn:
            by_ccn[re.sub(r"\D", "", p.ccn).zfill(6)].append(p)
    # PAC utilization (one file per setting; rows are NATION / STATE / PROVIDER level)
    rows = []
    for key in ("pac_snf", "pac_hos", "pac_hh", "pac_irf", "pac_ltc"):
        try:
            rows.extend(cat.rows(key, required=False))
        except Exception as e:  # noqa: BLE001
            log(f"   {key} skipped: {e}")
    joined = 0
    years = collections.Counter()
    for r in rows:
        ccn_raw = pick(r, "PRVDR_ID", "PROVIDER_ID", "CCN")
        if not re.fullmatch(r"[0-9A-Za-z]{6}", ccn_raw or ""):
            continue  # NATIONAL TOTAL / STATE TOTAL rows
        ccn = re.sub(r"\D", "", ccn_raw).zfill(6)
        if ccn not in by_ccn:
            continue
        year = pick(r, "YEAR", "RFRNC_YR", "PERIOD")
        years[year] += 1
        benes = safe_int(pick(r, "BENE_DSTNCT_CNT", "DISTINCT_BENEFICIARIES", "TOT_BENES"))
        pay = safe_float(pick(r, "TOT_MDCR_PYMT_AMT", "TOTAL_MEDICARE_PAYMENT_AMOUNT"))
        stays = safe_int(pick(r, "TOT_EPSD_STAY_CNT", "TOT_STAYS", "TOTAL_EPISODES", "TOT_EPSDS"))
        for p in by_ccn[ccn]:
            p.pac_benes = benes or None
            p.pac_pay = round(pay) if pay else None
            p.pac_stays = stays or None
            joined += 1
    if years:
        info["pac_year"] = years.most_common(1)[0][0]
    log(f"   PAC utilization joined to {joined:,} facilities (year {info['pac_year']})")
    # Care Compare ratings
    for code, ds_id in CARE_COMPARE.items():
        rows = care_compare_rows(dl, ds_id, code)
        got = 0
        for r in rows:
            ccn = re.sub(r"\D", "", pick(r, "CMS_CERTIFICATION_NUMBER_CCN", "FACILITY_ID", "FEDERAL_PROVIDER_NUMBER",
                                          "PROVIDER_ID", "CCN")).zfill(6)
            rating = pick(r, "OVERALL_RATING", "HOSPITAL_OVERALL_RATING", "QUALITY_OF_PATIENT_CARE_STAR_RATING",
                          "FAMILY_CAREGIVER_SURVEY_RATING", "STAR_RATING")
            rv = safe_float(rating)
            if ccn in by_ccn and rv:
                for p in by_ccn[ccn]:
                    if p.type in (code, "R", "L") if code == "H" else p.type == code:
                        p.rating = rv
                        got += 1
        info["ratings"][code] = got
        log(f"   Care Compare {TYPES[code]} ratings joined: {got:,}")
    return info


# ----------------------------------------------------------------------------
# Flow files
# ----------------------------------------------------------------------------

def pspp_candidates(year: int, window: int):
    base = f"https://data.nber.org/physician-shared-patient-patterns/{year}/"
    return [
        base + f"physician-shared-patient-patterns-{year}-days{window}.zip",
        base + f"pspp{year}_{window}.csv.zip",
        base + f"pspp{year}_{window}.zip",
        base + f"physician-shared-patient-patterns-{year}-days{window}.txt.zip",
    ]


def fetch_pspp(dl: Downloader, year: int, window: int, url: str | None) -> str:
    if url:
        return dl.fetch(url, f"pspp_{year}_{window}" + os.path.splitext(url)[1])
    for cand in pspp_candidates(year, window):
        p = dl.try_fetch(cand, f"pspp_{year}_{window}" + os.path.splitext(cand)[1])
        if p:
            return p
    raise RuntimeError(
        f"Could not download the {year} {window}-day Physician Shared Patient Patterns file.\n"
        f"Browse https://data.nber.org/physician-shared-patient-patterns/{year}/ and pass the zip with --pspp-url, "
        f"or a local copy with --flows-file.")


def iter_flow_rows(path: str):
    """Yield (src_npi:int, dst_npi:int, patients:int) from a PSPP file (zip/gz/csv/txt) or a generic flows CSV.

    PSPP layout: npi1, npi2, pair_count (claims), bene_count (unique patients), same_day_count.
    Generic layout (header required): source_npi, dest_npi, patients[, ...]
    """
    def open_lines():
        lower = path.lower()
        if lower.endswith(".zip"):
            zf = zipfile.ZipFile(path)
            members = [n for n in zf.namelist() if not n.endswith("/")]
            members.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
            return io.TextIOWrapper(zf.open(members[0]), encoding="utf-8", errors="replace", newline="")
        if lower.endswith(".gz"):
            return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline="")
        return open(path, encoding="utf-8", errors="replace", newline="")

    with open_lines() as f:
        first = f.readline()
        if not first:
            return
        cols = [c.strip().strip('"').lower() for c in first.split(",")]
        generic = False
        if not cols[0].isdigit():
            # header row
            generic = any(c in ("source_npi", "src_npi", "from_npi", "referring_npi") for c in cols)
            hdr = cols
            si = next((i for i, c in enumerate(hdr) if c in ("source_npi", "src_npi", "from_npi", "referring_npi", "npi1", "npi_1")), 0)
            di = next((i for i, c in enumerate(hdr) if c in ("dest_npi", "dst_npi", "to_npi", "referred_npi", "npi2", "npi_2")), 1)
            pi = next((i for i, c in enumerate(hdr) if c in ("patients", "bene_count", "benes", "unique_patients", "shared_patients", "beneficiaries")), None)
            if pi is None:
                pi = 3 if len(hdr) >= 4 and not generic else 2
        else:
            si, di, pi = 0, 1, 3
            yield from _parse_line(first, si, di, pi)
        for line in f:
            yield from _parse_line(line, si, di, pi)


def _parse_line(line: str, si: int, di: int, pi: int):
    parts = line.split(",")
    if len(parts) <= max(si, di, pi):
        return
    try:
        a = int(parts[si].strip().strip('"'))
        b = int(parts[di].strip().strip('"'))
        n = int(float(parts[pi].strip().strip('"')))
    except ValueError:
        return
    if n > 0 and a != b:
        yield a, b, n


def scan_npis(path: str) -> tuple[set, int]:
    log(f"Pass 1: scanning NPIs in {path} ...")
    seen = set()
    n = 0
    for a, b, _ in iter_flow_rows(path):
        seen.add(a)
        seen.add(b)
        n += 1
        if n % 5_000_000 == 0:
            log(f"   ... {n:,} pairs, {len(seen):,} NPIs")
    log(f"   {n:,} pairs, {len(seen):,} distinct NPIs")
    return seen, n


class TopList:
    """Fixed-size top-N by value (min-heap)."""

    def __init__(self, n: int):
        self.n = n
        self.h = []
        self.c = 0

    def add(self, value, item):
        self.c += 1
        if len(self.h) < self.n:
            heapq.heappush(self.h, (value, self.c, item))
        elif value > self.h[0][0]:
            heapq.heapreplace(self.h, (value, self.c, item))

    def items(self):
        return [it for _, _, it in sorted(self.h, key=lambda x: -x[0])]


def process_flows(path: str, providers: dict, alias: dict, args, work_dir: str):
    """Pass 2: aggregate flows, write shard temp files and per-state temp files, return totals and top lists."""
    log("Pass 2: aggregating flows ...")
    shards = args.shards
    out_tot = collections.Counter()
    in_tot = collections.Counter()
    out_partners = collections.Counter()
    in_partners = collections.Counter()
    pair_tops = collections.defaultdict(lambda: TopList(args.top_lists))
    facility_pairs = {}  # (a,b)->n for growth analysis (facility-involved only)

    shard_dir = os.path.join(work_dir, "shards")
    state_dir = os.path.join(work_dir, "states")
    for d in (shard_dir, state_dir):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    shard_buf = collections.defaultdict(list)
    state_buf = collections.defaultdict(list)
    buffered = 0

    def flush():
        nonlocal buffered
        for s, lines in shard_buf.items():
            with open(os.path.join(shard_dir, f"{s}.tsv"), "a", encoding="ascii") as f:
                f.write("".join(lines))
        for st, lines in state_buf.items():
            with open(os.path.join(state_dir, f"{st}.tsv"), "a", encoding="ascii") as f:
                f.write("".join(lines))
        shard_buf.clear()
        state_buf.clear()
        buffered = 0

    n_rows = n_kept = 0
    for a, b, n in iter_flow_rows(path):
        n_rows += 1
        if n_rows % 5_000_000 == 0:
            log(f"   ... {n_rows:,} pairs read, {n_kept:,} kept")
        a = alias.get(a, a)
        b = alias.get(b, b)
        if a == b or n < args.min_patients:
            continue
        pa = providers.get(a)
        pb = providers.get(b)
        if pa is None or pb is None:
            continue
        n_kept += 1
        out_tot[a] += n
        in_tot[b] += n
        out_partners[a] += 1
        in_partners[b] += 1
        shard_buf[a % shards].append(f"o\t{a}\t{b}\t{n}\n")
        shard_buf[b % shards].append(f"i\t{b}\t{a}\t{n}\n")
        if pa.type != "D" or pb.type != "D" or n >= args.dd_min:
            state_buf[pa.state or "XX"].append(f"{a}\t{b}\t{n}\n")
        if pa.type != "D" or pb.type != "D":
            pair_tops[f"{pa.type}>{pb.type}"].add(n, (a, b, n))
            if n >= args.growth_min:
                facility_pairs[(a, b)] = n
        buffered += 2
        if buffered >= 2_000_000:
            flush()
    flush()
    log(f"   {n_rows:,} pairs read, {n_kept:,} kept between known providers")
    return {
        "out_tot": out_tot, "in_tot": in_tot, "out_partners": out_partners, "in_partners": in_partners,
        "pair_tops": pair_tops, "facility_pairs": facility_pairs, "n_rows": n_rows, "n_kept": n_kept,
        "shard_dir": shard_dir, "state_dir": state_dir,
    }


def prior_year_pairs(path: str, alias: dict, wanted: dict) -> dict:
    log("Prior year: reading pairs for growth analysis ...")
    prev = {}
    for a, b, n in iter_flow_rows(path):
        a = alias.get(a, a)
        b = alias.get(b, b)
        if (a, b) in wanted:
            prev[(a, b)] = prev.get((a, b), 0) + n
    log(f"   matched {len(prev):,} of {len(wanted):,} relationships in the prior year")
    return prev


# ----------------------------------------------------------------------------
# Output writers
# ----------------------------------------------------------------------------

def flow_row(p: Provider, n: int, total: int):
    # [npi, type, name, city, state, specialty, patients, share%]
    share = round(100.0 * n / total, 1) if total else 0
    return [p.npi, p.type, p.name, p.city, p.state, p.specialty, n, share]


def write_provider_shards(providers: dict, agg: dict, args, out_dir: str):
    log("Writing provider shards ...")
    shards = args.shards
    by_shard = collections.defaultdict(list)
    for npi in providers:
        by_shard[npi % shards].append(npi)
    out_tot, in_tot = agg["out_tot"], agg["in_tot"]
    total_bytes = 0
    for s in range(shards):
        path = os.path.join(agg["shard_dir"], f"{s}.tsv")
        outs = collections.defaultdict(collections.Counter)
        ins = collections.defaultdict(collections.Counter)
        if os.path.exists(path):
            with open(path, encoding="ascii") as f:
                for line in f:
                    d, x, y, n = line.rstrip("\n").split("\t")
                    (outs if d == "o" else ins)[int(x)][int(y)] += int(n)
        payload = {}
        for npi in by_shard[s]:
            p = providers[npi]
            o = outs.get(npi, {})
            i = ins.get(npi, {})
            o_rows = [flow_row(providers[b], n, out_tot[npi]) for b, n in sorted(o.items(), key=lambda kv: -kv[1])[:args.top]]
            i_rows = [flow_row(providers[a], n, in_tot[npi]) for a, n in sorted(i.items(), key=lambda kv: -kv[1])[:args.top]]
            payload[str(npi)] = {
                "p": p.profile(),
                "t": [out_tot[npi], in_tot[npi], agg["out_partners"][npi], agg["in_partners"][npi]],
                "out": o_rows,
                "in": i_rows,
            }
        if payload:
            total_bytes += write_json_gz(os.path.join(out_dir, "providers", f"{s}.json.gz"), payload)
    log(f"   {shards} shards, {total_bytes / 1e6:,.1f} MB")


def write_lists(providers: dict, agg: dict, args, out_dir: str):
    log("Writing state lists and search indexes ...")
    out_tot, in_tot = agg["out_tot"], agg["in_tot"]
    fac_by_state = collections.defaultdict(list)
    doc_by_state = collections.defaultdict(list)
    fac_index = []
    for p in providers.values():
        if p.type == "D":
            doc_by_state[p.state].append([p.npi, p.name, p.specialty, p.city, p.zip, out_tot[p.npi], in_tot[p.npi]])
        else:
            fac_by_state[p.state].append([p.npi, p.type, p.name, p.city, p.zip, p.ccn, p.rating, p.pac_benes,
                                          out_tot[p.npi], in_tot[p.npi]])
            fac_index.append([p.npi, p.type, p.name, p.city, p.state, p.zip])
    states = []
    for st in sorted(set(fac_by_state) | set(doc_by_state)):
        facs = sorted(fac_by_state.get(st, []), key=lambda r: (-(r[8] + r[9]), r[2]))
        docs = sorted(doc_by_state.get(st, []), key=lambda r: (-(r[5] + r[6]), r[1]))
        if facs:
            write_json_gz(os.path.join(out_dir, "facilities", f"{st}.json.gz"),
                          {"cols": ["npi", "type", "name", "city", "zip", "ccn", "rating", "pac_benes", "out", "in"], "rows": facs})
        if docs:
            write_json_gz(os.path.join(out_dir, "doctors", f"{st}.json.gz"),
                          {"cols": ["npi", "name", "specialty", "city", "zip", "out", "in"], "rows": docs})
        counts = collections.Counter(r[1] for r in facs)
        states.append({"st": st, "name": STATES.get(st, st), "H": counts["H"] + counts["R"] + counts["L"],
                       "S": counts["S"], "A": counts["A"], "C": counts["C"], "D": len(docs)})
    fac_index.sort(key=lambda r: r[2])
    write_json_gz(os.path.join(out_dir, "search", "facilities.json.gz"),
                  {"cols": ["npi", "type", "name", "city", "state", "zip"], "rows": fac_index})
    return states


def write_state_flows(providers: dict, agg: dict, args, out_dir: str):
    log("Writing state flow tables ...")
    out_tot = agg["out_tot"]
    total = 0
    for fn in sorted(os.listdir(agg["state_dir"])):
        st = fn[:-4]
        pairs = collections.Counter()
        with open(os.path.join(agg["state_dir"], fn), encoding="ascii") as f:
            for line in f:
                a, b, n = line.rstrip("\n").split("\t")
                pairs[(int(a), int(b))] += int(n)
        rows = []
        for (a, b), n in pairs.most_common(args.flows_cap):
            pa, pb = providers[a], providers[b]
            rows.append([a, pa.type, pa.name, pa.city, b, pb.type, pb.name, pb.city, pb.state, n,
                         round(100.0 * n / out_tot[a], 1) if out_tot[a] else 0])
        total += len(rows)
        write_json_gz(os.path.join(out_dir, "flows", f"{st}.json.gz"),
                      {"cols": ["src_npi", "src_type", "src_name", "src_city", "dst_npi", "dst_type", "dst_name",
                                "dst_city", "dst_state", "patients", "share"], "rows": rows})
    log(f"   {total:,} flow rows across state files")


def write_trending(providers: dict, agg: dict, prev_pairs: dict | None, args, out_dir: str):
    log("Writing trending lists ...")
    out_tot, in_tot = agg["out_tot"], agg["in_tot"]
    k = args.top_lists

    def card(p: Provider, value, extra=None):
        return {"npi": p.npi, "type": p.type, "name": p.name, "city": p.city, "state": p.state,
                "specialty": p.specialty, "value": value, **(extra or {})}

    referrers, receivers = {}, {}
    for t in TYPES:
        top = TopList(k)
        for npi, v in out_tot.items():
            if providers[npi].type == t:
                top.add(v, npi)
        referrers[t] = [card(providers[n], out_tot[n], {"partners": agg["out_partners"][n]}) for n in top.items()]
        top = TopList(k)
        for npi, v in in_tot.items():
            if providers[npi].type == t:
                top.add(v, npi)
        receivers[t] = [card(providers[n], in_tot[n], {"partners": agg["in_partners"][n]}) for n in top.items()]

    pairs = {}
    for key, top in agg["pair_tops"].items():
        pairs[key] = [{"src": card(providers[a], n), "dst": card(providers[b], n), "patients": n,
                       "share": round(100.0 * n / out_tot[a], 1) if out_tot[a] else 0} for a, b, n in top.items()]

    growth = []
    if prev_pairs is not None:
        cur = agg["facility_pairs"]
        scored = []
        for (a, b), n in cur.items():
            pv = prev_pairs.get((a, b))
            if pv and pv >= args.min_patients:
                scored.append((n - pv, (n - pv) / pv, a, b, n, pv))
        scored.sort(key=lambda x: -x[0])
        growth = [{"src": card(providers[a], n), "dst": card(providers[b], n), "patients": n, "prior": pv,
                   "change": d, "pct": round(100.0 * pct, 1)} for d, pct, a, b, n, pv in scored[:k]]
        new_rel = [(n, a, b) for (a, b), n in cur.items() if (a, b) not in prev_pairs]
        new_rel.sort(reverse=True)
        growth_new = [{"src": card(providers[a], n), "dst": card(providers[b], n), "patients": n}
                      for n, a, b in new_rel[:k]]
    else:
        growth_new = []
    write_json(os.path.join(out_dir, "trending.json"),
               {"referrers": referrers, "receivers": receivers, "pairs": pairs, "growth": growth, "new": growth_new})


def write_meta(providers: dict, agg: dict, states, args, out_dir: str, extra: dict):
    counts = collections.Counter(p.type for p in providers.values())
    meta = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "year": args.year,
        "window_days": args.window,
        "flows_label": args.flows_label or f"CMS Physician Shared Patient Patterns, {args.year}, {args.window}-day window",
        "prior_year": args.prior_year,
        "prior_note": ("The 2015 file covers January through September 2015 while 2014 covers the full year, "
                       "so year-over-year changes understate growth.") if (args.year == 2015 and args.prior_year == 2014 and not args.demo) else "",
        "min_patients": args.min_patients,
        "dd_min": args.dd_min,
        "top": args.top,
        "growth_min": args.growth_min,
        "shards": args.shards,
        "demo": bool(args.demo),
        "types": TYPES,
        "counts": {t: counts[t] for t in TYPES},
        "pairs_total": agg["n_rows"],
        "pairs_kept": agg["n_kept"],
        "states": states,
        "profile_cols": PROFILE_COLS,
        "flow_cols": ["npi", "type", "name", "city", "state", "specialty", "patients", "share"],
        **extra,
    }
    write_json(os.path.join(out_dir, "meta.json"), meta)
    return meta


# ----------------------------------------------------------------------------
# Demo data (synthetic) - exercises the exact same pipeline without downloads
# ----------------------------------------------------------------------------

DEMO_STATES = ["NY", "NJ", "CT", "FL", "TX", "CA"]
DEMO_CITIES = {
    "NY": ["Brooklyn", "Bronx", "Queens", "Manhattan", "Staten Island", "Yonkers", "Rochester", "Buffalo", "Albany", "Syracuse"],
    "NJ": ["Newark", "Jersey City", "Lakewood", "Paterson", "Edison", "Toms River", "Trenton", "Cherry Hill", "Clifton", "Hackensack"],
    "CT": ["Hartford", "New Haven", "Stamford", "Bridgeport", "Waterbury", "Norwalk", "Danbury", "Greenwich"],
    "FL": ["Miami", "Tampa", "Orlando", "Jacksonville", "Boca Raton", "Fort Lauderdale", "Naples", "Sarasota", "Clearwater", "Hialeah"],
    "TX": ["Houston", "Dallas", "San Antonio", "Austin", "Fort Worth", "El Paso", "Plano", "Arlington", "Lubbock", "McAllen"],
    "CA": ["Los Angeles", "San Diego", "San Jose", "Sacramento", "Fresno", "Oakland", "Long Beach", "Anaheim", "Riverside", "Bakersfield"],
}
DEMO_FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth", "William",
              "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Daniel", "Karen", "Wei", "Priya",
              "Carlos", "Maria", "Ahmed", "Fatima", "Yosef", "Rivka", "Chen", "Olga", "Samuel", "Rachel", "Anthony", "Nancy"]
DEMO_LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Cohen",
             "Patel", "Kim", "Nguyen", "Lee", "Goldberg", "Friedman", "Schwartz", "Rosenberg", "Shapiro", "Chen", "Singh",
             "Khan", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Taylor", "Moore", "Jackson", "Martin", "Thompson"]
DEMO_SPECIALTIES = ["Internal Medicine", "Family Medicine", "Cardiology", "Orthopedic Surgery", "Neurology", "Pulmonary Disease",
                    "Nephrology", "Geriatric Medicine", "Hospitalist", "Physical Medicine & Rehabilitation", "General Surgery",
                    "Gastroenterology", "Infectious Disease", "Hematology & Oncology", "Nurse Practitioner", "Podiatry",
                    "Urology", "Endocrinology", "Psychiatry", "Vascular Surgery", "Emergency Medicine", "Wound Care"]
DEMO_FAC_WORDS = {
    "H": (["{city} General Hospital", "{city} Medical Center", "St. {saint} Hospital", "Mount {saint} Medical Center",
           "{city} University Hospital", "Memorial Hospital of {city}", "{city} Regional Medical Center", "Good Samaritan Hospital - {city}"]),
    "R": (["{city} Rehabilitation Hospital", "Encompass Health of {city}", "{city} Institute for Rehabilitation"]),
    "L": (["{city} Specialty Hospital", "Kindred Hospital {city}"]),
    "S": (["{city} Center for Rehabilitation and Nursing", "{saint} Manor Nursing Home", "The {saint} Pavilion", "{city} Gardens Care Center",
           "{saint} Hills Health Care Center", "Golden {saint} Nursing & Rehab", "{city} Park Rehabilitation Center", "Oceanview Nursing Home of {city}",
           "{saint} Oaks Skilled Nursing", "{city} Heights Rehabilitation", "Riverside Nursing Home - {city}", "Harmony Village at {city}"]),
    "A": (["{city} Home Care", "VNS of {city}", "{saint} Home Health Services", "Caring Hands Home Health - {city}", "Premier Home Care of {city}",
           "Amedisys Home Health of {city}", "{city} Visiting Nurse Association", "Comfort Home Health {city}"]),
    "C": (["{city} Hospice Care", "{saint} Hospice", "Compassionate Care Hospice of {city}", "VITAS Healthcare - {city}", "Hospice of {city}"]),
}
DEMO_SAINTS = ["Mary", "Joseph", "Luke", "Francis", "Vincent", "Anne", "Elizabeth", "Michael", "Peter", "Sinai", "Carmel", "Jude"]


def demo_build(args, work_dir: str):
    rnd = random.Random(42)
    providers: dict[int, Provider] = {}
    used = set()

    def new_npi():
        while True:
            n = rnd.randint(1000000000, 1999999999)
            if n not in used:
                used.add(n)
                return n

    def addr():
        return f"{rnd.randint(10, 9999)} {rnd.choice(['Main', 'Oak', 'Park', 'Church', 'Ocean', 'Bedford', 'Union', 'Maple'])} {rnd.choice(['St', 'Ave', 'Blvd', 'Rd'])}"

    def zipc(st):
        base = {"NY": 10, "NJ": 7, "CT": 6, "FL": 33, "TX": 77, "CA": 90}[st]
        return f"{base:02d}{rnd.randint(0, 999):03d}"

    def mk_fac(st, t, city):
        tpl = rnd.choice(DEMO_FAC_WORDS[t])
        name = tpl.format(city=city, saint=rnd.choice(DEMO_SAINTS))
        ccn_mid = {"H": rnd.randint(1, 879), "R": rnd.randint(3025, 3099), "L": rnd.randint(2000, 2299),
                   "S": rnd.randint(5000, 6499), "A": rnd.randint(7000, 7999), "C": rnd.randint(1500, 1799)}[t]
        ccn = f"{rnd.randint(10, 67):02d}{ccn_mid:04d}"
        p = Provider(new_npi(), ccn, name, t, addr(), city, st, zipc(st))
        if t != "L":
            p.rating = float(rnd.choice([1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5]))
        if t in ("S", "A", "C"):
            p.pac_benes = rnd.randint(80, 1600)
            p.pac_pay = p.pac_benes * rnd.randint(6000, 24000)
            p.pac_stays = int(p.pac_benes * rnd.uniform(1.0, 1.6))
        providers[p.npi] = p
        return p

    per_state = {}
    for st in DEMO_STATES:
        cities = DEMO_CITIES[st]
        facs = {t: [] for t in FACILITY_TYPES}
        counts = {"H": 14, "R": 3, "L": 2, "S": 46, "A": 26, "C": 12}
        for t, c in counts.items():
            for _ in range(c):
                facs[t].append(mk_fac(st, t, rnd.choice(cities)))
        docs = []
        for _ in range(320):
            spec = rnd.choice(DEMO_SPECIALTIES)
            cred = "NP" if spec == "Nurse Practitioner" else ("DPM" if spec == "Podiatry" else rnd.choice(["MD", "MD", "MD", "DO"]))
            name = f"{rnd.choice(DEMO_FIRST)} {rnd.choice(DEMO_LAST)}, {cred}"
            p = Provider(new_npi(), "", name, "D", addr(), rnd.choice(cities), st, zipc(st), spec)
            providers[p.npi] = p
            docs.append(p)
        per_state[st] = (facs, docs)

    # Synthetic flows: one list of relationships, written as PSPP-style CSV for the current
    # and prior year (prior = scaled down, ~12% of relationships missing so they show up as "new").
    pairs = []

    def send(src, pool, k, lo, hi):
        for d in rnd.sample(pool, min(k, len(pool))):
            pairs.append((src.npi, d.npi, rnd.randint(lo, hi)))

    for st, (facs, docs) in per_state.items():
        for h in facs["H"]:
            send(h, facs["S"], rnd.randint(10, 22), 12, 420)
            send(h, facs["A"], rnd.randint(8, 16), 12, 380)
            send(h, facs["C"], rnd.randint(4, 9), 11, 160)
            send(h, facs["R"] + facs["L"], rnd.randint(2, 4), 11, 140)
            send(h, docs, rnd.randint(40, 90), 11, 260)
        for r in facs["R"] + facs["L"]:
            send(r, facs["S"], rnd.randint(4, 8), 11, 90)
            send(r, facs["A"], rnd.randint(3, 7), 11, 90)
        for d in docs:
            send(d, facs["H"], rnd.randint(1, 4), 11, 220)
            send(d, facs["S"], rnd.randint(1, 6), 11, 120)
            send(d, facs["A"], rnd.randint(1, 5), 11, 110)
            send(d, facs["C"], rnd.randint(0, 2), 11, 60)
            send(d, docs, rnd.randint(8, 25), 11, 160)
        for s in facs["S"]:
            send(s, facs["A"], rnd.randint(1, 4), 11, 60)
            send(s, facs["C"], rnd.randint(1, 3), 11, 50)
            send(s, facs["H"], rnd.randint(1, 3), 11, 70)
            send(s, docs, rnd.randint(3, 10), 11, 60)
        for a in facs["A"]:
            send(a, docs, rnd.randint(3, 10), 11, 60)
            send(a, facs["H"], rnd.randint(1, 3), 11, 50)

    def write_flows(path, prior):
        with open(path, "w", encoding="ascii") as f:
            for a, b, n in pairs:
                if prior:
                    if rnd.random() < 0.12:
                        continue
                    n = int(n * rnd.uniform(0.45, 1.15))
                if n >= 11:
                    f.write(f"{a},{b},{n * 3},{n},{int(n * 0.1)}\n")

    cur = os.path.join(work_dir, "demo_flows_current.csv")
    prev = os.path.join(work_dir, "demo_flows_prior.csv")
    write_flows(cur, prior=False)
    write_flows(prev, prior=True)
    log(f"Demo providers: {len(providers):,}")
    return providers, {}, cur, prev, {"pac_year": args.year, "ratings": {}}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data", help="output directory (default: data)")
    ap.add_argument("--cache-dir", default="cache", help="download cache (default: cache)")
    ap.add_argument("--work-dir", default="work", help="temp working directory (default: work)")
    ap.add_argument("--year", type=int, default=2015, help="flows year to download / label (PSPP newest = 2015)")
    ap.add_argument("--window", type=int, default=30, choices=[30, 60, 90, 180], help="PSPP window in days (default 30)")
    ap.add_argument("--prior-year", type=int, default=None, help="also download this PSPP year for growth lists")
    ap.add_argument("--pspp-url", default=None, help="explicit URL of the PSPP zip (overrides auto-discovery)")
    ap.add_argument("--flows-file", default=None, help="local flows file (PSPP zip/csv, or CSV with source_npi,dest_npi,patients)")
    ap.add_argument("--prior-flows-file", default=None, help="local prior-year flows file")
    ap.add_argument("--flows-label", default=None, help="label shown on every page for the flows source")
    ap.add_argument("--nppes-zip", default=None, help="path to an already-downloaded NPPES dissemination zip")
    ap.add_argument("--states", default=None, help="comma-separated state codes to include (default all)")
    ap.add_argument("--min-patients", type=int, default=11, help="drop pairs below this many shared patients (default 11)")
    ap.add_argument("--dd-min", type=int, default=40, help="doctor->doctor pairs need this many patients to enter state flow tables")
    ap.add_argument("--growth-min", type=int, default=30, help="minimum current-year patients for growth analysis")
    ap.add_argument("--top", type=int, default=100, help="destinations/sources kept per provider page (default 100)")
    ap.add_argument("--top-lists", type=int, default=50, help="length of trending lists (default 50)")
    ap.add_argument("--flows-cap", type=int, default=150000, help="max rows per state flow table")
    ap.add_argument("--shards", type=int, default=1000, help="number of provider shard files (default 1000)")
    ap.add_argument("--no-app", dest="include_app", action="store_false", help="exclude NPs, PAs and podiatrists from doctors")
    ap.add_argument("--offline", action="store_true", help="never download; use cache only")
    ap.add_argument("--demo", action="store_true", help="build synthetic demo data (no downloads)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    t0 = time.time()
    states_filter = {s.strip().upper() for s in args.states.split(",")} if args.states else None
    os.makedirs(args.work_dir, exist_ok=True)
    out_dir = args.out
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    prev_pairs = None
    if args.demo:
        if args.shards == 1000:
            args.shards = 50
        args.flows_label = args.flows_label or f"Demo data (synthetic, modeled on CMS Physician Shared Patient Patterns {args.year})"
        providers, alias, flows_path, prior_path, extra = demo_build(args, args.work_dir)
        agg = process_flows(flows_path, providers, alias, args, args.work_dir)
        prev_pairs = prior_year_pairs(prior_path, alias, agg["facility_pairs"])
        args.prior_year = args.prior_year or args.year - 1
    else:
        dl = Downloader(args.cache_dir, offline=args.offline)
        cat = CmsCatalog(dl)
        flows_path = args.flows_file or fetch_pspp(dl, args.year, args.window, args.pspp_url)
        npis, _ = scan_npis(flows_path)
        providers, alias = load_facilities(cat, states_filter)
        tax = load_taxonomy(cat)
        load_doctors(dl, npis, providers, tax, states_filter, args.include_app, args.nppes_zip)
        extra = attach_volume_context(cat, dl, providers)
        agg = process_flows(flows_path, providers, alias, args, args.work_dir)
        if args.prior_year or args.prior_flows_file:
            prior_path = args.prior_flows_file or fetch_pspp(dl, args.prior_year, args.window, None)
            prev_pairs = prior_year_pairs(prior_path, alias, agg["facility_pairs"])

    write_provider_shards(providers, agg, args, out_dir)
    states = write_lists(providers, agg, args, out_dir)
    write_state_flows(providers, agg, args, out_dir)
    write_trending(providers, agg, prev_pairs, args, out_dir)
    meta = write_meta(providers, agg, states, args, out_dir, extra)

    size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(out_dir) for f in fs)
    log(f"Done in {time.time() - t0:,.0f}s. {len(providers):,} providers, {agg['n_kept']:,} flows, "
        f"{size / 1e6:,.1f} MB written to {out_dir}/")
    log(f"Flows label: {meta['flows_label']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
