#!/usr/bin/env python3
"""
deploy_netlify.py - publish this folder (site + data/) to Netlify through the Netlify API.

No Netlify CLI or Node needed. Uses the "file digest" deploy method, so a re-deploy only
uploads files whose contents changed.

    export NETLIFY_AUTH_TOKEN=...          # personal access token from app.netlify.com/user/applications
    python deploy_netlify.py --site my-referral-directory          # creates the site if it does not exist
    python deploy_netlify.py --site my-referral-directory --dir .  # publish directory (default: .)

Published files: index.html, style.css, app.js, _headers, netlify.toml and everything under data/ and jobs/.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.netlify.com/api/v1"
INCLUDE_TOP = {"index.html", "style.css", "app.js", "_headers", "netlify.toml", "404.html", "robots.txt", "favicon.ico"}
INCLUDE_DIRS = {"data", "jobs"}


def token() -> str:
    t = os.environ.get("NETLIFY_AUTH_TOKEN") or os.environ.get("NETLIFY_TOKEN")
    if not t:
        sys.exit("Set NETLIFY_AUTH_TOKEN (Netlify > User settings > Applications > Personal access tokens).")
    return t


def api(method: str, path: str, body=None, raw: bytes | None = None, ctype: str = "application/json", retries: int = 5):
    url = path if path.startswith("http") else API + path
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    delay = 2
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token(), "Content-Type": ctype,
                                              "User-Agent": "referral-directory-deploy/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                txt = r.read()
                return json.loads(txt) if txt else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:300]
            if e.code in (401, 403):
                sys.exit(f"Netlify refused the token ({e.code}): {msg}")
            if e.code == 404:
                return None
            if attempt == retries or e.code < 500 and e.code != 429:
                raise RuntimeError(f"{method} {url} -> {e.code} {msg}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == retries:
                raise
        time.sleep(delay)
        delay = min(delay * 2, 30)


def collect(publish_dir: str) -> dict[str, str]:
    files = {}
    for name in sorted(os.listdir(publish_dir)):
        full = os.path.join(publish_dir, name)
        if os.path.isfile(full) and name in INCLUDE_TOP:
            files["/" + name] = full
        elif os.path.isdir(full) and name in INCLUDE_DIRS:
            for root, _, fs in os.walk(full):
                for f in fs:
                    p = os.path.join(root, f)
                    files["/" + os.path.relpath(p, publish_dir).replace(os.sep, "/")] = p
    return files


def sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="Netlify site name (subdomain) or site id")
    ap.add_argument("--dir", default=".", help="publish directory (default: current folder)")
    ap.add_argument("--workers", type=int, default=8, help="parallel uploads (default 8)")
    ap.add_argument("--title", default="Deploy from deploy_netlify.py")
    args = ap.parse_args()

    # 1. find or create the site
    site = api("GET", f"/sites/{args.site}") or api("GET", f"/sites/{args.site}.netlify.app")
    if not site:
        print(f"Creating site {args.site} ...")
        site = api("POST", "/sites", {"name": args.site})
    site_id, site_url = site["id"], site.get("ssl_url") or site.get("url")
    print(f"Site: {site.get('name')}  {site_url}")

    # 2. digest every file
    files = collect(args.dir)
    print(f"Hashing {len(files):,} files ...")
    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        digests = dict(zip(files.keys(), ex.map(sha1, files.values())))
    total_bytes = sum(os.path.getsize(p) for p in files.values())
    print(f"   {total_bytes / 1e6:,.1f} MB in total")

    # 3. create the deploy; Netlify answers with the digests it does not have yet
    deploy = api("POST", f"/sites/{site_id}/deploys", {"files": digests, "draft": False, "title": args.title})
    deploy_id = deploy["id"]
    required = set(deploy.get("required") or [])
    by_sha = {}
    for path, d in digests.items():
        by_sha.setdefault(d, path)
    todo = [by_sha[d] for d in required if d in by_sha]
    print(f"Deploy {deploy_id}: {len(todo):,} of {len(files):,} files need uploading")

    # 4. upload what is missing
    done = 0
    lock = __import__("threading").Lock()

    def upload(path):
        nonlocal done
        with open(files[path], "rb") as f:
            raw = f.read()
        api("PUT", f"/deploys/{deploy_id}/files{urllib.parse.quote(path)}", raw=raw, ctype="application/octet-stream")
        with lock:
            done += 1
            if done % 100 == 0 or done == len(todo):
                print(f"   uploaded {done:,}/{len(todo):,}")

    with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(upload, todo))

    # 5. wait until live
    for _ in range(120):
        d = api("GET", f"/deploys/{deploy_id}")
        state = d.get("state")
        if state == "ready":
            print(f"Live: {d.get('ssl_url') or site_url}")
            return 0
        if state == "error":
            sys.exit(f"Deploy failed: {d.get('error_message')}")
        time.sleep(5)
    print("Deploy is still processing; check the Netlify dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
