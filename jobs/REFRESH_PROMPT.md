# Weekly refresh prompt

Paste this as the prompt of a scheduled task (claude.ai → Code → Scheduled tasks / routines) with the **Indeed**
connector attached and the `yidel-coder/desktop-tutorial` repository selected. Suggested schedule: Mondays, early
morning, weekly. A task created without the Indeed connector cannot pull postings and will stop at step 3 by design.

---

You are refreshing the Hiring Demand Radar dashboard in the yidel-coder/desktop-tutorial repository (the /jobs app).
Read README.md section "Hiring Demand Radar" if you need context. Do exactly this, nothing more:

1. Pick the working branch. If jobs_build.py exists on origin/main, use main. Otherwise use
   claude/trusting-mendel-dxtoao. Check it out and pull the latest.

2. Run the standing query plan. Read jobs/queries.json. The plan is large (hundreds of searches), so split it into
   batches of about 20 and hand each batch to a parallel worker agent that has the Indeed connector; check that every
   batch finished before building. For every entry, call the Indeed connector's search_jobs tool
   with country_code "US", the given search, location and job_type (when present). Save each tool result verbatim
   (the markdown it returns) to jobs/in/<today as YYYY-MM-DD>/<slug>.md, where slug is a short lowercase filename like
   rn-nursing-home_new-york-ny.md, with header lines at the top exactly like the existing files under jobs/in/:
   "search: ...", "location: ...", optionally "job_type: ...", "pulled: <date>", "source: Indeed connector
   (search_jobs)". When a query returns no results, add a line "no-results | <search> | <location>" to
   jobs/in/<date>/_queries.log instead of a file. Do not invent, edit or trim postings.

3. Build. Run: python3 jobs_build.py. It must finish without error and print "Done." Check its coverage output; if
   more than a third of the planned queries could not be run (connector unavailable, errors), stop here, do not
   commit, and report which failed.

4. Commit and push. Stage only jobs/in/<date>/ and jobs/data/. Commit with the message
   "Weekly Indeed pull <date>: <N> live postings, <M> facility employers" (numbers from the build output) and push to
   the same branch you checked out. Do not open a pull request. Do not change code, jobs/queries.json,
   jobs/overrides.json or any other file.

5. Report in a few lines: postings seen, new since last pull, closed since last pull, and any employer that moved
   into or out of tier A or B (compare jobs/data/employers.json before and after the build).
