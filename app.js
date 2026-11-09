/* Hospital & Doctor Referral Directory - static front end
 * Hash routes:  #/  #/hospitals[/ST]  #/doctors[/ST]  #/facilities[/ST]  #/p/{npi}  #/flows  #/trending  #/about  #/search?q=
 * Data: compressed JSON written by build.py into ./data (see README).
 */
(function () {
  'use strict';

  const CFG = Object.assign({ dataBase: 'data' }, window.DIRECTORY_CONFIG || {});
  const TYPE_LABEL = { H: 'Hospital', R: 'Rehab hospital', L: 'Long-term care hospital', S: 'Nursing home', A: 'Home health agency', C: 'Hospice', D: 'Doctor' };
  const TYPE_PLURAL = { H: 'Hospitals', R: 'Rehab hospitals', L: 'Long-term care hospitals', S: 'Nursing homes', A: 'Home health agencies', C: 'Hospices', D: 'Doctors' };
  const TYPE_COLOR = { H: '#1f4a8a', R: '#6a1b9a', L: '#4e342e', S: '#2e7d32', A: '#0277bd', C: '#ad1457', D: '#ef6c00' };
  const HOSPITAL_TYPES = ['H', 'R', 'L'];
  const FACILITY_TYPES = ['S', 'A', 'C'];

  let META = null;
  const cache = new Map();
  const app = document.getElementById('app');

  // ------------------------------------------------------------------ data
  async function fetchData(rel) {
    if (cache.has(rel)) return cache.get(rel);
    const p = (async () => {
      const res = await fetch(CFG.dataBase + '/' + rel, { cache: 'force-cache' });
      if (!res.ok) throw new Error('HTTP ' + res.status + ' loading ' + rel);
      if (!rel.endsWith('.gz')) return res.json();
      const buf = await res.arrayBuffer();
      const u8 = new Uint8Array(buf);
      if (u8[0] === 0x1f && u8[1] === 0x8b) {
        if (!('DecompressionStream' in window)) throw new Error('This browser cannot read compressed data files. Please use a current version of Chrome, Edge, Safari or Firefox.');
        const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
        return new Response(stream).json();
      }
      return JSON.parse(new TextDecoder().decode(u8)); // server already decompressed it
    })();
    cache.set(rel, p);
    p.catch(() => cache.delete(rel));
    return p;
  }
  const loadMeta = () => fetchData('meta.json');
  const loadFacilities = (st) => fetchData('facilities/' + st + '.json.gz').catch(() => ({ cols: [], rows: [] }));
  const loadDoctors = (st) => fetchData('doctors/' + st + '.json.gz').catch(() => ({ cols: [], rows: [] }));
  const loadFlows = (st) => fetchData('flows/' + st + '.json.gz').catch(() => ({ cols: [], rows: [] }));
  async function loadProvider(npi) {
    const shard = Number(npi) % META.shards;
    const data = await fetchData('providers/' + shard + '.json.gz').catch(() => ({}));
    return data[String(npi)] || null;
  }

  // --------------------------------------------------------------- helpers
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n) => (n == null || isNaN(n) ? '—' : Number(n).toLocaleString('en-US'));
  const money = (n) => (n == null ? '—' : '$' + Math.round(n).toLocaleString('en-US'));
  const pct = (n) => (n == null ? '—' : Number(n).toFixed(1) + '%');
  const badge = (t) => `<span class="badge t-${esc(t)}">${esc(TYPE_LABEL[t] || t)}</span>`;
  const plink = (npi, name) => `<a href="#/p/${esc(npi)}">${esc(name)}</a>`;
  const stars = (r) => {
    const n = Math.round(Number(r));
    if (r == null || !Number.isFinite(n) || n < 1 || n > 5) return '<span class="muted">—</span>';
    return `<span class="stars" title="${n} star rating">${'★'.repeat(n)}<span class="off">${'★'.repeat(5 - n)}</span></span>`;
  };
  const yearTag = () => `<span class="year-tag">Data year ${esc(META.year)} · ${esc(META.window_days)}-day window</span>`;
  const stateName = (st) => ((META.states || []).find((s) => s.st === st) || {}).name || st;
  const bar = (share, max = 100) => `<span class="bar" aria-hidden="true"><span style="width:${Math.max(1, Math.min(100, (share / max) * 100)).toFixed(1)}%"></span></span>`;
  const stat = (v, l, href) => `<${href ? `a href="${href}" class="stat link"` : 'div class="stat"'}><div class="v">${v}</div><div class="l">${l}</div></${href ? 'a' : 'div'}>`;
  const norm = (s) => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const tokens = (q) => norm(q).split(/[\s,]+/).filter(Boolean);
  const matches = (hay, toks) => { const h = norm(hay); return toks.every((t) => h.includes(t)); };
  const setTitle = (t) => { document.title = (t ? t + ' · ' : '') + 'Referral Directory'; };
  const qs = (obj) => { const p = new URLSearchParams(); Object.entries(obj).forEach(([k, v]) => { if (v !== '' && v != null) p.set(k, v); }); const s = p.toString(); return s ? '?' + s : ''; };

  function sortRows(rows, key, dir, numeric) {
    const m = dir === 'asc' ? 1 : -1;
    return rows.slice().sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      if (numeric) return (Number(x) - Number(y)) * m;
      return String(x).localeCompare(String(y)) * m;
    });
  }

  /** Sortable, paginated table. cols: [{key,label,num,render(row),sortable}] */
  function renderTable(container, opts) {
    const state = { sortKey: opts.sort || null, dir: opts.dir || 'desc', page: 1 };
    const pageSize = opts.pageSize || 50;
    function draw() {
      let rows = opts.rows;
      const col = opts.cols.find((c) => c.key === state.sortKey);
      if (col) rows = sortRows(rows, col.key, state.dir, col.num);
      const shown = rows.slice(0, state.page * pageSize);
      const head = opts.cols.map((c) => `<th class="${c.num ? 'num ' : ''}${c.sortable === false ? '' : 'sortable'}" data-key="${esc(c.key)}">${esc(c.label)}${state.sortKey === c.key ? `<span class="arrow">${state.dir === 'asc' ? '▲' : '▼'}</span>` : ''}</th>`).join('');
      const body = shown.map((r, i) => `<tr>${opts.cols.map((c) => `<td class="${c.num ? 'num' : ''}">${c.render ? c.render(r, i) : esc(r[c.key])}</td>`).join('')}</tr>`).join('');
      container.innerHTML = rows.length
        ? `<div class="table-wrap"><table class="data"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>
           <div class="table-foot"><span>Showing ${fmt(shown.length)} of ${fmt(rows.length)}</span>
           <span>${shown.length < rows.length ? '<button class="btn ghost" data-more>Show more</button> ' : ''}${opts.csv ? '<button class="btn ghost" data-csv>Download CSV</button>' : ''}</span></div>`
        : `<div class="empty">${esc(opts.empty || 'Nothing matches these filters.')}</div>`;
      container.querySelectorAll('th.sortable').forEach((th) => th.addEventListener('click', () => {
        const k = th.dataset.key;
        if (state.sortKey === k) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
        else { state.sortKey = k; state.dir = opts.cols.find((c) => c.key === k).num ? 'desc' : 'asc'; }
        state.page = 1; draw();
      }));
      const more = container.querySelector('[data-more]');
      if (more) more.addEventListener('click', () => { state.page++; draw(); });
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

  function stateGrid(key, pathPrefix, countKeys) {
    const states = (META.states || []).filter((s) => countKeys.some((k) => s[k] > 0));
    return `<div class="state-grid">${states.map((s) => `<a class="state-card" href="#/${pathPrefix}/${s.st}"><b>${esc(s.name)}</b><small>${countKeys.map((k) => `${fmt(s[k])} ${TYPE_PLURAL[k].toLowerCase()}`).join(' · ')}</small></a>`).join('')}</div>`;
  }

  function filtersBar(defs) {
    return `<div class="filters">${defs.map((d) => `<label>${esc(d.label)}${d.type === 'select'
      ? `<select data-f="${d.id}">${d.options.map((o) => `<option value="${esc(o[0])}" ${String(o[0]) === String(d.value || '') ? 'selected' : ''}>${esc(o[1])}</option>`).join('')}</select>`
      : `<input type="${d.type || 'search'}" data-f="${d.id}" value="${esc(d.value || '')}" placeholder="${esc(d.placeholder || '')}" ${d.min != null ? `min="${d.min}"` : ''}>`}</label>`).join('')}</div>`;
  }
  const readFilters = (root) => { const o = {}; root.querySelectorAll('[data-f]').forEach((el) => { o[el.dataset.f] = el.value; }); return o; };
  const typeOptions = (types, allLabel) => [['', allLabel]].concat(types.map((t) => [t, TYPE_PLURAL[t]]));

  // ------------------------------------------------------------------ views
  function viewHome() {
    setTitle('');
    const c = META.counts || {};
    const hospitals = (c.H || 0) + (c.R || 0) + (c.L || 0);
    app.innerHTML = `
      <section class="hero">
        <h1>Where do hospitals and doctors send their patients?</h1>
        <p>A free national directory of patient referral patterns. Look up any hospital, doctor, nursing home, home health agency or hospice and see who sends patients where, with patient counts, percentage share and rank. ${yearTag()}</p>
        <form class="search-box" id="homeSearch" role="search">
          <input type="search" name="q" placeholder="Hospital, doctor or facility name, city, ZIP code or NPI" aria-label="Search" autocomplete="off" autofocus>
          <select name="st" aria-label="State for doctor search"><option value="">Doctors in: any state (facilities only)</option>${(META.states || []).map((s) => `<option value="${s.st}">Doctors in: ${esc(s.name)}</option>`).join('')}</select>
          <button type="submit">Search</button>
        </form>
        <div class="hint">Facilities are searched nationally. To include doctors, choose a state. A 10-digit NPI jumps straight to that provider.</div>
      </section>
      <div class="grid cols-4">
        ${stat(fmt(hospitals), 'Hospitals (incl. rehab and LTCH)', '#/hospitals')}
        ${stat(fmt(c.D), 'Doctors and clinicians', '#/doctors')}
        ${stat(fmt((c.S || 0) + (c.A || 0) + (c.C || 0)), 'Nursing homes, home health and hospices', '#/facilities')}
        ${stat(fmt(META.pairs_kept), 'Referral relationships', '#/flows')}
      </div>
      <div class="grid cols-3" style="margin-top:18px">
        <div class="card"><h3>Hospitals</h3><p class="muted">Every destination a hospital discharges to: nursing homes, home health, hospice, rehab and the doctors who follow patients.</p><a class="btn" href="#/hospitals">Browse by state</a></div>
        <div class="card"><h3>Doctors</h3><p class="muted">Which facilities and specialists a physician shares patients with, by state and specialty.</p><a class="btn" href="#/doctors">Browse by state</a></div>
        <div class="card"><h3>Facilities</h3><p class="muted">Reverse view: which hospitals and doctors send patients to a nursing home, agency or hospice.</p><a class="btn" href="#/facilities">Browse by state</a></div>
      </div>
      <div class="card" style="margin-top:18px"><div class="row between"><div><h3>Trending</h3><span class="muted">Biggest referrers, biggest receivers and the fastest-growing relationships nationally.</span></div><a class="btn gold" href="#/trending">See national top lists</a></div></div>`;
    document.getElementById('homeSearch').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = e.target.q.value.trim(), st = e.target.st.value;
      if (q) location.hash = '#/search' + qs({ q, st });
    });
  }

  async function viewSearch(q) {
    const query = (q.q || '').trim();
    const st = (q.st || '').toUpperCase();
    setTitle('Search: ' + query);
    if (/^\d{10}$/.test(query)) { location.replace('#/p/' + query); return; }
    app.innerHTML = `<div class="page-head"><h1>Search results</h1><p>“${esc(query)}” ${st ? 'in ' + esc(stateName(st)) : ''}</p></div><div class="loading">Searching…</div>`;
    const toks = tokens(query);
    const fac = await fetchData('search/facilities.json.gz');
    const facHits = fac.rows.filter((r) => matches(r[2] + ' ' + r[3] + ' ' + r[4] + ' ' + r[5], toks) || r[5] === query).slice(0, 300);
    let docHits = [];
    if (st) {
      const d = await loadDoctors(st);
      docHits = d.rows.filter((r) => matches(r[1] + ' ' + r[2] + ' ' + r[3] + ' ' + r[4], toks)).slice(0, 300);
    }
    app.innerHTML = `<div class="page-head"><h1>Search results</h1><p>“${esc(query)}” ${st ? 'in ' + esc(stateName(st)) : '(facilities nationwide)'} · ${yearTag()}</p></div>
      <form class="search-box" id="againSearch" style="margin-bottom:18px">
        <input type="search" name="q" value="${esc(query)}" aria-label="Search" style="border:1px solid var(--line)">
        <select name="st"><option value="">Doctors in: any state (facilities only)</option>${(META.states || []).map((s) => `<option value="${s.st}" ${s.st === st ? 'selected' : ''}>Doctors in: ${esc(s.name)}</option>`).join('')}</select>
        <button type="submit">Search</button></form>
      <div class="grid cols-2">
        <div class="card"><h2>Facilities <small>(${fmt(facHits.length)}${facHits.length === 300 ? '+' : ''})</small></h2>
          ${facHits.length ? `<ul class="result-list">${facHits.map((r) => `<li>${badge(r[1])}<span class="name">${plink(r[0], r[2])}</span><small>${esc(r[3])}, ${esc(r[4])} ${esc(r[5])}</small></li>`).join('')}</ul>` : '<div class="empty">No facilities match.</div>'}</div>
        <div class="card"><h2>Doctors <small>${st ? `(${fmt(docHits.length)}${docHits.length === 300 ? '+' : ''})` : ''}</small></h2>
          ${st ? (docHits.length ? `<ul class="result-list">${docHits.map((r) => `<li>${badge('D')}<span class="name">${plink(r[0], r[1])}</span><small>${esc(r[2])} · ${esc(r[3])}, ${st}</small></li>`).join('')}</ul>` : '<div class="empty">No doctors match in this state.</div>')
      : '<div class="empty">Choose a state above to search doctors by name, city or ZIP.</div>'}</div>
      </div>`;
    document.getElementById('againSearch').addEventListener('submit', (e) => { e.preventDefault(); location.hash = '#/search' + qs({ q: e.target.q.value.trim(), st: e.target.st.value }); });
  }

  // ---- Hospitals -------------------------------------------------------
  async function viewHospitals(st, q) {
    if (!st) {
      setTitle('Hospitals');
      app.innerHTML = `<div class="page-head"><h1>Hospitals by state</h1><p>Choose a state to list acute-care, rehabilitation and long-term care hospitals and see where each one sends patients. ${yearTag()}</p></div>${stateGrid('H', 'hospitals', ['H'])}`;
      return;
    }
    setTitle('Hospitals in ' + stateName(st));
    app.innerHTML = `<div class="breadcrumb"><a href="#/hospitals">Hospitals</a> › ${esc(stateName(st))}</div><div class="loading">Loading hospitals…</div>`;
    const data = await loadFacilities(st);
    const rows = data.rows.filter((r) => HOSPITAL_TYPES.includes(r[1])).map((r) => ({ npi: r[0], type: r[1], name: r[2], city: r[3], zip: r[4], ccn: r[5], rating: r[6], out: r[8], inn: r[9] }));
    app.innerHTML = `<div class="breadcrumb"><a href="#/hospitals">Hospitals</a> › ${esc(stateName(st))}</div>
      <div class="page-head"><h1>Hospitals in ${esc(stateName(st))} <small class="muted">(${fmt(rows.length)})</small></h1><p>Patients sent = Medicare patients shared with any downstream provider within ${META.window_days} days. ${yearTag()}</p></div>
      <div class="card">${filtersBar([
        { id: 'q', label: 'Filter by name, city or ZIP', placeholder: 'e.g. Memorial, Brooklyn, 11201', value: q.q },
        { id: 'type', label: 'Hospital type', type: 'select', options: typeOptions(HOSPITAL_TYPES, 'All hospital types'), value: q.type },
      ])}<div id="tbl"></div></div>`;
    const cols = [
      { key: 'name', label: 'Hospital', render: (r) => `${plink(r.npi, r.name)}<span class="sub">${badge(r.type)} NPI ${esc(r.npi)}${r.ccn ? ' · CCN ' + esc(r.ccn) : ''}</span>` },
      { key: 'city', label: 'City', render: (r) => `${esc(r.city)}<span class="sub">${esc(r.zip)}</span>` },
      { key: 'rating', label: 'CMS rating', num: true, render: (r) => stars(r.rating) },
      { key: 'out', label: 'Patients sent', num: true, render: (r) => fmt(r.out) },
      { key: 'inn', label: 'Patients received', num: true, render: (r) => fmt(r.inn) },
    ];
    const apply = () => { const f = readFilters(app); const t = tokens(f.q); return rows.filter((r) => (!f.type || r.type === f.type) && (!t.length || matches(r.name + ' ' + r.city + ' ' + r.zip, t))); };
    const tbl = renderTable(document.getElementById('tbl'), { cols, rows: apply(), sort: 'out', empty: 'No hospitals match.' });
    app.querySelectorAll('[data-f]').forEach((el) => el.addEventListener('input', () => tbl.redraw(apply())));
  }

  // ---- Doctors ---------------------------------------------------------
  async function viewDoctors(st, q) {
    if (!st) {
      setTitle('Doctors');
      app.innerHTML = `<div class="page-head"><h1>Doctors by state</h1><p>Physicians, nurse practitioners, physician assistants and podiatrists who appear in the patient-sharing data, grouped by state and specialty. ${yearTag()}</p></div>${stateGrid('D', 'doctors', ['D'])}`;
      return;
    }
    setTitle('Doctors in ' + stateName(st));
    app.innerHTML = `<div class="breadcrumb"><a href="#/doctors">Doctors</a> › ${esc(stateName(st))}</div><div class="loading">Loading doctors…</div>`;
    const data = await loadDoctors(st);
    const rows = data.rows.map((r) => ({ npi: r[0], name: r[1], specialty: r[2], city: r[3], zip: r[4], out: r[5], inn: r[6] }));
    const specs = [...new Set(rows.map((r) => r.specialty))].sort();
    app.innerHTML = `<div class="breadcrumb"><a href="#/doctors">Doctors</a> › ${esc(stateName(st))}</div>
      <div class="page-head"><h1>Doctors in ${esc(stateName(st))} <small class="muted">(${fmt(rows.length)})</small></h1><p>Patients sent = Medicare patients the doctor saw before another provider within ${META.window_days} days. ${yearTag()}</p></div>
      <div class="card">${filtersBar([
        { id: 'q', label: 'Filter by name, city or ZIP', placeholder: 'e.g. Patel, Lakewood, 08701', value: q.q },
        { id: 'spec', label: 'Specialty', type: 'select', options: [['', 'All specialties']].concat(specs.map((s) => [s, s])), value: q.spec },
      ])}<div id="tbl"></div></div>`;
    const cols = [
      { key: 'name', label: 'Doctor', render: (r) => `${plink(r.npi, r.name)}<span class="sub">NPI ${esc(r.npi)}</span>` },
      { key: 'specialty', label: 'Specialty' },
      { key: 'city', label: 'City', render: (r) => `${esc(r.city)}<span class="sub">${esc(r.zip)}</span>` },
      { key: 'out', label: 'Patients sent', num: true, render: (r) => fmt(r.out) },
      { key: 'inn', label: 'Patients received', num: true, render: (r) => fmt(r.inn) },
    ];
    const apply = () => { const f = readFilters(app); const t = tokens(f.q); return rows.filter((r) => (!f.spec || r.specialty === f.spec) && (!t.length || matches(r.name + ' ' + r.city + ' ' + r.zip, t))); };
    const tbl = renderTable(document.getElementById('tbl'), { cols, rows: apply(), sort: 'out', empty: 'No doctors match.' });
    app.querySelectorAll('[data-f]').forEach((el) => el.addEventListener('input', () => tbl.redraw(apply())));
  }

  // ---- Facilities ------------------------------------------------------
  async function viewFacilities(st, q) {
    if (!st) {
      setTitle('Facilities');
      app.innerHTML = `<div class="page-head"><h1>Nursing homes, home health agencies and hospices</h1><p>Choose a state. Each facility page shows where its patients come from: the hospitals and doctors that send them, with counts and shares. ${yearTag()}</p></div>${stateGrid('S', 'facilities', ['S', 'A', 'C'])}`;
      return;
    }
    setTitle('Facilities in ' + stateName(st));
    app.innerHTML = `<div class="breadcrumb"><a href="#/facilities">Facilities</a> › ${esc(stateName(st))}</div><div class="loading">Loading facilities…</div>`;
    const data = await loadFacilities(st);
    const rows = data.rows.filter((r) => FACILITY_TYPES.includes(r[1])).map((r) => ({ npi: r[0], type: r[1], name: r[2], city: r[3], zip: r[4], ccn: r[5], rating: r[6], pac: r[7], out: r[8], inn: r[9] }));
    const type = FACILITY_TYPES.includes(q.type) ? q.type : 'S';
    app.innerHTML = `<div class="breadcrumb"><a href="#/facilities">Facilities</a> › ${esc(stateName(st))}</div>
      <div class="page-head"><h1>Facilities in ${esc(stateName(st))}</h1><p>Patients received = Medicare patients who saw a hospital or doctor before this facility within ${META.window_days} days. ${yearTag()}</p></div>
      <div class="card">
        <div class="tabs">${FACILITY_TYPES.map((t) => `<button class="tab ${t === type ? 'active' : ''}" data-type="${t}">${TYPE_PLURAL[t]} (${fmt(rows.filter((r) => r.type === t).length)})</button>`).join('')}</div>
        ${filtersBar([{ id: 'q', label: 'Filter by name, city or ZIP', placeholder: 'e.g. Gardens, Lakewood, 08701', value: q.q }])}
        <div id="tbl"></div></div>`;
    let current = type;
    const cols = [
      { key: 'name', label: 'Facility', render: (r) => `${plink(r.npi, r.name)}<span class="sub">${badge(r.type)} NPI ${esc(r.npi)}${r.ccn ? ' · CCN ' + esc(r.ccn) : ''}</span>` },
      { key: 'city', label: 'City', render: (r) => `${esc(r.city)}<span class="sub">${esc(r.zip)}</span>` },
      { key: 'rating', label: 'CMS rating', num: true, render: (r) => stars(r.rating) },
      { key: 'pac', label: 'Medicare patients served', num: true, render: (r) => fmt(r.pac) },
      { key: 'inn', label: 'Patients received', num: true, render: (r) => fmt(r.inn) },
      { key: 'out', label: 'Patients sent', num: true, render: (r) => fmt(r.out) },
    ];
    const apply = () => { const f = readFilters(app); const t = tokens(f.q); return rows.filter((r) => r.type === current && (!t.length || matches(r.name + ' ' + r.city + ' ' + r.zip, t))); };
    const tbl = renderTable(document.getElementById('tbl'), { cols, rows: apply(), sort: 'inn', empty: 'No facilities match.' });
    app.querySelectorAll('[data-f]').forEach((el) => el.addEventListener('input', () => tbl.redraw(apply())));
    app.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
      current = b.dataset.type; app.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b));
      history.replaceState(null, '', `#/facilities/${st}${qs({ type: current, q: readFilters(app).q })}`); tbl.redraw(apply());
    }));
  }

  // ---- Provider page ---------------------------------------------------
  async function viewProvider(npi, q) {
    app.innerHTML = '<div class="loading">Loading provider…</div>';
    const rec = await loadProvider(npi);
    if (!rec) {
      setTitle('Not found');
      app.innerHTML = `<div class="card"><h1>Provider not found</h1><p>NPI <b>${esc(npi)}</b> is not in this directory. It may not bill Medicare, may have fewer than ${META.min_patients} shared patients with any other provider in ${META.year}, or may be a provider type that is not included (labs, suppliers, dentists).</p><a class="btn" href="#/">Back to search</a></div>`;
      return;
    }
    const [, type, name, city, state, zip, specialty, ccn, address, rating, pacBenes, pacPay, pacStays] = rec.p;
    const [outTotal, inTotal, outPartners, inPartners] = rec.t;
    setTitle(name);
    const isDoctor = type === 'D';
    const dir = q.dir === 'in' || (!isDoctor && !HOSPITAL_TYPES.includes(type) && q.dir !== 'out') ? 'in' : 'out';
    const listPath = isDoctor ? `#/doctors/${state}` : HOSPITAL_TYPES.includes(type) ? `#/hospitals/${state}` : `#/facilities/${state}?type=${type}`;
    app.innerHTML = `
      <div class="breadcrumb"><a href="#/">Home</a> › <a href="${listPath}">${esc(TYPE_PLURAL[type])} in ${esc(stateName(state))}</a></div>
      <div class="card">
        <div class="prov-head">
          <div>
            <h1>${esc(name)}</h1>
            <div class="prov-meta">${badge(type)} ${specialty ? `<span>${esc(specialty)}</span>` : ''}<span>${esc(address ? address + ', ' : '')}${esc(city)}, ${esc(state)} ${esc(zip)}</span></div>
            <div class="prov-meta" style="margin-top:4px"><span>NPI ${esc(npi)}</span>${ccn ? `<span>CCN ${esc(ccn)}</span>` : ''}${rating != null ? `<span>CMS rating ${stars(rating)}</span>` : ''}</div>
          </div>
          <div>${yearTag()}</div>
        </div>
        ${pacBenes || pacPay || pacStays ? `<dl class="kv" style="margin-top:14px"><dt>Medicare patients served (${esc(META.pac_year || 'latest')})</dt><dd>${fmt(pacBenes)}</dd><dt>Medicare payments</dt><dd>${money(pacPay)}</dd><dt>Stays / episodes</dt><dd>${fmt(pacStays)}</dd></dl>` : ''}
      </div>
      <div class="grid cols-4">
        ${stat(fmt(outTotal), 'Patients sent onward')}${stat(fmt(outPartners), 'Destinations')}${stat(fmt(inTotal), 'Patients received')}${stat(fmt(inPartners), 'Sources')}
      </div>
      <div class="card" style="margin-top:18px">
        <div class="tabs">
          <button class="tab ${dir === 'out' ? 'active' : ''}" data-dir="out">Where patients go (${fmt(rec.out.length)})</button>
          <button class="tab ${dir === 'in' ? 'active' : ''}" data-dir="in">Where patients come from (${fmt(rec.in.length)})</button>
        </div>
        <div id="flowPanel"></div>
      </div>`;
    const panel = document.getElementById('flowPanel');
    const drawPanel = (d) => {
      const list = d === 'out' ? rec.out : rec.in;
      const total = d === 'out' ? outTotal : inTotal;
      const rows = list.map((r, i) => ({ rank: i + 1, npi: r[0], type: r[1], name: r[2], city: r[3], state: r[4], specialty: r[5], patients: r[6], share: r[7] }));
      const byType = {};
      rows.forEach((r) => { byType[r.type] = (byType[r.type] || 0) + r.patients; });
      const listed = rows.reduce((s, r) => s + r.patients, 0);
      const types = Object.keys(byType).sort((a, b) => byType[b] - byType[a]);
      const typeFilter = q.type && byType[q.type] ? q.type : '';
      const maxShare = rows.length ? rows[0].share : 100;
      panel.innerHTML = `
        <p class="muted" style="margin:0 0 12px">${d === 'out'
          ? `Providers that treated this ${isDoctor ? "doctor's" : "facility's"} Medicare patients within ${META.window_days} days afterwards. Share = percent of all ${fmt(total)} patients sent onward.`
          : `Providers whose Medicare patients came to ${esc(name)} within ${META.window_days} days. Share = percent of all ${fmt(total)} patients received.`}
          ${rows.length >= META.top ? ` Showing the top ${META.top} relationships overall plus the top ${META.top_per_type || 50} of each type.` : ''}</p>
        ${types.length ? `<h3>By ${d === 'out' ? 'destination' : 'source'} type</h3><div class="share-list">${types.map((t) => `<div class="share-row"><div>${badge(t)}</div><div class="track"><span style="width:${(100 * byType[t] / Math.max(total, 1)).toFixed(1)}%;background:${TYPE_COLOR[t]}"></span></div><div class="n">${fmt(byType[t])} · ${pct(100 * byType[t] / Math.max(total, 1))}</div></div>`).join('')}
          ${total > listed ? `<div class="share-row"><div class="muted">Other (not listed)</div><div class="track"><span style="width:${(100 * (total - listed) / total).toFixed(1)}%;background:#c5ccd6"></span></div><div class="n">${fmt(total - listed)} · ${pct(100 * (total - listed) / total)}</div></div>` : ''}</div>` : ''}
        <div class="chips" style="margin-top:14px"><button class="chip ${!typeFilter ? 'active' : ''}" data-t="">All types</button>${types.map((t) => `<button class="chip ${typeFilter === t ? 'active' : ''}" data-t="${t}">${TYPE_PLURAL[t]}</button>`).join('')}</div>
        <div id="flowTable"></div>`;
      const cols = [
        { key: 'rank', label: '#', num: true, render: (r) => `<span class="rank">${r.rank}</span>` },
        { key: 'name', label: d === 'out' ? 'Destination' : 'Source', render: (r) => `${plink(r.npi, r.name)}<span class="sub">${esc(r.city)}, ${esc(r.state)}${r.specialty ? ' · ' + esc(r.specialty) : ''}</span>` },
        { key: 'type', label: 'Type', render: (r) => badge(r.type) },
        { key: 'patients', label: 'Patients', num: true, render: (r) => fmt(r.patients) },
        { key: 'share', label: 'Share', num: true, render: (r) => `${pct(r.share)}${bar(r.share, maxShare)}` },
      ];
      const apply = (t) => (t ? rows.filter((r) => r.type === t) : rows);
      const tbl = renderTable(document.getElementById('flowTable'), {
        cols, rows: apply(typeFilter), sort: 'patients', pageSize: 100, empty: 'No relationships of this type.',
        csv: { name: `${name.replace(/[^\w]+/g, '_')}_${d}_${META.year}.csv`, header: ['rank', 'npi', 'type', 'name', 'city', 'state', 'specialty', 'patients', 'share_pct'], row: (r) => [r.rank, r.npi, TYPE_LABEL[r.type], r.name, r.city, r.state, r.specialty, r.patients, r.share] },
      });
      panel.querySelectorAll('.chip').forEach((ch) => ch.addEventListener('click', () => {
        panel.querySelectorAll('.chip').forEach((x) => x.classList.toggle('active', x === ch));
        q.type = ch.dataset.t; history.replaceState(null, '', `#/p/${npi}${qs({ dir: d, type: q.type })}`); tbl.redraw(apply(ch.dataset.t));
      }));
    };
    drawPanel(dir);
    app.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => {
      app.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b));
      q.type = ''; history.replaceState(null, '', `#/p/${npi}${qs({ dir: b.dataset.dir })}`); drawPanel(b.dataset.dir);
    }));
  }

  // ---- Flows table -----------------------------------------------------
  async function viewFlows(q) {
    setTitle('Flows');
    const states = META.states || [];
    const st = (q.state || (states[0] || {}).st || '').toUpperCase();
    const allTypes = ['H', 'R', 'L', 'S', 'A', 'C', 'D'];
    app.innerHTML = `<div class="page-head"><h1>Referral flows</h1><p>Every source → destination pair with at least ${META.min_patients} shared Medicare patients, by the source's state. Doctor → doctor pairs are listed from ${META.dd_min} patients. ${yearTag()}</p></div>
      <div class="card">${filtersBar([
        { id: 'state', label: 'Source state', type: 'select', options: states.map((s) => [s.st, s.name]), value: st },
        { id: 'src', label: 'Source type', type: 'select', options: typeOptions(allTypes, 'All source types'), value: q.src },
        { id: 'dst', label: 'Destination type', type: 'select', options: typeOptions(allTypes, 'All destination types'), value: q.dst },
        { id: 'min', label: 'Minimum patients', type: 'number', value: q.min || META.min_patients, min: 1 },
        { id: 'q', label: 'Name or city contains', placeholder: 'source or destination', value: q.q },
      ])}<div id="tbl"><div class="loading">Loading flows…</div></div></div>`;
    const cols = [
      { key: 'src_name', label: 'Source', render: (r) => `${plink(r.src_npi, r.src_name)}<span class="sub">${badge(r.src_type)} ${esc(r.src_city)}</span>` },
      { key: 'dst_name', label: 'Destination', render: (r) => `${plink(r.dst_npi, r.dst_name)}<span class="sub">${badge(r.dst_type)} ${esc(r.dst_city)}, ${esc(r.dst_state)}</span>` },
      { key: 'patients', label: 'Patients', num: true, render: (r) => fmt(r.patients) },
      { key: 'share', label: "Share of source's patients", num: true, render: (r) => `${pct(r.share)}${bar(r.share, 50)}` },
    ];
    let rows = [];
    let tbl = null;
    const apply = () => {
      const f = readFilters(app); const t = tokens(f.q); const min = Number(f.min) || 0;
      return rows.filter((r) => (!f.src || r.src_type === f.src) && (!f.dst || r.dst_type === f.dst) && r.patients >= min && (!t.length || matches(r.src_name + ' ' + r.src_city + ' ' + r.dst_name + ' ' + r.dst_city, t)));
    };
    const load = async () => {
      const f = readFilters(app);
      document.getElementById('tbl').innerHTML = '<div class="loading">Loading flows…</div>';
      const data = await loadFlows(f.state);
      rows = data.rows.map((r) => ({ src_npi: r[0], src_type: r[1], src_name: r[2], src_city: r[3], dst_npi: r[4], dst_type: r[5], dst_name: r[6], dst_city: r[7], dst_state: r[8], patients: r[9], share: r[10] }));
      tbl = renderTable(document.getElementById('tbl'), {
        cols, rows: apply(), sort: 'patients', pageSize: 100, empty: 'No flows match these filters.',
        csv: { name: `flows_${f.state}_${META.year}.csv`, header: ['source_npi', 'source_type', 'source_name', 'source_city', 'dest_npi', 'dest_type', 'dest_name', 'dest_city', 'dest_state', 'patients', 'share_pct'], row: (r) => [r.src_npi, TYPE_LABEL[r.src_type], r.src_name, r.src_city, r.dst_npi, TYPE_LABEL[r.dst_type], r.dst_name, r.dst_city, r.dst_state, r.patients, r.share] },
      });
    };
    await load();
    app.querySelectorAll('[data-f]').forEach((el) => el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', () => {
      const f = readFilters(app);
      history.replaceState(null, '', '#/flows' + qs({ state: f.state, src: f.src, dst: f.dst, min: f.min !== String(META.min_patients) ? f.min : '', q: f.q }));
      if (el.dataset.f === 'state') load(); else if (tbl) tbl.redraw(apply());
    }));
  }

  // ---- Trending --------------------------------------------------------
  async function viewTrending(q) {
    setTitle('Trending');
    app.innerHTML = '<div class="loading">Loading national lists…</div>';
    const t = await fetchData('trending.json');
    const tabs = [['referrers', 'Biggest referrers'], ['receivers', 'Biggest receivers'], ['pairs', 'Biggest relationships']];
    if (t.growth && t.growth.length) tabs.push(['growth', 'Fastest growing']);
    if (t.new && t.new.length) tabs.push(['new', 'New relationships']);
    let tab = tabs.some((x) => x[0] === q.tab) ? q.tab : 'referrers';
    app.innerHTML = `<div class="page-head"><h1>Trending nationally</h1><p>Top ${fmt((t.referrers.H || []).length)} lists across the whole dataset. ${yearTag()}${META.prior_year ? ` <span class="year-tag">Growth vs ${esc(META.prior_year)}</span>` : ''}</p></div>
      <div class="card"><div class="tabs">${tabs.map(([k, l]) => `<button class="tab ${k === tab ? 'active' : ''}" data-tab="${k}">${l}</button>`).join('')}</div><div id="panel"></div></div>`;
    const panel = document.getElementById('panel');
    const card = (c) => `${plink(c.npi, c.name)}<span class="sub">${badge(c.type)} ${esc(c.city)}, ${esc(c.state)}${c.specialty ? ' · ' + esc(c.specialty) : ''}</span>`;
    const pairRow = (p, right) => `<div class="pair"><div>${card(p.src)}</div><div class="arrow">→</div><div>${card(p.dst)}</div><div class="n">${right}</div></div>`;
    const draw = () => {
      if (tab === 'referrers' || tab === 'receivers') {
        const lists = t[tab]; const types = Object.keys(lists).filter((k) => lists[k].length);
        const sel = types.includes(q.type) ? q.type : types[0];
        panel.innerHTML = `<div class="chips">${types.map((k) => `<button class="chip ${k === sel ? 'active' : ''}" data-t="${k}">${TYPE_PLURAL[k]}</button>`).join('')}</div>
          <p class="muted">${tab === 'referrers' ? 'Ranked by total Medicare patients sent onward to any other provider.' : 'Ranked by total Medicare patients received from any other provider.'}</p><div id="list"></div>`;
        const rows = lists[sel].map((c, i) => ({ rank: i + 1, ...c }));
        renderTable(document.getElementById('list'), {
          cols: [{ key: 'rank', label: '#', num: true }, { key: 'name', label: TYPE_LABEL[sel], render: card }, { key: 'value', label: tab === 'referrers' ? 'Patients sent' : 'Patients received', num: true, render: (r) => `${fmt(r.value)}${bar(r.value, rows[0].value)}` }, { key: 'partners', label: tab === 'referrers' ? 'Destinations' : 'Sources', num: true, render: (r) => fmt(r.partners) }],
          rows, sort: 'value', pageSize: 100,
        });
        panel.querySelectorAll('.chip').forEach((ch) => ch.addEventListener('click', () => { q.type = ch.dataset.t; history.replaceState(null, '', '#/trending' + qs({ tab, type: q.type })); draw(); }));
      } else if (tab === 'pairs') {
        const keys = Object.keys(t.pairs).sort((a, b) => a.localeCompare(b));
        const sel = keys.includes(q.pair) ? q.pair : (keys.includes('H>S') ? 'H>S' : keys[0]);
        const label = (k) => k.split('>').map((x) => TYPE_LABEL[x]).join(' → ');
        panel.innerHTML = `<div class="filters"><label>Relationship type<select data-f="pair">${keys.map((k) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${label(k)}</option>`).join('')}</select></label></div>
          <p class="muted">The largest single source → destination relationships of this type, by shared Medicare patients. Share is the percent of all patients the source sent onward.</p>
          ${(t.pairs[sel] || []).map((p, i) => pairRow(p, `${fmt(p.patients)}<span class="sub">${pct(p.share)} of source · #${i + 1}</span>`)).join('')}`;
        panel.querySelector('[data-f]').addEventListener('change', (e) => { q.pair = e.target.value; history.replaceState(null, '', '#/trending' + qs({ tab, pair: q.pair })); draw(); });
      } else if (tab === 'growth') {
        panel.innerHTML = `<p class="muted">Relationships involving at least one facility that grew the most from ${esc(META.prior_year)} to ${esc(META.year)} (minimum ${META.growth_min || 30} patients in ${esc(META.year)}).${META.prior_note ? ' ' + esc(META.prior_note) : ''}</p>
          ${t.growth.map((p) => pairRow(p, `${fmt(p.patients)}<span class="sub"><span class="up">▲ ${fmt(p.change)}</span> (+${pct(p.pct)}) from ${fmt(p.prior)}</span>`)).join('')}`;
      } else if (tab === 'new') {
        panel.innerHTML = `<p class="muted">Largest relationships in ${esc(META.year)} that did not exist (fewer than ${META.min_patients} shared patients) in ${esc(META.prior_year)}.</p>
          ${t.new.map((p) => pairRow(p, `${fmt(p.patients)}<span class="sub">new in ${esc(META.year)}</span>`)).join('')}`;
      }
    };
    draw();
    app.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => { tab = b.dataset.tab; app.querySelectorAll('.tab').forEach((x) => x.classList.toggle('active', x === b)); history.replaceState(null, '', '#/trending' + qs({ tab })); draw(); }));
  }

  // ---- About -----------------------------------------------------------
  function viewAbout() {
    setTitle('About');
    const c = META.counts || {};
    app.innerHTML = `<div class="page-head"><h1>About this directory</h1><p>Sources, dates, methods and limitations. ${yearTag()}</p></div>
      <div class="card about">
        <h2>What the numbers mean</h2>
        <p>A <b>patient</b> here is one Medicare fee-for-service beneficiary who had a claim from the source provider and then a claim from the destination provider within <b>${META.window_days} days</b> in <b>${esc(META.year)}</b>. CMS counts each beneficiary once per pair and suppresses pairs with fewer than 11 beneficiaries. This is a <i>shared-patient</i> measure: it is the best public proxy for referrals and discharges, but it does not prove that one provider referred the patient to the other.</p>
        <p><b>Share</b> is the pair's patients divided by all patients the source sent onward (or, on a "where patients come from" view, all patients the destination received). <b>Rank</b> orders a provider's relationships by patients.</p>
        <h2>Data sources</h2>
        <ul>
          <li><b>Patient-sharing pairs:</b> ${esc(META.flows_label)}. Original source: CMS Physician Shared Patient Patterns (released under FOIA), mirrored by the National Bureau of Economic Research at data.nber.org. Pairs below ${META.min_patients} patients were dropped.</li>
          <li><b>Hospitals, nursing homes, home health agencies and hospices:</b> CMS Provider Enrollment files (Hospital, SNF, Home Health Agency and Hospice Enrollments) from data.cms.gov, including the "Additional NPIs" files so that a facility's secondary NPIs are folded into its main record.</li>
          <li><b>Doctors and specialties:</b> NPPES NPI Registry monthly dissemination file (download.cms.gov/nppes). Individual clinicians (entity type 1) with a physician taxonomy, plus nurse practitioners, physician assistants and podiatrists, who appear in the pair data.</li>
          <li><b>Volume context:</b> CMS Medicare Post-Acute Care &amp; Hospice by Provider and Service${META.pac_year ? ` (${esc(META.pac_year)})` : ''}: distinct Medicare patients served, payments and stays per facility.</li>
          <li><b>Star ratings:</b> CMS Care Compare provider files (Hospital General Information, Nursing Home Provider Information, Home Health Agencies, Hospice General Information).</li>
        </ul>
        <h2>Dates</h2>
        <ul>
          <li>Pair data year: <b>${esc(META.year)}</b>${META.prior_year ? ` (growth compared with ${esc(META.prior_year)})` : ''}.${META.prior_note ? ' ' + esc(META.prior_note) : ''} CMS's newest public release of the Physician Shared Patient Patterns is 2015; the 2015 file covers claims from January through about September 2015.</li>
          <li>Provider names, addresses and ratings: current enrollment and Care Compare files at build time.</li>
          <li>Site data built: <b>${esc(META.built)}</b>.</li>
        </ul>
        <h2>Coverage</h2>
        <p>${fmt((c.H || 0) + (c.R || 0) + (c.L || 0))} hospitals, ${fmt(c.S)} nursing homes, ${fmt(c.A)} home health agencies, ${fmt(c.C)} hospices and ${fmt(c.D)} doctors, connected by ${fmt(META.pairs_kept)} relationships (from ${fmt(META.pairs_total)} pairs in the source file). Provider pages list up to ${META.top} relationships in each direction.</p>
        <h2>Limitations</h2>
        <ul>
          <li>Medicare fee-for-service only. Medicare Advantage, Medicaid and commercial patients are not included, so facilities in markets with heavy Medicare Advantage enrollment look smaller than they are.</li>
          <li>The public pair data is from ${esc(META.year)}. Provider names and addresses are current, so a facility that opened or changed ownership after ${esc(META.year)} may show few or no relationships.</li>
          <li>A shared patient is not necessarily a referral. Two providers can share patients because they are in the same building or because the patient chose both.</li>
          <li>Hospitals and large groups bill under several NPIs. Known additional NPIs are merged; unknown ones appear as separate providers.</li>
          <li>Pairs with fewer than 11 beneficiaries are suppressed by CMS, so small relationships are invisible and shares are computed over visible pairs only.</li>
        </ul>
        <h2>Data model</h2>
        <p>The site is static. <code>build.py</code> writes two logical tables as compressed JSON: <code>providers(npi, ccn, name, type, address, city, state, zip, specialty)</code> and <code>flows(source_npi, dest_npi, year, patients, share)</code>. A newer licensed claims feed (Trella Health, Definitive Healthcare, CareSet, a CMS VRDC extract) can replace the public pair file with <code>build.py --flows-file feed.csv --year 2025 --flows-label "..."</code> without changing the site.</p>
        ${META.demo ? '<div class="banner"><b>Demo data.</b> This copy of the site was built with <code>build.py --demo</code>. Every provider, number and name is synthetic. Run <code>python build.py</code> to download the real public data.</div>' : ''}
      </div>`;
  }

  // ---------------------------------------------------------------- router
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, '');
    const [path, query] = h.split('?');
    const parts = path.split('/').filter(Boolean);
    const q = {}; new URLSearchParams(query || '').forEach((v, k) => { q[k] = v; });
    return { parts, q };
  }

  async function route() {
    const { parts, q } = parseHash();
    const page = parts[0] || 'home';
    document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active', a.dataset.nav === page || (page === 'p' && false)));
    document.getElementById('siteNav').classList.remove('open');
    window.scrollTo(0, 0);
    try {
      switch (page) {
        case 'home': viewHome(); break;
        case 'search': await viewSearch(q); break;
        case 'hospitals': await viewHospitals((parts[1] || '').toUpperCase(), q); break;
        case 'doctors': await viewDoctors((parts[1] || '').toUpperCase(), q); break;
        case 'facilities': await viewFacilities((parts[1] || '').toUpperCase(), q); break;
        case 'p': await viewProvider(parts[1], q); break;
        case 'flows': await viewFlows(q); break;
        case 'trending': await viewTrending(q); break;
        case 'about': viewAbout(); break;
        default: app.innerHTML = '<div class="card"><h1>Page not found</h1><a class="btn" href="#/">Go home</a></div>';
      }
    } catch (err) {
      console.error(err);
      app.innerHTML = `<div class="error"><b>Could not load this page.</b> ${esc(err.message)}<br><small>If you opened index.html directly from disk, serve the folder instead: <code>python -m http.server</code></small></div>`;
    }
  }

  async function init() {
    document.getElementById('navToggle').addEventListener('click', (e) => {
      const nav = document.getElementById('siteNav'); nav.classList.toggle('open'); e.currentTarget.setAttribute('aria-expanded', nav.classList.contains('open'));
    });
    document.getElementById('headerSearch').addEventListener('submit', (e) => {
      e.preventDefault(); const q = e.target.q.value.trim(); if (q) { location.hash = '#/search' + qs({ q }); e.target.q.value = ''; }
    });
    try {
      META = await loadMeta();
    } catch (err) {
      app.innerHTML = `<div class="error"><b>No data found.</b> Run <code>python build.py --demo</code> (or a full build) to create the <code>data/</code> folder, then serve this directory with a web server. (${esc(err.message)})</div>`;
      return;
    }
    META.states = (META.states || []).slice().sort((a, b) => a.name.localeCompare(b.name));
    document.getElementById('footerData').textContent = `Referral data: ${META.flows_label}. Built ${META.built}.`;
    if (META.demo) document.getElementById('banner').innerHTML = '<div class="banner"><b>Demo data.</b> Every name and number on this copy of the site is synthetic. Run <code>python build.py</code> to build it from real CMS data.</div>';
    window.addEventListener('hashchange', route);
    route();
  }
  init();
})();
