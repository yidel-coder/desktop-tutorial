# Hospital & Doctor Referral Directory

A free, static, national directory of **where hospitals and doctors send their patients**: nursing homes, home
health agencies, hospices, rehab hospitals and specialists, with patient counts, % share and rank. It also works in
reverse: for any nursing home, agency or hospice, see which hospitals and doctors send it patients.

Built the same way as the King Solomon nursing-home owners directory: `index.html` + `style.css` + `app.js`, hash
routes (`#/hospitals`, `#/p/1234567890`, ...), and a Python build script that downloads free public government data,
cleans it and writes compressed JSON per state into `/data`. No server, no database, no login.

```
index.html   style.css   app.js        the site (vanilla JS, no dependencies)
build.py                               downloads + joins public data, writes /data
data/                                  output of build.py (a demo build is committed)
netlify.toml  _headers  deploy_netlify.py  .github/workflows/pages.yml   deployment
```

## Pages

| Route | What it shows |
|---|---|
| `#/` | One search box for any hospital, doctor or facility by name, city, ZIP or NPI |
| `#/hospitals`, `#/hospitals/NY` | Hospitals by state (acute, rehab, LTCH), sortable, with CMS rating and patients sent/received |
| `#/doctors`, `#/doctors/NJ` | Doctors by state and specialty |
| `#/facilities`, `#/facilities/FL?type=S` | Nursing homes, home health agencies and hospices by state |
| `#/p/{npi}` | Provider page: "Where patients go" and "Where patients come from", with counts, share, rank, bar chart, type breakdown, type filter and CSV export |
| `#/flows` | Every source → destination pair, filterable by state, source type, destination type, minimum patients, name |
| `#/trending` | National top lists: biggest referrers, biggest receivers, biggest relationships, fastest growing, new relationships |
| `#/about` | Sources, dates, coverage and limitations |

The data year and window are labelled on every page (`Data year 2015 · 30-day window`).

## Data model

`build.py` produces two logical tables, so the referral source can be swapped without touching the site:

```
providers(npi, ccn, name, type, address, city, state, zip, specialty)
flows(source_npi, dest_npi, year, patients, share)
```

`type` is one letter: `H` hospital, `R` rehab hospital, `L` long-term care hospital, `S` nursing home (SNF),
`A` home health agency, `C` hospice, `D` doctor/clinician.

Files written to `data/` (all `.json.gz` files are gzip; `app.js` decompresses them in the browser):

| File | Contents |
|---|---|
| `meta.json` | year, window, labels, counts, state list, column names |
| `providers/{shard}.json.gz` | profile + top-N outgoing and incoming flows for every NPI with `npi % shards == shard` |
| `facilities/{ST}.json.gz` | hospitals, SNFs, HHAs, hospices in a state (rating, Medicare volume, patients sent/received) |
| `doctors/{ST}.json.gz` | doctors in a state (specialty, city, patients sent/received) |
| `flows/{ST}.json.gz` | all source → destination pairs whose source is in the state |
| `search/facilities.json.gz` | national facility search index |
| `trending.json` | national top lists |

## Data sources (all free and public)

1. **Provider names and IDs**
   - CMS Provider Enrollment files on data.cms.gov: *Hospital Enrollments*, *Skilled Nursing Facility Enrollments*,
     *Home Health Agency Enrollments*, *Hospice Enrollments*, plus the matching *Additional NPIs* files (secondary NPIs
     are folded into the facility's main record). Resolved by title through `https://data.cms.gov/data.json`, with
     dataset UUID fallbacks.
   - NPPES NPI Registry monthly dissemination file (`https://download.cms.gov/nppes/NPI_Files.html`) for doctors and
     their taxonomy/specialty. Only clinicians who appear in the pair data are kept.
2. **Referral / patient-sharing pairs**: CMS *Physician Shared Patient Patterns* (NBER mirror,
   `https://data.nber.org/physician-shared-patient-patterns/{year}/`). Newest public year is **2015**; the
   30-day window is used by default. A pair is counted when provider B's claim follows provider A's within the
   window for the same Medicare beneficiary; pairs under 11 beneficiaries are suppressed by CMS.
3. **Volume context**: CMS *Medicare Post-Acute Care and Hospice - by Provider and Service* (distinct patients,
   payments, stays per SNF/HHA/hospice) and Care Compare star ratings (hospital `xubh-q36u`, nursing home
   `4pq5-n9py`, home health `6jpm-sxkc`, hospice `252m-zfp9`).

### Replacing the pair data with a licensed feed

Any newer claims feed (Trella Health, Definitive Healthcare, CareSet, a CMS VRDC extract) can replace source 2
without changing the site. Export it as a CSV with a header row containing `source_npi, dest_npi, patients` and run:

```bash
python build.py --flows-file trella_2025.csv --year 2025 --flows-label "Trella Health, CY2025 Medicare FFS" \
                --prior-flows-file trella_2024.csv --prior-year 2024
```

PSPP-layout files (no header: `npi1,npi2,pair_count,bene_count,same_day`) are also accepted by `--flows-file`.

## Run it

Requirements: Python 3.9+ (standard library only). For a full national build: ~25 GB free disk, a few hours,
~6 GB RAM.

```bash
# 1. Preview the site immediately with synthetic demo data (no downloads, 2 seconds)
python build.py --demo
python -m http.server 8000
# open http://localhost:8000

# 2. Full national build from real public data
python build.py                       # 2015 PSPP, 30-day window, all states
python build.py --prior-year 2014     # also compute "fastest growing" and "new relationships"

# 3. Smaller / faster builds
python build.py --states NY,NJ,CT     # only providers located in these states
python build.py --window 90           # 90-day window instead of 30
python build.py --min-patients 20 --top 50 --shards 500   # smaller output
```

Useful flags (`python build.py -h` lists them all):

| Flag | Default | Meaning |
|---|---|---|
| `--year` / `--window` | 2015 / 30 | PSPP year and day window to download and label |
| `--prior-year` | none | second PSPP year for growth lists |
| `--pspp-url URL` | auto | explicit PSPP zip URL if NBER renames files |
| `--flows-file`, `--prior-flows-file` | none | local pair files instead of downloading |
| `--nppes-zip PATH` | auto | reuse an NPPES zip you already downloaded |
| `--states` | all | comma-separated state codes |
| `--min-patients` | 11 | drop pairs below this |
| `--dd-min` | 40 | doctor→doctor pairs need this many patients to enter the Flows tables |
| `--top` | 100 | relationships kept per provider page per direction |
| `--shards` | 1000 | number of provider shard files |
| `--no-app` | off | exclude nurse practitioners, PAs and podiatrists |
| `--offline` | off | use only files already in `cache/` |

What the build does, step by step:

1. Downloads the PSPP zip (cached in `cache/`) and scans it once to collect every NPI that appears.
2. Downloads the four enrollment files and Additional-NPI files, builds the facility table (type from CCN range and
   hospital sub-group flags), merges secondary NPIs.
3. Downloads the NPPES zip (~1 GB) and streams the 9 GB CSV inside it, keeping individual clinicians that appear in the
   pair data, with specialty from the primary taxonomy code.
4. Joins Post-Acute Care utilization and Care Compare ratings on CCN.
5. Second pass over the PSPP file: keeps pairs where both NPIs are known providers, totals patients sent/received per
   provider, writes shard and state temp files to `work/`.
6. Writes `data/`: provider shards (top-N each way, share = pair / provider total), state lists, state flow tables,
   search index, trending lists, `meta.json`.

Expected size for a full national 2015 30-day build with defaults: roughly 1–3 GB in `data/` (about 1,000 provider
shard files of 1–3 MB each; state files 0.1–10 MB). Browsing a page loads one shard or one state file.

## Deploy as a static site

The whole folder is static. Any host works; three options:

**Netlify (recommended for a full build).** `netlify.toml` is included (publish directory `.`, no build command,
correct headers for `.gz`).

```bash
npm i -g netlify-cli
netlify login
netlify deploy --prod --dir .      # uploads index.html, style.css, app.js and data/
```

Or connect the GitHub repo in the Netlify UI with publish directory `.` and an empty build command. Multi-GB deploys
work but are slow the first time; later deploys only upload changed files.

Without Node or the CLI, `deploy_netlify.py` does the same through the Netlify API (it creates the site if needed and
only uploads files whose contents changed):

```bash
export NETLIFY_AUTH_TOKEN=...          # app.netlify.com > User settings > Applications > Personal access tokens
python deploy_netlify.py --site my-referral-directory
```

**GitHub Pages (what this repo is set up for).** `.github/workflows/pages.yml` deploys the repo root on every push
to `main`. `main` carries only the small demo `data/`; the real national dataset (about 810 MB) lives on the orphan
`data` branch, and the workflow swaps it in at deploy time, so the repository history never grows with rebuilds.
In the repo settings choose *Pages → Source: GitHub Actions* once. To publish a new build:

```bash
python build.py --prior-year 2014                       # writes data/
git worktree add /tmp/dataw --detach && cd /tmp/dataw
git checkout --orphan data && git rm -rfq . && cp -r ../desktop-tutorial/data/. . && git add -A
git commit -m "National referral data, built $(date +%F)" && git push --force -u origin data
```

Then re-run the Pages workflow (push to `main` or use *Run workflow*). GitHub Pages sites are limited to 1 GB.

**Site on Pages/Netlify, data on object storage (best for a full national build).** Upload `data/` to Cloudflare R2,
Backblaze B2 or S3 behind a CDN, allow CORS `GET` from your site's origin, serve `.gz` files as
`application/gzip` (no `Content-Encoding` header), and point the site at it in `index.html`:

```html
<script>window.DIRECTORY_CONFIG = { dataBase: 'https://cdn.example.com/referral-data' };</script>
```

Cloudflare Pages also works for the site itself (20,000-file / 25 MB-per-file limits apply if `data/` is included,
so use `--shards 500` or external storage).

## Notes and limitations

- Patient counts are Medicare fee-for-service beneficiaries only (no Medicare Advantage, Medicaid or commercial).
- The newest free pair data is 2015 (January to about September). Names and addresses come from current files, so a
  facility that opened later shows no relationships. A licensed feed fixes this (see above).
- A shared patient is a proxy for a referral or discharge, not proof of one.
- Pairs under 11 beneficiaries are suppressed by CMS, so shares are over visible pairs.
- The committed `data/` folder is a **demo build**: every name and number is synthetic, and the site shows a banner.
