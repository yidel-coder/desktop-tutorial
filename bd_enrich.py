#!/usr/bin/env python3
"""
bd_enrich.py - fill in email addresses for outreach targets with an email-finder service.

Web search finds websites, phone numbers and administrator names, but administrators' email addresses are
rarely published. This script takes jobs/contacts.csv rows that have a website domain (and ideally a contact
name) but no email, asks an email-finder API, and writes the result back with the source recorded.

Supported providers (set one key in the environment; the host must be allowed by your network policy):
    HUNTER_API_KEY   Hunter.io   https://api.hunter.io/v2/email-finder (name + domain) and /domain-search
    APOLLO_API_KEY   Apollo.io   https://api.apollo.io/api/v1/people/match (name + domain)

Usage
    python bd_enrich.py                      # enrich every row with a website and no email
    python bd_enrich.py --only "Green Hill"  # one employer
    python bd_enrich.py --dry-run            # show what would be looked up

Rows are only updated when the provider returns an address with a confidence score of at least --min-confidence
(default 70 for Hunter). Addresses are business addresses for the named role; nothing is guessed locally.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request

CONTACTS = "jobs/contacts.csv"
COLS = ["employer", "contact_name", "contact_title", "email", "phone", "website", "source", "status", "notes"]


def get_json(url: str, headers: dict | None = None, data: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json", "User-Agent": "hiring-radar-enrich/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def domain_of(website: str) -> str:
    w = (website or "").strip().lower()
    w = w.split("//")[-1].split("/")[0]
    return w[4:] if w.startswith("www.") else w


def hunter(row: dict, key: str, min_conf: int):
    dom = domain_of(row["website"])
    name = (row.get("contact_name") or "").strip()
    if name and " " in name:
        first, last = name.split(" ", 1)
        q = urllib.parse.urlencode({"domain": dom, "first_name": first, "last_name": last.split(",")[0].strip(), "api_key": key})
        d = get_json("https://api.hunter.io/v2/email-finder?" + q).get("data") or {}
        if d.get("email") and (d.get("score") or 0) >= min_conf:
            return d["email"], f"hunter.io email-finder (score {d.get('score')})"
    q = urllib.parse.urlencode({"domain": dom, "api_key": key, "limit": 10, "department": "executive,hr,management"})
    d = get_json("https://api.hunter.io/v2/domain-search?" + q).get("data") or {}
    for e in d.get("emails") or []:
        pos = (e.get("position") or "").lower()
        if any(k in pos for k in ("administrator", "executive director", "director of nursing", "human resources", "talent", "recruit")) and (e.get("confidence") or 0) >= min_conf:
            if not name:
                row["contact_name"] = f"{e.get('first_name', '')} {e.get('last_name', '')}".strip()
                row["contact_title"] = e.get("position") or row.get("contact_title", "")
            return e["value"], f"hunter.io domain-search (confidence {e.get('confidence')})"
    return None, None


def apollo(row: dict, key: str, min_conf: int):
    dom = domain_of(row["website"])
    name = (row.get("contact_name") or "").strip()
    if not name:
        return None, None
    first, last = (name.split(" ", 1) + [""])[:2]
    d = get_json("https://api.apollo.io/api/v1/people/match", headers={"X-Api-Key": key},
                 data={"first_name": first, "last_name": last.split(",")[0].strip(), "domain": dom, "reveal_personal_emails": False})
    p = d.get("person") or {}
    if p.get("email") and p.get("email_status") in ("verified", "likely to engage", None):
        return p["email"], f"apollo.io people/match ({p.get('email_status') or 'unverified'})"
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contacts", default=CONTACTS)
    ap.add_argument("--only", help="substring of an employer name")
    ap.add_argument("--min-confidence", type=int, default=70)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    hkey, akey = os.environ.get("HUNTER_API_KEY"), os.environ.get("APOLLO_API_KEY")
    if not (hkey or akey) and not args.dry_run:
        sys.exit("Set HUNTER_API_KEY or APOLLO_API_KEY (or use --dry-run).")
    with open(args.contacts, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    todo = [r for r in rows if r.get("website") and not r.get("email") and (not args.only or args.only.lower() in r["employer"].lower())]
    print(f"{len(todo)} row(s) to look up")
    found = 0
    for r in todo:
        print(f"  {r['employer']} ({domain_of(r['website'])}, {r.get('contact_name') or 'no name'})", end=": ")
        if args.dry_run:
            print("skip (dry run)"); continue
        try:
            email, src = (hunter(r, hkey, args.min_confidence) if hkey else (None, None))
            if not email and akey:
                email, src = apollo(r, akey, args.min_confidence)
        except Exception as e:  # noqa: BLE001
            print(f"error {e}"); continue
        if email:
            r["email"], r["status"] = email, "ready"
            r["source"] = (r.get("source") or "").rstrip("; ") + ("; " if r.get("source") else "") + src
            found += 1; print(email)
        else:
            print("nothing above the confidence floor")
    if not args.dry_run and found:
        with open(args.contacts, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in COLS})
        print(f"Updated {found} row(s) in {args.contacts}. Run python3 jobs_build.py to refresh the dashboard.")


if __name__ == "__main__":
    main()
