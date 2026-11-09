/* Hiring Demand Radar - static front end
 * Routes: #/  #/employers  #/e/{key}  #/jobs  #/markets[/ST]  #/pay  #/about  #/search?q=
 * Data: JSON written by ../jobs_build.py into ./data (see ../README.md and #/about).
 */
(function () {
  'use strict';

  const CFG = Object.assign({ dataBase: 'data' }, window.RADAR_CONFIG || {});
  const D = {}; // meta, jobs, employers, markets, benchmarks, trends
  const app = document.getElementById('app');

  // ------------------------------------------------------------------ data
  async function loadAll() {
    const names = ['meta', 'jobs', 'employers', 'markets', 'benchmarks', 'trends', 'outreach'];
    const res = await Promise.all(names.map((n) => fetch(`${CFG.dataBase}/${n}.json`, { cache: 'no-cache' }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status} loading ${n}.json`); return r.json(); })));
    names.forEach((n, i) => { D[n] = res[i]; });
    D.jobs = D.jobs.rows; D.employers = D.employers.rows; D.trends = D.trends.rows; D.bench = D.benchmarks.rows; D.outreach = (D.outreach || { rows: [] }).rows;
    D.empByKey = new Map(D.employers.map((e) => [e.key, e]));
    D.jobById = new Map(D.jobs.map((j) => [j.id, j]));
    D.live = D.jobs.filter((j) => j.status !== 'closed');
  }

  // --------------------------------------------------------------- helpers
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n) => (n == null || isNaN(n) ? '—' : Number(n).toLocaleString('en-US'));
  const hr = (n) => (n == null ? '—' : '$' + (Math.round(n * 100) / 100).toLocaleString('en-US', { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 }) + '/hr');
  const pctf = (x) => (x == null ? '—' : Math.round(x * 100) + '%');
  const days = (d) => (d == null ? '—' : d + 'd');
  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const tokens = (q) => norm(q).split(/[\s,]+/).filter(Boolean);
  const matches = (hay, toks) => { const h = norm(hay); return toks.every((t) => h.includes(t)); };
  const setTitle = (t) => { document.title = (t ? t + ' · ' : '') + 'Hiring Demand Radar'; };
  const qs = (obj) => { const p = new URLSearchParams(); Object.entries(obj).forEach(([k, v]) => { if (v !== '' && v != null) p.set(k, v); }); const s = p.toString(); return s ? '?' + s : ''; };
  const roleLabel = (r) => (D.meta.roles[r] || r);
  const settingLabel = (s) => (D.meta.settings[s] || s);
  const stateName = (st) => (D.meta.states[st] || st);
  const asofTag = () => `<span class="asof">Postings as of ${esc(D.meta.asof)} · ${D.meta.snapshots.length} pull${D.meta.snapshots.length === 1 ? '' : 's'}</span>`;
  const tier = (e) => (e.is_agency ? '<span class="tier AG" title="Staffing agency (competitor)">AGY</span>' : `<span class="tier ${esc(e.tier)}" title="Lead tier ${esc(e.tier)}">${esc(e.tier)}</span>`);
  const sbadge = (s) => `<span class="badge s-${esc(s)}">${esc(settingLabel(s))}</span>`;
  const rbadge = (r) => `<span class="badge" style="background:var(--c-${esc(r.toLowerCase())})">${esc(roleLabel(r))}</span>`;
  const flagChip = (f) => `<span class="flag ${esc(f)}">${esc(D.meta.flags[f] || f)}</span>`;
  const elink = (e, text) => `<a href="#/e/${encodeURIComponent(e.key)}">${esc(text || e.name)}</a>`;
  const indeedCompany = (name) => `https://www.indeed.com/jobs?q=${encodeURIComponent('company:"' + name + '"')}`;
  const stat = (v, l, href, d) => `<${href ? `a href="${href}" class="stat link"` : 'div class="stat"'}><div class="v">${v}</div><div class="l">${l}</div>${d ? `<div class="d">${d}</div>` : ''}</${href ? 'a' : 'div'}>`;
  const meter = (score) => `<span class="meter" title="Demand score ${score} of 100"><span class="track"><span style="width:${Math.max(2, Math.min(100, score))}%"></span></span><b>${score}</b></span>`;
  const where = (e) => (e.cities.length ? e.cities.slice(0, 2).join(', ') + (e.cities.length > 2 ? ` +${e.cities.length - 2}` : '') + ' · ' : '') + e.states.join(', ');
  const STATUS_LABEL = { new: 'Needs contact', ready: 'Ready to send', sent: 'Sent', replied: 'Replied', meeting: 'Meeting booked', not_interested: 'Not interested', bounced: 'Bounced', do_not_contact: 'Do not contact' };
  const statusChip = (st) => `<span class="status st-${esc(st)}">${esc(STATUS_LABEL[st] || st)}</span>`;
  const mailto = (r) => `mailto:${encodeURIComponent((r.contact || {}).email || '')}?subject=${encodeURIComponent(r.subject)}&body=${encodeURIComponent(r.body)}`;
  const copyBtn = (text, label) => `<button class="btn ghost" data-copy="${esc(text)}">${esc(label || 'Copy')}</button>`;
  function wireCopy(root) { root.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => { try { await navigator.clipboard.writeText(b.dataset.copy); const t = b.textContent; b.textContent = 'Copied'; setTimeout(() => { b.textContent = t; }, 1200); } catch (e) { window.prompt('Copy:', b.dataset.copy); } })); }
  const median = (a) => { if (!a.length) return null; const s = a.slice().sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

  function sortRows(rows, key, dir, numeric, get) {
    const m = dir === 'asc' ? 1 : -1;
    const g = get || ((r) => r[key]);
    return rows.slice().sort((a, b) => {
      const x = g(a), y = g(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (numeric) return (Number(x) - Number(y)) * m;
      return String(x).localeCompare(String(y)) * m;
    });
  }

  /** Sortable, paginated table. cols: [{key,label,num,render(row),sortable,get(row),cls}] */
  function renderTable(container, opts) {
    const state = { sortKey: opts.sort || null, dir: opts.dir || 'desc', page: 1 };
    const pageSize = opts.pageSize || 50;
    function draw() {
      let rows = opts.rows;
      const col = opts.cols.find((c) => c.key === state.sortKey);
      if (col) rows = sortRows(rows, col.key, state.dir, col.num, col.get);
      const shown = rows.slice(0, state.page * pageSize);
      const head = opts.cols.map((c) => `<th class="${c.num ? 'num ' : ''}${c.sortable === false ? '' : 'sortable'}" data-key="${esc(c.key)}">${esc(c.label)}${state.sortKey === c.key ? `<span class="arrow">${state.dir === 'asc' ? '▲' : '▼'}</span>` : ''}</th>`).join('');
      const body = shown.map((r, i) => `<tr>${opts.cols.map((c) => `<td class="${c.num ? 'num ' : ''}${c.cls || ''}">${c.render ? c.render(r, i) : esc(r[c.key])}</td>`).join('')}</tr>`).join('');
      container.innerHTML = rows.length
        ? `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
           <div class="table-foot"><span>Showing ${fmt(shown.length)} of ${fmt(rows.length)}</span>
           <span>${shown.length < rows.length ? '<button class="btn ghost" data-more>Show more</button> <button class="btn ghost" data-all>Show all</button> ' : ''}${opts.csv ? '<button class="btn ghost" data-csv>Download CSV</button>' : ''}</span></div>`
        : `<div class="empty">${esc(opts.empty || 'Nothing matches these filters.')}</div>`;
      container.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', () => {
        const k = th.dataset.key;
        if (state.sortKey === k) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        else { state.sortKey = k; state.dir = opts.cols.find((c) => c.key === k).num ? 'desc' : 'asc'; }
        state.page = 1; draw();
      }));
      const more = container.querySelector('[data-more]');
      if (more) more.addEventListener('click', () => { state.page++; draw(); });
      const all = container.querySelector('[data-all]');
      if (all) all.addEventListener('click', () => { state.page = Math.ceil(rows.length / pageSize); draw(); });
      const csvBtn = container.querySelector('[data-csv]');
      if (csvBtn) csvBtn.addEventListener('click', () => downloadCsv(opts.csv.name, opts.csv.header, rows.map(opts.csv.row)));
    }
    draw();
    return { redraw: (rows) => { opts.rows = rows; state.page = 1; draw(); } };
  }

  function downloadCsv(name, header, rows) {
    const cell = (v) => { const s = String(v == null ? '' : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
    const text = [header, ...rows].map((r) => r.map(cell).join(',')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
    a.download = name; a.click(); URL.revokeObjectURL(a.href);
  }

  function filtersBar(defs) {
    return `<div class="filters">${defs.map((d) => `<label>${esc(d.label)}${d.type === 'select'
      ? `<select data-f="${d.id}">${d.options.map((o) => `<option value="${esc(o[0])}" ${String(o[0]) === String(d.value || '') ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select>`
      : `<input type="${d.type || 'search'}" data-f="${d.id}" value="${esc(d.value || '')}" placeholder="${esc(d.placeholder || '')}" ${d.min != null ? `min="${d.min}"` : ''}>`}</label>`).join('')}</div>`;
  }
  const readFilters = (root) => { const o = {}; root.querySelectorAll('[data-f]').forEach((el) => { o[el.dataset.f] = el.value; }); return o; };
  const statesPresent = () => Object.keys(D.markets.states).sort((a, b) => (D.markets.states[b].postings - D.markets.states[a].postings));
  const stateOptions = (all) => [['', all || 'All states']].concat(statesPresent().map((s) => [s, `${stateName(s)} (${D.markets.states[s].postings})`]));
  const roleOptions = () => [['', 'All roles']].concat(D.meta.role_order.map((r) => [r, roleLabel(r)]));
  const settingOptions = () => [['', 'All settings']].concat(Object.keys(D.meta.settings).map((s) => [s, settingLabel(s)]));

  // ---------------------------------------------------------------- charts
  /** Ranked horizontal bars, one hue. items: [{label, value, href, sub, emph, title}] */
  function hbars(items, opts = {}) {
    const max = opts.max || Math.max(1, ...items.map((i) => i.value));
    const f = opts.fmt || fmt;
    const rows = items.map((i) => `<div class="hbar ${i.emph ? 'emph' : ''}" title="${esc(i.title || (i.label + ': ' + f(i.value)))}">
        <div class="lbl">${i.href ? `<a href="${i.href}">${esc(i.label)}</a>` : esc(i.label)}${i.sub ? `<small>${esc(i.sub)}</small>` : ''}</div>
        <div class="track"><div class="fill ${i.ghost ? 'ghost' : ''}" style="width:${Math.max(0.5, (i.value / max) * 100).toFixed(1)}%"></div></div>
        <div class="val">${f(i.value)}${i.of ? `<small> / ${f(i.of)}</small>` : ''}</div></div>`).join('');
    const table = `<table class="sr-only"><caption>${esc(opts.caption || 'Values')}</caption><tbody>${items.map((i) => `<tr><th scope="row">${esc(i.label)}</th><td>${f(i.value)}</td></tr>`).join('')}</tbody></table>`;
    return `<div class="hbars" role="img" aria-label="${esc(opts.caption || 'Bar chart')}">${rows}</div>${table}`;
  }
  /** Thin segmented bar of a role mix, fixed order and colors. counts: {ROLE: n} */
  function segbar(counts, total) {
    const t = total || Object.values(counts).reduce((a, b) => a + b, 0) || 1;
    const parts = D.meta.role_order.filter((r) => counts[r]);
    const title = parts.map((r) => `${roleLabel(r)}: ${counts[r]}`).join(' · ');
    return `<div class="seg" role="img" aria-label="${esc(title)}" title="${esc(title)}">${parts.map((r) => `<span class="r-${r}" style="flex:${counts[r]} 1 0"></span>`).join('')}</div>`;
  }
  const roleLegend = () => `<div class="legend">${D.meta.role_order.map((r) => `<span><i class="r-${r}"></i>${esc(roleLabel(r))}</span>`).join('')}</div>`;
  /** p25-p75 band with a median tick on a shared hourly scale; optional reference tick (e.g. national median). */
  function rangebar(b, max, ref) {
    const x = (v) => Math.max(0, Math.min(100, (v / max) * 100)).toFixed(1) + '%';
    const t = `p25 ${hr(b.p25)} · median ${hr(b.median)} · p75 ${hr(b.p75)}${ref ? ` · national ${hr(ref)}` : ''}`;
    return `<div class="range" title="${esc(t)}" role="img" aria-label="${esc(t)}"><div class="band" style="left:${x(b.p25)};width:${(Math.max(0, b.p75 - b.p25) / max * 100).toFixed(1)}%"></div>${ref ? `<div class="ref" style="left:${x(ref)}"></div>` : ''}<div class="med" style="left:${x(b.median)}"></div></div>`;
  }
  const benchFor = (role, st) => D.bench.find((b) => b.role === role && b.state === st);

  // ------------------------------------------------------------------ views
  function viewHome() {
    setTitle('');
    const c = D.meta.counts;
    const live = D.live;
    const facilityEmps = D.employers.filter((e) => !e.is_agency);
    const ages = live.map((j) => j.age_days).filter((a) => a != null);
    const byRole = {}, bySetting = {}, byState = {}, byFlag = {};
    live.forEach((j) => { byRole[j.role] = (byRole[j.role] || 0) + 1; bySetting[j.setting] = (bySetting[j.setting] || 0) + 1; byState[j.state || 'US'] = (byState[j.state || 'US'] || 0) + 1; j.flags.forEach((f) => { byFlag[f] = (byFlag[f] || 0) + 1; }); });
    const top = facilityEmps.slice(0, 8);
    const rank = (o, label, href) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: label(k), value: v, href: href && href(k) }));
    const payRows = D.meta.role_order.map((r) => benchFor(r, 'ALL')).filter((b) => b && b.n >= 3);
    const payMax = Math.max(...payRows.map((b) => b.p75)) * 1.05;

    app.innerHTML = `
      <div class="page-head"><h1>Who is hiring, how urgently, and what they pay</h1>
        <p>Every job posting is a demand signal from a facility. This board groups ${fmt(c.postings)} live postings by employer and market, scores each employer as a staffing lead, and benchmarks advertised pay. ${asofTag()}</p></div>
      <div class="coverage"><b>Read this as a sample, not a census.</b> ${fmt(D.meta.coverage.queries_run)} Indeed searches were run across ${fmt(c.states)} states; each returns at most 10 postings. Employers with several postings in the sample are hiring a lot more than that. Re-running the same <a href="#/about">query plan</a> on a schedule turns this into a trend line.</div>
      <div class="kpis">
        ${stat(fmt(c.postings), 'Live postings', '#/jobs')}
        ${stat(fmt(c.employers), 'Facility employers hiring', '#/employers', `${fmt(c.agencies)} competitor agencies also posting`)}
        ${stat(fmt(c.tier_a + c.tier_b), 'Priority leads (tier A + B)', '#/employers?tier=AB', `${fmt(c.tier_a)} tier A · ${fmt(c.tier_b)} tier B`)}
        ${stat(pctf(c.urgent / c.postings), 'Postings with urgency signals', '#/jobs?flag=any', 'bonus, nights, weekends, per diem')}
        ${stat(days(median(ages)), 'Median days open', '#/jobs?sort=age', `oldest ${days(Math.max(...ages))}`)}
        ${stat(pctf(c.with_pay / c.postings), 'Postings listing pay', '#/pay', 'used for hourly benchmarks')}
      </div>
      <div class="grid cols-3-2">
        <div class="card"><div class="row between"><div><h2>Call first</h2><p class="sub">Facility employers ranked by demand score: volume, role breadth, urgency, posting age and pay pressure.</p></div><a class="btn" href="#/employers">All employers</a> <a class="btn gold" href="#/outreach">Outreach list</a></div>
          ${top.map((e) => `<div class="lead">${tier(e)}<div class="who">${elink(e)} ${sbadge(e.setting)}<small>${esc(where(e))} · ${esc(e.signals.slice(0, 2).join(' · ') || 'single posting')}</small></div><div class="num"><div class="n">${fmt(e.postings)} <small class="muted">open</small></div>${meter(e.score)}</div></div>`).join('')}
        </div>
        <div>
          <div class="card"><h2>Demand by role</h2><p class="sub">Live postings per role family.</p>${hbars(rank(byRole, roleLabel, (k) => '#/jobs' + qs({ role: k })), { caption: 'Postings by role' })}</div>
          <div class="card"><h2>Demand by care setting</h2><p class="sub">Inferred from the employer name and title.</p>${hbars(rank(bySetting, settingLabel, (k) => '#/jobs' + qs({ setting: k })), { caption: 'Postings by setting' })}</div>
        </div>
      </div>
      <div class="grid cols-3">
        <div class="card"><h2>Demand by state</h2><p class="sub">Click a state for its market page.</p>${hbars(rank(byState, stateName, (k) => '#/markets/' + k), { caption: 'Postings by state' })}</div>
        <div class="card"><h2>Urgency signals</h2><p class="sub">Postings whose title or type carries each signal.</p>${hbars(rank(byFlag, (k) => D.meta.flags[k] || k, (k) => '#/jobs' + qs({ flag: k })), { caption: 'Urgency signals' })}</div>
        <div class="card"><h2>Advertised pay, national</h2><p class="sub">Hourly midpoint of posted ranges: p25 to p75 band, median tick.</p>
          <div class="table-wrap"><table class="data"><thead><tr><th>Role</th><th class="num">n</th><th class="num">Median</th><th>Range</th></tr></thead><tbody>
          ${payRows.map((b) => `<tr><td>${esc(roleLabel(b.role))}</td><td class="num">${b.n}</td><td class="num">${hr(b.median)}</td><td>${rangebar(b, payMax)}</td></tr>`).join('')}</tbody></table></div>
          <a class="btn ghost" style="margin-top:10px" href="#/pay">Pay by state</a></div>
      </div>
      <div class="card"><div class="row between"><div><h2>Trend</h2><p class="sub">Postings seen per pull. Postings that disappear between pulls of the same query are counted as closed.</p></div></div>
        ${D.trends.length > 1 ? trendChart() : `<div class="empty">One pull so far (${esc(D.meta.asof)}). Run the query plan again next week and this card shows new, continuing and closed postings per employer.</div>`}</div>`;
  }

  function trendChart() {
    const max = Math.max(...D.trends.map((t) => t.postings));
    return `<div class="trend" role="img" aria-label="Postings per pull">${D.trends.map((t) => `<div class="col" title="${esc(t.snapshot)}: ${t.postings} postings, ${t.new} new, ${t.closed} closed"><span style="height:${(t.postings / max * 100).toFixed(0)}%"></span><small>${esc(t.snapshot.slice(5))}</small></div>`).join('')}</div>
      <table class="sr-only"><tbody>${D.trends.map((t) => `<tr><th scope="row">${esc(t.snapshot)}</th><td>${t.postings} postings</td><td>${t.new} new</td><td>${t.closed} closed</td></tr>`).join('')}</tbody></table>`;
  }

  // ---- Employers -------------------------------------------------------
  function viewEmployers(q) {
    setTitle('Employers');
    const f = { q: q.q || '', st: q.st || '', setting: q.setting || '', role: q.role || '', tier: q.tier || '', kind: q.kind || 'fac', min: q.min || '' };
    app.innerHTML = `<div class="page-head"><h1>Employers as leads</h1><p>One row per employer, scored 0 to 100 as a staffing prospect. Agencies are competitors and are listed separately. ${asofTag()}</p></div>
      <div class="card tight" id="fbar">${filtersBar([
        { id: 'q', label: 'Search', value: f.q, placeholder: 'Employer, chain or city' },
        { id: 'st', label: 'State', type: 'select', value: f.st, options: stateOptions() },
        { id: 'setting', label: 'Care setting', type: 'select', value: f.setting, options: settingOptions().filter((o) => o[0] !== 'AGENCY') },
        { id: 'role', label: 'Hiring for', type: 'select', value: f.role, options: roleOptions() },
        { id: 'tier', label: 'Lead tier', type: 'select', value: f.tier, options: [['', 'All tiers'], ['AB', 'A and B (priority)'], ['A', 'A only'], ['B', 'B only'], ['C', 'C only']] },
        { id: 'kind', label: 'Show', type: 'select', value: f.kind, options: [['fac', 'Facility employers'], ['agy', 'Staffing agencies (competitors)'], ['all', 'Everyone']] },
        { id: 'min', label: 'Min. postings', type: 'number', value: f.min, min: 1, placeholder: '1' },
      ])}${roleLegend()}</div>
      <div class="card" id="tbl"></div>
      <p class="note">Score = volume (40) + role breadth (15) + urgency (20) + posting age and reposts (15) + pay pressure vs market (10). Tier A ≥ 60, B ≥ 40. Single-posting employers are discounted. Full method on the <a href="#/about">Method</a> page.</p>`;
    const cols = [
      { key: 'tier', label: 'Tier', get: (e) => (e.is_agency ? 'Z' : e.tier), render: (e) => tier(e) },
      { key: 'score', label: 'Score', num: true, render: (e) => meter(e.score) },
      { key: 'name', label: 'Employer', cls: 'wrap', render: (e) => `${elink(e)}${e.chain && e.chain !== e.name ? `<span class="sub">${esc(e.chain)}</span>` : ''}` },
      { key: 'setting', label: 'Setting', render: (e) => sbadge(e.setting) },
      { key: 'where', label: 'Where', cls: 'wrap', get: (e) => e.states.join(','), render: (e) => esc(where(e)) },
      { key: 'postings', label: 'Open', num: true },
      { key: 'roles', label: 'Role mix', sortable: false, render: (e) => segbar(e.roles, e.postings) },
      { key: 'urgent_share', label: 'Urgent', num: true, render: (e) => pctf(e.urgent_share) },
      { key: 'oldest_age', label: 'Oldest', num: true, render: (e) => days(e.oldest_age) },
      { key: 'signals', label: 'Signals', cls: 'wrap sigs', sortable: false, render: (e) => `<ul class="plain sig">${e.signals.slice(0, 3).map((s) => `<li>${esc(s)}</li>`).join('') || '<li class="muted">—</li>'}</ul>` },
    ];
    const apply = () => {
      const v = readFilters(document.getElementById('fbar'));
      const toks = tokens(v.q);
      let rows = D.employers.filter((e) => (v.kind === 'all' ? true : v.kind === 'agy' ? e.is_agency : !e.is_agency));
      if (v.st) rows = rows.filter((e) => e.states.includes(v.st));
      if (v.setting) rows = rows.filter((e) => e.setting === v.setting);
      if (v.role) rows = rows.filter((e) => e.roles[v.role]);
      if (v.tier) rows = rows.filter((e) => v.tier.includes(e.tier));
      if (v.min) rows = rows.filter((e) => e.postings >= Number(v.min));
      if (toks.length) rows = rows.filter((e) => matches(e.name + ' ' + e.chain + ' ' + e.cities.join(' ') + ' ' + e.states.join(' '), toks));
      history.replaceState(null, '', '#/employers' + qs(v));
      return rows;
    };
    const t = renderTable(document.getElementById('tbl'), { rows: apply(), cols, sort: 'score', dir: 'desc', pageSize: 50, empty: 'No employers match these filters.',
      csv: { name: `leads-${D.meta.asof}.csv`, header: ['Tier', 'Score', 'Employer', 'Chain', 'Setting', 'States', 'Cities', 'Open postings', 'Roles', 'Urgent share', 'Median days open', 'Oldest days open', 'Signals', 'Talking points', 'Indeed search'],
        row: (e) => [e.is_agency ? 'Agency' : e.tier, e.score, e.name, e.chain, settingLabel(e.setting), e.states.join('; '), e.cities.join('; '), e.postings, Object.entries(e.roles).map(([r, n]) => `${roleLabel(r)}: ${n}`).join('; '), e.urgent_share, e.median_age, e.oldest_age, e.signals.join(' | '), e.talking_points.join(' | '), indeedCompany(e.name)] } });
    document.getElementById('fbar').addEventListener('input', () => t.redraw(apply()));
    document.getElementById('fbar').addEventListener('change', () => t.redraw(apply()));
  }

  function viewEmployer(key) {
    const e = D.empByKey.get(key);
    if (!e) { app.innerHTML = `<div class="error">No employer with key “${esc(key)}”.</div>`; return; }
    setTitle(e.name);
    const js = e.job_ids.map((id) => D.jobById.get(id)).filter(Boolean);
    const partsMax = { volume: 40, breadth: 15, urgency: 20, aging: 15, pay: 10 };
    const partsLabel = { volume: 'Volume of postings', breadth: 'Role breadth', urgency: 'Urgency signals', aging: 'Posting age & reposts', pay: 'Pay pressure vs market' };
    const st = e.states[0];
    const mk = D.markets.states[st];
    app.innerHTML = `
      <div class="breadcrumb"><a href="#/employers">Employers</a> › ${esc(e.name)}</div>
      <div class="prov-head"><div><h1>${esc(e.name)}</h1><div class="prov-meta"><span>${tier(e)} ${e.is_agency ? 'Staffing agency' : 'Lead tier ' + esc(e.tier)}</span><span>${sbadge(e.setting)}</span>${e.chain && e.chain !== e.name ? `<span>Part of ${esc(e.chain)}</span>` : ''}<span>${esc(where(e))}</span></div></div>
        <div class="row"><a class="btn gold" href="${indeedCompany(e.name)}" target="_blank" rel="noopener">All postings on Indeed ↗</a>
          ${e.cms ? `<a class="btn" href="../#/p/${esc(e.cms.npi)}" title="${esc(e.cms.name)}">Referral profile (CMS) ↗</a>` : `<a class="btn ghost" href="../#/search${qs({ q: e.name.split(/ at | of /)[0] })}">Find in referral directory ↗</a>`}</div></div>
      <div class="kv-grid" style="margin:14px 0 18px">
        ${stat(meter(e.score), 'Demand score')}${stat(fmt(e.postings), 'Open postings')}${stat(Object.keys(e.roles).length, 'Role families')}${stat(pctf(e.urgent_share), 'With urgency signals')}${stat(days(e.median_age), 'Median days open', null, `oldest ${days(e.oldest_age)}`)}${stat(e.newest_posted ? esc(e.newest_posted) : '—', 'Most recent posting')}
      </div>
      <div class="grid cols-2">
        <div class="card"><h2>${e.is_agency ? 'Competitor notes' : 'Talking points'}</h2><p class="sub">Generated from the postings below; verify before the call.</p><ul class="plain talk">${e.talking_points.map((t) => `<li>${esc(t)}</li>`).join('')}</ul>
          <h3 style="margin-top:16px">Signals</h3><ul class="sig" style="padding-left:18px">${e.signals.map((s) => `<li>${esc(s)}</li>`).join('') || '<li class="muted">Single posting; no aggregate signals yet.</li>'}</ul></div>
        <div class="card"><h2>Score breakdown</h2><p class="sub">Each part against its maximum.</p><div class="score-parts">${hbars(Object.keys(partsMax).map((k) => ({ label: partsLabel[k], value: e.score_parts[k], of: partsMax[k], title: `${partsLabel[k]}: ${e.score_parts[k]} of ${partsMax[k]}` })), { max: 40, caption: 'Score parts' })}</div>
          <h3 style="margin-top:16px">Pay vs market</h3>
          ${e.pay.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Role</th><th class="num">Their median</th><th class="num">Market (${esc(st || 'US')})</th><th class="num">Diff</th></tr></thead><tbody>${e.pay.map((p) => `<tr><td>${esc(roleLabel(p.role))} <span class="muted">(${p.n})</span></td><td class="num">${hr(p.employer_median)}</td><td class="num">${hr(p.market_median)}</td><td class="num ${p.diff_pct < 0 ? 'down' : 'up'}">${p.diff_pct > 0 ? '+' : ''}${p.diff_pct}%</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">No comparable pay figures.</div>'}
          ${mk ? `<p class="note">Market context: ${esc(stateName(st))} has ${fmt(mk.postings)} live postings from ${fmt(mk.employers)} facility employers and ${fmt(mk.agencies)} agencies. <a href="#/markets/${esc(st)}">Open market</a></p>` : ''}</div>
      </div>
      ${outreachCard(e)}
      <div class="card"><h2>Postings (${fmt(js.length)})</h2>${roleLegend()}<div id="tbl"></div></div>`;
    wireCopy(app);
    renderTable(document.getElementById('tbl'), { rows: js, sort: 'posted', dir: 'desc', cols: jobCols({ employer: false }), csv: jobCsv(`${e.key.replace(/\s+/g, '-')}-postings.csv`) });
  }

  // ---- Postings --------------------------------------------------------
  function jobCols(opts = {}) {
    const cols = [
      { key: 'title', label: 'Title', cls: 'wrap', render: (j) => (j.url ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>` : esc(j.title)) + `<span class="sub">${esc(j.job_type || '')}</span>` },
    ];
    if (opts.employer !== false) cols.push({ key: 'company', label: 'Employer', cls: 'wrap', render: (j) => { const e = D.empByKey.get(j.employer_key); return (e ? elink(e, j.company) : esc(j.company)) + `<span class="sub">${sbadge(j.setting)}</span>`; } });
    cols.push(
      { key: 'role', label: 'Role', render: (j) => rbadge(j.role) },
      { key: 'location', label: 'Location', cls: 'nowrap', render: (j) => esc(j.location) },
      { key: 'posted', label: 'Posted', cls: 'nowrap', render: (j) => `${esc(j.posted || '—')}<span class="sub">${j.age_days != null ? days(j.age_days) + ' open' : ''}</span>` },
      { key: 'pay', label: 'Pay', num: true, get: (j) => j.pay.hourly_mid, render: (j) => (j.pay.hourly_mid ? `${hr(j.pay.hourly_mid)}${j.pay.outlier ? ' <span class="muted" title="Excluded from benchmarks">⚑</span>' : ''}<span class="sub">${esc(j.compensation || '')}</span>` : `<span class="muted">${esc(j.compensation || 'Not listed')}</span>`) },
      { key: 'flags', label: 'Signals', cls: 'wrap', sortable: false, render: (j) => j.flags.map(flagChip).join('') || '<span class="muted">—</span>' },
    );
    if (D.meta.snapshots.length > 1) cols.push({ key: 'status', label: 'Status', render: (j) => esc(j.status) + `<span class="sub">seen ${j.seen}×</span>` });
    return cols;
  }
  const jobCsv = (name) => ({ name, header: ['Title', 'Employer', 'Setting', 'Role', 'Location', 'State', 'Posted', 'Days open', 'Job type', 'Compensation (listed)', 'Hourly midpoint', 'Signals', 'Status', 'First seen', 'Last seen', 'URL'],
    row: (j) => [j.title, j.company, settingLabel(j.setting), roleLabel(j.role), j.location, j.state, j.posted, j.age_days, j.job_type, j.compensation, j.pay.hourly_mid, j.flags.map((f) => D.meta.flags[f]).join('; '), j.status, j.first_seen, j.last_seen, j.url] });

  function viewJobs(q) {
    setTitle('Postings');
    const f = { q: q.q || '', st: q.st || '', role: q.role || '', setting: q.setting || '', flag: q.flag || '', kind: q.kind || 'all', age: q.age || '' };
    app.innerHTML = `<div class="page-head"><h1>Postings</h1><p>Every distinct posting in the sample, normalized. Pay is the listed range midpoint converted to hourly. ${asofTag()}</p></div>
      <div class="card tight" id="fbar">${filtersBar([
        { id: 'q', label: 'Search', value: f.q, placeholder: 'Title, employer or city' },
        { id: 'st', label: 'State', type: 'select', value: f.st, options: stateOptions() },
        { id: 'role', label: 'Role', type: 'select', value: f.role, options: roleOptions() },
        { id: 'setting', label: 'Care setting', type: 'select', value: f.setting, options: settingOptions() },
        { id: 'flag', label: 'Urgency signal', type: 'select', value: f.flag, options: [['', 'Any or none'], ['any', 'Has any signal']].concat(Object.entries(D.meta.flags)) },
        { id: 'kind', label: 'Posted by', type: 'select', value: f.kind, options: [['all', 'Everyone'], ['fac', 'Facilities only'], ['agy', 'Agencies only']] },
        { id: 'age', label: 'Posted', type: 'select', value: f.age, options: [['', 'Any time'], ['14', 'Last 14 days'], ['45', 'Last 45 days'], ['old', 'Open 45+ days']] },
      ])}</div>
      <div class="card" id="tbl"></div>`;
    const apply = () => {
      const v = readFilters(document.getElementById('fbar'));
      const toks = tokens(v.q);
      let rows = D.live;
      if (v.st) rows = rows.filter((j) => (j.state || 'US') === v.st);
      if (v.role) rows = rows.filter((j) => j.role === v.role);
      if (v.setting) rows = rows.filter((j) => j.setting === v.setting);
      if (v.flag === 'any') rows = rows.filter((j) => j.flags.length); else if (v.flag) rows = rows.filter((j) => j.flags.includes(v.flag));
      if (v.kind === 'fac') rows = rows.filter((j) => !j.is_agency); else if (v.kind === 'agy') rows = rows.filter((j) => j.is_agency);
      if (v.age === 'old') rows = rows.filter((j) => j.age_days != null && j.age_days >= 45); else if (v.age) rows = rows.filter((j) => j.age_days != null && j.age_days <= Number(v.age));
      if (toks.length) rows = rows.filter((j) => matches(j.title + ' ' + j.company + ' ' + j.location, toks));
      history.replaceState(null, '', '#/jobs' + qs(v));
      return rows;
    };
    const t = renderTable(document.getElementById('tbl'), { rows: apply(), cols: jobCols(), sort: q.sort === 'age' ? 'posted' : 'posted', dir: q.sort === 'age' ? 'asc' : 'desc', pageSize: 50, csv: jobCsv(`postings-${D.meta.asof}.csv`) });
    document.getElementById('fbar').addEventListener('input', () => t.redraw(apply()));
    document.getElementById('fbar').addEventListener('change', () => t.redraw(apply()));
  }

  // ---- Markets ---------------------------------------------------------
  function viewMarkets(st) {
    if (st && D.markets.states[st]) return viewMarket(st);
    setTitle('Markets');
    const states = statesPresent().map((s) => Object.assign({ st: s }, D.markets.states[s]));
    app.innerHTML = `<div class="page-head"><h1>Markets</h1><p>Demand by state and metro. Coverage follows the query plan, so a quiet state may simply be one nobody searched. ${asofTag()}</p></div>
      <div class="state-grid" style="margin-bottom:18px">${states.map((s) => `<a class="state-card" href="#/markets/${s.st}"><b>${esc(s.name)}</b><small>${fmt(s.postings)} postings · ${fmt(s.employers)} employers · ${fmt(s.tier_a + s.tier_b)} priority leads</small><div style="margin-top:6px">${segbar(s.roles, s.postings)}</div></a>`).join('')}</div>
      ${roleLegend()}
      <div class="card"><h2>Metros</h2><p class="sub">Cities with at least two postings in the sample.</p><div id="tbl"></div></div>`;
    renderTable(document.getElementById('tbl'), { rows: D.markets.metros, sort: 'postings', dir: 'desc', pageSize: 40, cols: [
      { key: 'city', label: 'City', render: (m) => `<a href="#/jobs${qs({ q: m.city, st: m.state })}">${esc(m.city)}</a>` },
      { key: 'state', label: 'State', render: (m) => `<a href="#/markets/${esc(m.state)}">${esc(m.state)}</a>` },
      { key: 'postings', label: 'Postings', num: true },
      { key: 'employers', label: 'Employers', num: true },
      { key: 'agencies', label: 'Agencies', num: true },
      { key: 'roles', label: 'Role mix', sortable: false, render: (m) => segbar(m.roles, m.postings) },
      { key: 'urgent_share', label: 'Urgent', num: true, render: (m) => pctf(m.urgent_share) },
      { key: 'median_age', label: 'Median open', num: true, render: (m) => days(m.median_age) },
      { key: 'top', label: 'Top employers', cls: 'wrap', sortable: false, render: (m) => m.top_employers.map((k) => { const e = D.empByKey.get(k); return e ? elink(e) : esc(k); }).join(', ') || '—' },
    ] });
  }

  function viewMarket(st) {
    const m = D.markets.states[st];
    setTitle(stateName(st));
    const js = D.live.filter((j) => (j.state || 'US') === st);
    const emps = D.employers.filter((e) => e.states.includes(st));
    const fac = emps.filter((e) => !e.is_agency).sort((a, b) => b.score - a.score);
    const agy = emps.filter((e) => e.is_agency);
    const rank = (o, label, href) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: label(k), value: v, href: href(k) }));
    const payRows = D.meta.role_order.map((r) => ({ r, s: benchFor(r, st), n: benchFor(r, 'ALL') })).filter((x) => x.s && x.s.n >= 2);
    const payMax = Math.max(1, ...payRows.map((x) => Math.max(x.s.p75, x.n ? x.n.p75 : 0))) * 1.05;
    app.innerHTML = `
      <div class="breadcrumb"><a href="#/markets">Markets</a> › ${esc(stateName(st))}</div>
      <div class="page-head"><h1>${esc(stateName(st))}</h1><p>${fmt(m.postings)} live postings from ${fmt(m.employers)} facility employers and ${fmt(m.agencies)} staffing agencies. ${asofTag()}</p></div>
      <div class="kpis">
        ${stat(fmt(m.postings), 'Live postings', '#/jobs' + qs({ st }))}${stat(fmt(m.employers), 'Facility employers', '#/employers' + qs({ st }))}${stat(fmt(m.tier_a + m.tier_b), 'Priority leads', '#/employers' + qs({ st, tier: 'AB' }))}${stat(pctf(m.urgent_share), 'With urgency signals')}${stat(days(m.median_age), 'Median days open')}${stat(fmt(m.agencies), 'Agencies posting', '#/employers' + qs({ st, kind: 'agy' }))}
      </div>
      <div class="grid cols-2-3">
        <div>
          <div class="card"><h2>Demand by role</h2>${hbars(rank(m.roles, roleLabel, (k) => '#/jobs' + qs({ st, role: k })), { caption: 'Postings by role' })}</div>
          <div class="card"><h2>Demand by setting</h2>${hbars(rank(m.settings, settingLabel, (k) => '#/jobs' + qs({ st, setting: k })), { caption: 'Postings by setting' })}</div>
        </div>
        <div>
          <div class="card"><div class="row between"><h2>Top employers</h2><a class="btn ghost" href="#/employers${qs({ st })}">All in ${esc(st)}</a></div>
            ${fac.slice(0, 10).map((e) => `<div class="lead">${tier(e)}<div class="who">${elink(e)} ${sbadge(e.setting)}<small>${esc(e.cities.slice(0, 3).join(', '))} · ${esc(e.signals.slice(0, 2).join(' · ') || 'single posting')}</small></div><div class="num"><div class="n">${fmt(e.postings)} <small class="muted">open</small></div>${meter(e.score)}</div></div>`).join('') || '<div class="empty">No facility employers.</div>'}
            ${agy.length ? `<p class="note">Agencies active here: ${agy.map((e) => elink(e)).join(', ')}.</p>` : ''}</div>
          <div class="card"><h2>Advertised pay vs national</h2><p class="sub">State band (p25–p75, median tick) with the national median as a thin reference line.</p>
            <div class="table-wrap"><table class="data"><thead><tr><th>Role</th><th class="num">n</th><th class="num">State median</th><th class="num">National</th><th>Range</th></tr></thead><tbody>
            ${payRows.map((x) => `<tr><td>${esc(roleLabel(x.r))}</td><td class="num">${x.s.n}</td><td class="num">${hr(x.s.median)}</td><td class="num muted">${x.n ? hr(x.n.median) : '—'}</td><td>${rangebar(x.s, payMax, x.n && x.n.median)}</td></tr>`).join('') || '<tr><td colspan="5" class="empty">Not enough pay data.</td></tr>'}</tbody></table></div></div>
        </div>
      </div>
      <div class="card"><h2>Metros in ${esc(stateName(st))}</h2><div id="tbl"></div></div>`;
    renderTable(document.getElementById('tbl'), { rows: D.markets.metros.filter((x) => x.state === st), sort: 'postings', dir: 'desc', cols: [
      { key: 'city', label: 'City', render: (x) => `<a href="#/jobs${qs({ q: x.city, st })}">${esc(x.city)}</a>` },
      { key: 'postings', label: 'Postings', num: true }, { key: 'employers', label: 'Employers', num: true },
      { key: 'roles', label: 'Role mix', sortable: false, render: (x) => segbar(x.roles, x.postings) },
      { key: 'urgent_share', label: 'Urgent', num: true, render: (x) => pctf(x.urgent_share) },
      { key: 'top', label: 'Top employers', cls: 'wrap', sortable: false, render: (x) => x.top_employers.map((k) => { const e = D.empByKey.get(k); return e ? elink(e) : esc(k); }).join(', ') || '—' },
    ], empty: 'No city has two or more postings here yet.' });
    void js;
  }

  // ---- Pay -------------------------------------------------------------
  function viewPay(q) {
    setTitle('Pay benchmarks');
    const st = q.st || 'ALL';
    const role = q.role || '';
    app.innerHTML = `<div class="page-head"><h1>Advertised pay</h1><p>Hourly midpoint of the posted range (yearly ÷ 2,080, weekly ÷ 40, monthly ÷ 173). Use the p75 as the ceiling facilities are already paying when you price a bill rate. ${asofTag()}</p></div>
      <div class="card tight" id="fbar">${filtersBar([
        { id: 'st', label: 'Market', type: 'select', value: st, options: [['ALL', 'National (all states)']].concat(statesPresent().map((s) => [s, stateName(s)])) },
        { id: 'role', label: 'Role (state breakdown)', type: 'select', value: role, options: roleOptions() },
      ])}</div>
      <div class="card" id="byRole"></div>
      <div class="card" id="byState"></div>
      <p class="note">Stipend-style figures (travel packages, live-in day rates, obvious typos) are flagged ⚑ in the postings table and excluded here. Rows need at least two postings with pay; medians from fewer than five are indicative only.</p>`;
    const draw = () => {
      const v = readFilters(document.getElementById('fbar'));
      history.replaceState(null, '', '#/pay' + qs({ st: v.st === 'ALL' ? '' : v.st, role: v.role }));
      const rows = D.meta.role_order.map((r) => ({ r, b: benchFor(r, v.st), n: benchFor(r, 'ALL') })).filter((x) => x.b && x.b.n >= 2);
      const max = Math.max(1, ...rows.map((x) => Math.max(x.b.p75, x.n ? x.n.p75 : 0))) * 1.05;
      document.getElementById('byRole').innerHTML = `<h2>By role · ${esc(v.st === 'ALL' ? 'national' : stateName(v.st))}</h2><p class="sub">Band is p25 to p75, tick is the median${v.st !== 'ALL' ? ', thin line is the national median' : ''}.</p>
        <div class="table-wrap"><table class="data"><thead><tr><th>Role</th><th class="num">Postings</th><th class="num">p25</th><th class="num">Median</th><th class="num">p75</th>${v.st !== 'ALL' ? '<th class="num">National median</th>' : ''}<th>Range</th></tr></thead><tbody>
        ${rows.map((x) => `<tr><td><a href="#/jobs${qs({ role: x.r, st: v.st === 'ALL' ? '' : v.st })}">${esc(roleLabel(x.r))}</a></td><td class="num">${x.b.n}</td><td class="num">${hr(x.b.p25)}</td><td class="num"><b>${hr(x.b.median)}</b></td><td class="num">${hr(x.b.p75)}</td>${v.st !== 'ALL' ? `<td class="num muted">${x.n ? hr(x.n.median) : '—'}</td>` : ''}<td>${rangebar(x.b, max, v.st !== 'ALL' && x.n ? x.n.median : null)}</td></tr>`).join('') || '<tr><td colspan="7" class="empty">Not enough pay data for this market.</td></tr>'}</tbody></table></div>`;
      const r2 = v.role || 'CNA';
      const srows = D.bench.filter((b) => b.role === r2 && b.state !== 'ALL' && b.n >= 2).sort((a, b) => b.median - a.median);
      const nat = benchFor(r2, 'ALL');
      const smax = Math.max(1, ...srows.map((b) => b.p75), nat ? nat.p75 : 0) * 1.05;
      document.getElementById('byState').innerHTML = `<h2>${esc(roleLabel(r2))} by state</h2><p class="sub">Where this role is paid most in the sample${nat ? `; national median ${hr(nat.median)} across ${nat.n} postings` : ''}.</p>
        <div class="table-wrap"><table class="data"><thead><tr><th>State</th><th class="num">Postings</th><th class="num">p25</th><th class="num">Median</th><th class="num">p75</th><th>Range</th></tr></thead><tbody>
        ${srows.map((b) => `<tr><td><a href="#/markets/${esc(b.state)}">${esc(stateName(b.state))}</a></td><td class="num">${b.n}</td><td class="num">${hr(b.p25)}</td><td class="num"><b>${hr(b.median)}</b></td><td class="num">${hr(b.p75)}</td><td>${rangebar(b, smax, nat && nat.median)}</td></tr>`).join('') || '<tr><td colspan="6" class="empty">Not enough pay data.</td></tr>'}</tbody></table></div>`;
    };
    draw();
    document.getElementById('fbar').addEventListener('change', draw);
  }


  // ---- Outreach --------------------------------------------------------
  function viewOutreach(q) {
    setTitle('Outreach');
    const rows = D.outreach;
    const c = D.meta.counts;
    const f = { q: q.q || '', st: q.st || '', setting: q.setting || '', status: q.status || '', tier: q.tier || '' };
    app.innerHTML = `<div class="page-head"><h1>Outreach</h1><p>Employers that fit your recruiting lines, with a draft email built from their own postings. Add the administrator's contact to <code>jobs/contacts.csv</code>, rebuild, and the Email button opens a ready-to-send message in your mail client. ${asofTag()}</p></div>
      <div class="kpis" style="grid-template-columns:repeat(4,1fr)">
        ${stat(fmt(c.targets), 'Target employers', null, 'fit the rules in bd_config.json')}
        ${stat(fmt(c.targets_with_email), 'With an email address', null, `${fmt(c.targets - c.targets_with_email)} still need a contact`)}
        ${stat(fmt(c.targets_contacted), 'Contacted', null, 'sent, replied or meeting')}
        ${stat(fmt(rows.filter((r) => r.contact && r.contact.contact_name).length), 'Named contact found', null, 'name and title from public sources')}
      </div>
      <div class="card tight" id="fbar">${filtersBar([
        { id: 'q', label: 'Search', value: f.q, placeholder: 'Employer, chain, city or contact' },
        { id: 'st', label: 'State', type: 'select', value: f.st, options: stateOptions() },
        { id: 'setting', label: 'Care setting', type: 'select', value: f.setting, options: settingOptions().filter((o) => o[0] !== 'AGENCY') },
        { id: 'tier', label: 'Lead tier', type: 'select', value: f.tier, options: [['', 'All tiers'], ['AB', 'A and B'], ['A', 'A'], ['B', 'B'], ['C', 'C']] },
        { id: 'status', label: 'Status', type: 'select', value: f.status, options: [['', 'All statuses']].concat(D.meta.bd.statuses.map((s) => [s, STATUS_LABEL[s] || s])) },
      ])}</div>
      <div class="card" id="tbl"></div>
      <p class="note">Fit rules: settings ${(D.meta.bd.fit.settings || []).map(settingLabel).join(', ') || 'any'}; roles ${(D.meta.bd.fit.roles_any || []).map(roleLabel).join(', ') || 'any'}; tiers ${(D.meta.bd.fit.tiers || []).join(', ') || 'any'}; agencies excluded. Sender details and pitch wording live in <code>jobs/bd_config.json</code>. Drafts carry a physical address line and an opt-out sentence for CAN-SPAM; fill in the sender placeholders before sending.</p>`;
    const cols = [
      { key: 'tier', label: 'Tier', render: (r) => `<span class="tier ${esc(r.tier)}">${esc(r.tier)}</span>` },
      { key: 'score', label: 'Score', num: true },
      { key: 'name', label: 'Employer', cls: 'wrap', render: (r) => `<a href="#/e/${encodeURIComponent(r.key)}">${esc(r.name)}</a><span class="sub">${sbadge(r.setting)} ${esc(where(r))}</span>` },
      { key: 'postings', label: 'Open', num: true },
      { key: 'why', label: 'Why now', cls: 'wrap', sortable: false, render: (r) => `<span class="sig">${esc(r.fit_reasons[0] || '')}${r.flags.length ? '<br>' + r.flags.slice(0, 2).map(flagChip).join('') : ''}</span>` },
      { key: 'contact', label: 'Contact', cls: 'wrap', get: (r) => (r.contact.contact_name || '') + (r.contact.email || ''), render: (r) => r.contact.contact_name || r.contact.email || r.contact.phone
          ? `${esc(r.contact.contact_name || '')}${r.contact.contact_title ? `<span class="sub">${esc(r.contact.contact_title)}</span>` : ''}${r.contact.email ? `<span class="sub"><a href="mailto:${esc(r.contact.email)}">${esc(r.contact.email)}</a></span>` : ''}${r.contact.phone ? `<span class="sub">${esc(r.contact.phone)}</span>` : ''}${r.contact.website ? `<span class="sub"><a href="https://${esc(r.contact.website.replace(/^https?:\/\//, ''))}" target="_blank" rel="noopener">${esc(r.contact.website.replace(/^https?:\/\//, ''))}</a></span>` : ''}`
          : `<span class="muted">Not found yet</span><span class="sub"><a href="${esc(r.indeed)}" target="_blank" rel="noopener">Indeed ↗</a> · <a href="https://www.google.com/search?q=${encodeURIComponent(r.name + ' ' + (r.cities[0] || '') + ' administrator')}" target="_blank" rel="noopener">Search ↗</a></span>` },
      { key: 'status', label: 'Status', render: (r) => statusChip(r.status) },
      { key: 'act', label: 'Draft', sortable: false, cls: 'nowrap', render: (r) => `${r.contact.email ? `<a class="btn gold" href="${mailto(r)}">Email</a> ` : ''}${copyBtn(r.subject + '\n\n' + r.body, 'Copy draft')}` },
    ];
    const apply = () => {
      const v = readFilters(document.getElementById('fbar'));
      const toks = tokens(v.q);
      let out = rows;
      if (v.st) out = out.filter((r) => r.states.includes(v.st));
      if (v.setting) out = out.filter((r) => r.setting === v.setting);
      if (v.tier) out = out.filter((r) => v.tier.includes(r.tier));
      if (v.status) out = out.filter((r) => r.status === v.status);
      if (toks.length) out = out.filter((r) => matches(r.name + ' ' + r.chain + ' ' + r.cities.join(' ') + ' ' + (r.contact.contact_name || '') + ' ' + (r.contact.email || ''), toks));
      history.replaceState(null, '', '#/outreach' + qs(v));
      return out;
    };
    const t = renderTable(document.getElementById('tbl'), { rows: apply(), cols, sort: 'score', dir: 'desc', pageSize: 50, empty: 'No targets match.',
      csv: { name: `outreach-${D.meta.asof}.csv`, header: ['Status', 'Tier', 'Score', 'Employer', 'Chain', 'Setting', 'States', 'Cities', 'Open postings', 'Contact', 'Title', 'Email', 'Phone', 'Website', 'Subject', 'Body'],
        row: (r) => [STATUS_LABEL[r.status] || r.status, r.tier, r.score, r.name, r.chain, settingLabel(r.setting), r.states.join('; '), r.cities.join('; '), r.postings, r.contact.contact_name, r.contact.contact_title, r.contact.email, r.contact.phone, r.contact.website, r.subject, r.body] } });
    const redraw = () => { t.redraw(apply()); wireCopy(document.getElementById('tbl')); };
    wireCopy(document.getElementById('tbl'));
    document.getElementById('fbar').addEventListener('input', redraw);
    document.getElementById('fbar').addEventListener('change', redraw);
    document.getElementById('tbl').addEventListener('click', (e) => { if (e.target.matches('[data-more],[data-all],th.sortable')) setTimeout(() => wireCopy(document.getElementById('tbl')), 0); });
  }

  function outreachCard(e) {
    const r = D.outreach.find((x) => x.key === e.key);
    if (!r) return `<div class="card"><h2>Outreach</h2><p class="sub">Not a target under the current fit rules.</p><ul class="sig" style="padding-left:18px">${(e.fit ? e.fit.reasons : []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
    const c = r.contact || {};
    return `<div class="card"><div class="row between"><div><h2>Outreach</h2><p class="sub">${statusChip(r.status)} · ${esc(r.fit_reasons.join(' · '))}</p></div>
        <div class="row">${c.email ? `<a class="btn gold" href="${mailto(r)}">Email ${esc(c.contact_name ? c.contact_name.split(' ')[0] : 'administrator')}</a>` : ''}${copyBtn(r.subject + '\n\n' + r.body, 'Copy draft')}</div></div>
      <div class="grid cols-2-3">
        <div><h3>Contact</h3>${c.contact_name || c.email || c.phone || c.website ? `<dl class="kv">${c.contact_name ? `<dt>Name</dt><dd>${esc(c.contact_name)}</dd>` : ''}${c.contact_title ? `<dt>Title</dt><dd>${esc(c.contact_title)}</dd>` : ''}${c.email ? `<dt>Email</dt><dd><a href="mailto:${esc(c.email)}">${esc(c.email)}</a></dd>` : ''}${c.phone ? `<dt>Phone</dt><dd>${esc(c.phone)}</dd>` : ''}${c.website ? `<dt>Website</dt><dd><a href="https://${esc(c.website.replace(/^https?:\/\//, ''))}" target="_blank" rel="noopener">${esc(c.website)}</a></dd>` : ''}${c.notes ? `<dt>Notes</dt><dd style="font-weight:400">${esc(c.notes)}</dd>` : ''}</dl>` : `<p class="muted">No contact on file. Add a row for “${esc(e.name)}” to <code>jobs/contacts.csv</code> and rebuild.</p>`}</div>
        <div><h3>Draft</h3><div class="draft"><b>${esc(r.subject)}</b><pre class="mail">${esc(r.body)}</pre></div></div>
      </div></div>`;
  }

  // ---- Search ----------------------------------------------------------
  function viewSearch(q) {
    const query = (q.q || '').trim();
    setTitle('Search: ' + query);
    const toks = tokens(query);
    const emps = D.employers.filter((e) => matches(e.name + ' ' + e.chain + ' ' + e.cities.join(' '), toks)).slice(0, 50);
    const js = D.live.filter((j) => matches(j.title + ' ' + j.company + ' ' + j.location, toks));
    app.innerHTML = `<div class="page-head"><h1>Search results</h1><p>“${esc(query)}” · ${asofTag()}</p></div>
      <div class="grid cols-2-3">
        <div class="card"><h2>Employers <small>(${fmt(emps.length)})</small></h2>${emps.length ? emps.map((e) => `<div class="lead">${tier(e)}<div class="who">${elink(e)} ${sbadge(e.setting)}<small>${esc(where(e))}</small></div><div class="num"><div class="n">${fmt(e.postings)} <small class="muted">open</small></div></div></div>`).join('') : '<div class="empty">No employers match.</div>'}</div>
        <div class="card"><h2>Postings <small>(${fmt(js.length)})</small></h2><div id="tbl"></div></div></div>`;
    renderTable(document.getElementById('tbl'), { rows: js, sort: 'posted', dir: 'desc', cols: jobCols(), empty: 'No postings match.', csv: jobCsv('search.csv') });
  }

  // ---- Method ----------------------------------------------------------
  function viewAbout() {
    setTitle('Method');
    const c = D.meta.counts;
    app.innerHTML = `<div class="page-head"><h1>Method</h1><p>What this board is, how the numbers are made, and how to refresh it. ${asofTag()}</p></div>
      <div class="about method">
      <div class="card"><h2>The idea</h2>
        <p>A job posting is the clearest public signal that a facility is short-staffed. It says which role, where, on which shift, how long the seat has been open and what they are willing to pay. Seen one at a time on Indeed that is noise; grouped by employer and market, and compared against the pay other facilities advertise, it becomes a prospect list and a rate card. This board does that grouping. It is a companion to the <a href="../">Referral Directory</a>: that site shows where a facility's patients come from; this one shows who it is trying to hire.</p></div>
      <div class="card"><h2>Data</h2>
        <p>Postings are pulled through the Indeed connector (the <code>search_jobs</code> tool) with a fixed plan of ${fmt(D.meta.coverage.queries_planned)} searches (role × market). Each search returns up to 10 postings, which is why the board calls itself a sample. The raw results are saved verbatim under <code>jobs/in/&lt;date&gt;/</code>; <code>jobs_build.py</code> parses them, so there is no hand-editing of data. Current pull: ${fmt(D.meta.coverage.queries_run)} searches, ${fmt(c.postings_all)} distinct postings, ${fmt(c.employers)} facility employers, ${fmt(c.agencies)} agencies, ${fmt(c.states)} states.</p>
        <h3>Normalization</h3>
        <ul>
          <li><b>Role family</b> from the title: nursing leadership (DON, ADON, supervisor, unit manager), MDS / clinical specialist (MDS, wound care, infection control, educator, case manager, admissions), NP / PA, therapy &amp; respiratory, LPN / LVN, CNA / aide / caregiver, RN. When a title lists several, the first mentioned wins; a bare “PT” is read as part-time.</li>
          <li><b>Care setting</b> from the employer name, then the title: nursing home / post-acute, assisted or senior living, home health, hospice, hospital. Known operators are pinned in <code>jobs/overrides.json</code>.</li>
          <li><b>Agencies</b> are detected from a name list plus words such as staffing, placement, recruiting and travel nursing. They stay in the postings table and the pay benchmarks (their advertised rates are useful) but are excluded from the lead list.</li>
          <li><b>Pay</b> is the midpoint of the listed range, converted to hourly (year ÷ 2,080; week ÷ 40; month ÷ 173.3; day ÷ 8). Figures far from the role's national median, travel packages and live-in day rates are flagged and left out of benchmarks.</li>
          <li><b>Urgency signals</b> from the title and job type: sign-on or retention bonus, nights / evenings, weekends, per diem / PRN / temp / travel, “hiring now” language, and multi-site or multi-shift postings.</li>
          <li><b>Posting age</b> is the pull date minus Indeed's posted-on date. Evergreen postings inflate it, which is itself a signal.</li>
          <li><b>De-duplication</b> by URL, then by title + employer + location + date. Across pulls a posting keeps its first-seen and last-seen dates; it is marked closed only when a search that found it was re-run and it did not come back.</li>
        </ul></div>
      <div class="card"><h2>Demand score (0–100)</h2>
        <div class="table-wrap"><table class="data"><thead><tr><th>Part</th><th class="num">Max</th><th>How</th></tr></thead><tbody>
          <tr><td>Volume</td><td class="num">40</td><td>12 × ln(1 + open postings). One posting ≈ 8, three ≈ 17, ten ≈ 29.</td></tr>
          <tr><td>Role breadth</td><td class="num">15</td><td>5 per distinct role family. Hiring across aides, nurses and leadership points to a structural gap, not one resignation.</td></tr>
          <tr><td>Urgency</td><td class="num">20</td><td>20 × share of postings carrying an urgency signal.</td></tr>
          <tr><td>Age &amp; reposts</td><td class="num">15</td><td>15 × share of postings open more than 45 days, plus 2 per repeated title.</td></tr>
          <tr><td>Pay pressure</td><td class="num">10</td><td>10 if the employer's median pay for a role is more than 3% below the market median for that role and state (they will struggle to hire at that rate); 6 if more than 8% above (they are competing hard); otherwise 3.</td></tr>
        </tbody></table></div>
        <p>Share-based parts are multiplied by 1 − 0.5<sup>n</sup>, so one posting counts half, two count three quarters, and a lone evergreen posting cannot outrank a facility with nine openings. <b>Tier A</b> is 60 or more, <b>Tier B</b> 40 or more, <b>Tier C</b> the rest. Talking points are template sentences chosen from the signals; they are prompts for the call, not facts about the facility.</p></div>
      <div class="card"><h2>Refreshing the board</h2>
        <div class="step"><b class="n">1</b><div><b>Run the query plan.</b> In a Claude session with the Indeed connector, run every search in <code>jobs/queries.json</code> (<code>python jobs_build.py --print-queries</code> lists them). Save each result verbatim as <code>jobs/in/&lt;YYYY-MM-DD&gt;/&lt;slug&gt;.md</code> with <code>search:</code> and <code>location:</code> header lines; note empty searches in <code>_queries.log</code>. Add new role × market pairs to the plan when the business expands.</div></div>
        <div class="step"><b class="n">2</b><div><b>Build.</b> <pre>python jobs_build.py</pre> writes <code>jobs/data/*.json</code>, prints coverage against the plan, and now has two pulls to compare: new, continuing and closed postings per employer appear in the Trend card and the Status column.</div></div>
        <div class="step"><b class="n">3</b><div><b>Publish.</b> Commit and push; the site is static and deploys with the Referral Directory. Any CSV with title, company, location, posted, job_type, compensation and url columns (an Indeed Publisher export, a scraper, a purchased feed) can be dropped into the same snapshot folder.</div></div>
        <p class="note">Suggested cadence: weekly. Weekly pulls make posting age and close rates meaningful and keep the lead list fresh for the sales team.</p></div>
      <div class="card"><h2>Limits</h2><ul>${D.meta.limits.map((l) => `<li>${esc(l)}</li>`).join('')}
        <li>Indeed postings are public job advertisements; the board links to them and stores only the fields shown.</li></ul></div>
      <div class="card"><h2>Query plan in the last pull</h2><ul style="columns:2;font-size:.9rem">${Array.from(new Set(D.live.flatMap((j) => j.queries))).sort().map((q) => `<li>${esc(q)}</li>`).join('')}</ul>
        ${D.meta.coverage.planned_not_run.length ? `<p class="note">Planned but not run: ${D.meta.coverage.planned_not_run.map(esc).join('; ')}</p>` : ''}</div>
      </div>`;
  }

  // ---------------------------------------------------------------- router
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, query] = h.split('?');
    const parts = path.split('/').filter(Boolean).map(decodeURIComponent);
    const q = Object.fromEntries(new URLSearchParams(query || ''));
    return { parts, q };
  }
  function route() {
    const { parts, q } = parseHash();
    const page = parts[0] || 'home';
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === page || (page === 'e' && a.dataset.nav === 'employers')));
    document.getElementById('siteNav').classList.remove('open');
    window.scrollTo(0, 0);
    try {
      switch (page) {
        case 'home': viewHome(); break;
        case 'employers': viewEmployers(q); break;
        case 'e': viewEmployer(parts[1] || ''); break;
        case 'jobs': viewJobs(q); break;
        case 'markets': viewMarkets((parts[1] || '').toUpperCase()); break;
        case 'pay': viewPay(q); break;
        case 'search': viewSearch(q); break;
        case 'outreach': viewOutreach(q); break;
        case 'about': viewAbout(); break;
        default: app.innerHTML = '<div class="error">Page not found.</div>';
      }
    } catch (err) {
      app.innerHTML = `<div class="error">Something went wrong rendering this page: ${esc(err.message)}</div>`;
      console.error(err);
    }
  }

  async function init() {
    app.innerHTML = '<div class="loading">Loading postings…</div>';
    try { await loadAll(); } catch (err) {
      app.innerHTML = `<div class="error">Could not load dashboard data (${esc(err.message)}). Run <code>python jobs_build.py</code> to create <code>jobs/data/</code>.</div>`;
      return;
    }
    document.getElementById('footerData').textContent = `${D.meta.source} · as of ${D.meta.asof} · built ${D.meta.built}`;
    document.getElementById('navToggle').addEventListener('click', (e) => { const n = document.getElementById('siteNav'); n.classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', n.classList.contains('open')); });
    document.getElementById('headerSearch').addEventListener('submit', (e) => { e.preventDefault(); const v = e.target.q.value.trim(); if (v) location.hash = '#/search' + qs({ q: v }); });
    window.addEventListener('hashchange', route);
    route();
  }
  init();
})();
