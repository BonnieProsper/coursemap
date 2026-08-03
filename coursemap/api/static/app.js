'use strict';
const API = '/api';
let currentPlan = null;
let lastPlanId = null;
let fillerCodes = new Set();
let sharedCodes = new Set();
let allMajors = [];
let modalCache = null;
let modalLevel = '';
let modalSubject = '';
let _modalSem = null;
let qualFilter = '';

// ── Theme ─────────────────────────────────────────────────────────────────────

const MOON_SVG = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const SUN_SVG  = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

function _applyTheme(theme, animate) {
  if (animate) document.body.classList.add('theme-ready');
  if (theme === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
  const btn = document.getElementById('theme-btn');
  if (btn) {
    const icon = document.getElementById('theme-icon');
    const label = document.getElementById('theme-label');
    if (theme === 'light') {
      icon.outerHTML = MOON_SVG.replace('<svg', '<svg id="theme-icon"');
      label.textContent = 'Dark';
    } else {
      icon.outerHTML = SUN_SVG.replace('<svg', '<svg id="theme-icon"');
      label.textContent = 'Light';
    }
  }
}

function initTheme() {
  // Priority: localStorage > prefers-color-scheme > dark
  const saved = localStorage.getItem('cm-theme');
  const preferLight = window.matchMedia('(prefers-color-scheme: light)').matches;
  const theme = saved || (preferLight ? 'light' : 'dark');
  _applyTheme(theme, false);
  // Listen for OS-level theme changes (only if user hasn't explicitly chosen)
  window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', e => {
    if (!localStorage.getItem('cm-theme')) {
      _applyTheme(e.matches ? 'light' : 'dark', true);
    }
  });
}

function toggleHelp() {
  const m = document.getElementById('help-modal');
  m.classList.toggle('open');
}

function toggleTheme() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const next = isLight ? 'dark' : 'light';
  localStorage.setItem('cm-theme', next);
  _applyTheme(next, true);
}

// ── Minors ───────────────────────────────────────────────────────────────────

let allMinors = [];
let selectedMinor = null;

async function loadMinors() {
  try {
    const res = await fetch(`${API}/minors`).then(r => r.json());
    allMinors = res.minors || [];
  } catch(e) { allMinors = []; }
}

function showMinorList() {
  filterMinors(document.getElementById('minor-input').value);
}

function filterMinors(q) {
  const box = document.getElementById('suggestions-minor');
  const matches = allMinors.filter(m => !q || m.name.toLowerCase().includes(q.toLowerCase()));
  if (!matches.length) { box.classList.remove('open'); return; }
  box.innerHTML = matches.map(m => {
    const safeN = m.name.replace(/'/g, "\\'");
    return `<div class="sug-item" onclick="selectMinor('${safeN}')">
      <div class="sug-name">${esc(m.name)}</div>
      <div class="sug-qual">Minor · 120cr</div>
    </div>`;
  }).join('');
  box.classList.add('open');
}

function selectMinor(name) {
  selectedMinor = allMinors.find(m => m.name === name);
  if (!selectedMinor) return;
  document.getElementById('minor-input').value = '';
  document.getElementById('suggestions-minor').classList.remove('open');
  document.getElementById('minor-selected').style.display = 'block';
  document.getElementById('minor-name').textContent = selectedMinor.name + ' Minor';
  // Add minor's required courses as preferred electives
  const preferred = extractMinorCodes(selectedMinor);
  preferred.forEach(code => addTag('prefer-wrap', code));
  toast(`${selectedMinor.name} Minor added: ${preferred.length} course codes added to preferred electives.`);
}

function clearMinor() {
  selectedMinor = null;
  document.getElementById('minor-selected').style.display = 'none';
  document.getElementById('minor-input').value = '';
}

function extractMinorCodes(minor) {
  const codes = [];
  function walk(node) {
    if (!node) return;
    if (node.type === 'COURSE') { codes.push(node.course_code); return; }
    if (node.course_codes) codes.push(...node.course_codes.slice(0, 4));
    (node.children || []).forEach(walk);
  }
  walk(minor.requirement);
  return [...new Set(codes)];
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  initTheme();  // Apply saved/system theme immediately, no flash
  try {
    const fr = await fetch(`${API}/`, {signal: AbortSignal.timeout(5000)}).then(r => r.json());
    const badge = document.getElementById('freshness-badge');
    const text = document.getElementById('freshness-text');
    if (fr.dataset) {
      text.textContent = `data: ${fr.dataset.scrape_date}`;
      badge.style.opacity = '1';
      if (fr.dataset.is_stale) badge.classList.add('stale');
    } else {
      text.textContent = 'data loaded';
      badge.style.opacity = '0.7';
    }
  } catch(e) {
    document.getElementById('freshness-text').textContent = 'server offline';
    document.getElementById('freshness-badge').style.color = 'var(--red)';
    // Show a visible error in the main panel
    const main = document.getElementById('plan-area') || document.querySelector('.plan-area') || document.body;
    const errDiv = document.createElement('div');
    errDiv.style.cssText = 'margin:60px auto;max-width:480px;padding:24px;background:var(--red-lt,#fef2f2);border:1px solid rgba(239,68,68,0.3);border-radius:12px;text-align:center;';
    errDiv.innerHTML = `
      <div style="font-size:32px;margin-bottom:12px">⚠️</div>
      <h3 style="margin:0 0 8px;color:var(--ink1)">Server not running</h3>
      <p style="margin:0 0 16px;color:var(--ink2);font-size:14px">
        CourseMap needs the Python server to be running.<br>
        Open a terminal, go to the <code>coursemap</code> folder, and run:
      </p>
      <code style="display:block;background:var(--bg3);padding:10px 14px;border-radius:6px;font-size:13px;text-align:left">
        python -m uvicorn coursemap.api.server:app --reload --port 8000
      </code>
      <p style="margin:12px 0 0;color:var(--ink3);font-size:12px">Then refresh this page.</p>
    `;
    const mainEl = document.getElementById('main'); if(mainEl) mainEl.prepend(errDiv); else document.body.append(errDiv);
    return; // stop init if server is offline
  }

  try {
    const mRes = await fetch(`${API}/majors?limit=500`).then(r => r.json());
    allMajors = mRes.majors || [];
    buildQualPills();
  } catch(e) {}

  // Pull the canonical fee-rate table from the backend so this UI's fee
  // estimates can never silently drift from /api/plan/fees again (see
  // loadFeeConstants() for the bug this replaced). Falls back to the
  // bundled table below if the server is briefly unreachable.
  await loadFeeConstants();

  // Auto-detect current year + semester
  const now = new Date();
  const yr = now.getFullYear();
  const mo = now.getMonth() + 1;
  const p = new URLSearchParams(location.search);
  if (!p.get('year')) document.getElementById('start-year').value = yr;
  if (!p.get('sem')) {
    const sem = (mo>=2&&mo<=6)?'S1':(mo>=7&&mo<=11)?'S2':'SS';
    document.getElementById('start-sem').value = sem;
  }

  loadMinors();
  setupAutocomplete('major-input','suggestions');
  setupAutocomplete('double-input','suggestions-dm');
  setupTagInput('completed-input','completed-wrap');
  setupTagInput('prefer-input','prefer-wrap');
  setupTagInput('exclude-input','exclude-wrap');
  restoreFromUrl();
  renderSavedPlans();
  initStudentType();
}

// ── Qual filter pills ─────────────────────────────────────────────────────────

function buildQualPills() {
  const container = document.getElementById('qual-pills');
  const buckets = [
    { label:'Bachelor', match: q => q.startsWith('Bachelor') && !q.includes('Honours') },
    { label:'Honours',  match: q => q.includes('Honours') },
    { label:'Postgrad', match: q => q.startsWith('Postgraduate')||q.startsWith('Graduate') },
    { label:'Master',   match: q => q.startsWith('Master') },
    { label:'Diploma',  match: q => q.startsWith('Diploma') },
  ];
  const quals = allMajors.map(m => m.qualification_type||'').filter(Boolean);
  buckets.filter(b => quals.some(q => b.match(q))).forEach(b => {
    const pill = document.createElement('span');
    pill.className = 'qpill';
    pill.dataset.qual = b.label;
    pill.textContent = b.label;
    pill.onclick = () => setQualFilter(pill, b.label);
    container.appendChild(pill);
  });
}

function setQualFilter(el, val) {
  document.querySelectorAll('.qpill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  qualFilter = val;
}

// ── Autocomplete ──────────────────────────────────────────────────────────────

function setupAutocomplete(inputId, boxId) {
  const inp = document.getElementById(inputId);
  const box = document.getElementById(boxId);
  let idx = -1;
  let debounceTimer = null;

  function show(q) {
    const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const matches = allMajors.filter(m => {
      const name = (m.name||m).toLowerCase().replace(/[–-]/g,' ');
      const toks = name.split(/\s+/);
      const wordOk = !words.length || words.every(w => toks.some(t => t.includes(w)));
      const qt = m.qualification_type||'';
      const qualOk = !qualFilter || (() => {
        if (qualFilter==='Bachelor') return qt.startsWith('Bachelor')&&!qt.includes('Honours');
        if (qualFilter==='Honours')  return qt.includes('Honours');
        if (qualFilter==='Postgrad') return qt.startsWith('Postgraduate')||qt.startsWith('Graduate');
        if (qualFilter==='Master')   return qt.startsWith('Master');
        if (qualFilter==='Diploma')  return qt.startsWith('Diploma');
        return qt.includes(qualFilter);
      })();
      return wordOk && qualOk;
    }).slice(0,14);

    if (!matches.length) { box.classList.remove('open'); return; }

    box.innerHTML = matches.map(m => {
      const name = m.name||m;
      const major = name.split(/\s*[–-]\s*/)[0].trim();
      const qual  = m.qualification_type||'';
      const safe  = name.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      return `<div class="sug-item" data-val="${escAttr(name)}" onclick="pickSug('${inputId}','${boxId}','${safe}')">
        <div class="sug-name">${esc(major)}</div>
        ${qual ? `<div class="sug-qual">${esc(qual)}</div>` : ''}
      </div>`;
    }).join('');
    box.classList.add('open');
    idx = -1;
  }

  inp.addEventListener('focus', async () => {
    if (!allMajors.length) {
      // Retry loading majors if init() failed
      try {
        const mRes = await fetch(`${API}/majors?limit=500`).then(r=>r.json());
        allMajors = mRes.majors || [];
        buildQualPills();
      } catch(e) {}
    }
    if (allMajors.length) show(inp.value);
  });
  inp.addEventListener('input', () => {
    // Debounce: wait 120ms after last keystroke before filtering
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => show(inp.value), 120);
  });
  inp.addEventListener('keydown', e => {
    const items = box.querySelectorAll('.sug-item');
    if (e.key==='ArrowDown') { idx=Math.min(idx+1,items.length-1); hlSug(items,idx); e.preventDefault(); }
    else if (e.key==='ArrowUp') { idx=Math.max(idx-1,0); hlSug(items,idx); e.preventDefault(); }
    else if (e.key==='Enter'&&idx>=0) { items[idx].click(); e.preventDefault(); }
    else if (e.key==='Escape') box.classList.remove('open');
  });
  document.addEventListener('click', e => {
    if (!inp.contains(e.target)&&!box.contains(e.target)) box.classList.remove('open');
  });
  // Also close minor dropdown on outside click
  document.addEventListener('click', e => {
    const minorInp = document.getElementById('minor-input');
    const minorBox = document.getElementById('suggestions-minor');
    if (minorInp && minorBox && !minorInp.contains(e.target) && !minorBox.contains(e.target)) {
      minorBox.classList.remove('open');
    }
  }, {once: false});
}

function hlSug(items, i) {
  items.forEach((el,j) => el.classList.toggle('active', j===i));
  if (items[i]) items[i].scrollIntoView({block:'nearest'});
}

function pickSug(inputId, boxId, val) {
  document.getElementById(inputId).value = val;
  document.getElementById(boxId).classList.remove('open');
}

// ── Tag inputs ────────────────────────────────────────────────────────────────

function setupTagInput(inputId, wrapId) {
  const inp = document.getElementById(inputId);
  inp.addEventListener('keydown', e => {
    if (['Enter','Tab',','].includes(e.key) && inp.value.trim()) {
      e.preventDefault();
      addTag(wrapId, inp.value.trim().toUpperCase().replace(/,/g,''));
      inp.value='';
    } else if (e.key==='Backspace' && !inp.value) {
      const tags = document.querySelectorAll(`#${wrapId} .tag`);
      if (tags.length) tags[tags.length-1].remove();
    }
  });
  document.getElementById(wrapId).addEventListener('click', () => inp.focus());
}

function addTag(wrapId, code) {
  if (!code || code.length < 4) return;
  const existing = [...document.querySelectorAll(`#${wrapId} .tag`)].map(t => t.dataset.code);
  if (existing.includes(code)) return;
  const tag = document.createElement('div');
  tag.className = 'tag'; tag.dataset.code = code;
  tag.innerHTML = `${esc(code)}<button onclick="this.parentElement.remove()" type="button">×</button>`;
  document.getElementById(wrapId).insertBefore(tag, document.querySelector(`#${wrapId} input`));
}

function getTags(wrapId) {
  return [...document.querySelectorAll(`#${wrapId} .tag`)].map(t => t.dataset.code);
}

// ── Quick picks ───────────────────────────────────────────────────────────────

function quickPick(name) {
  document.getElementById('major-input').value = name;
  // Open sidebar on mobile so user can see the field
  document.getElementById('sidebar')?.classList.add('open');
  generatePlan();
}

function openMajorBrowser() {
  document.getElementById('major-modal').classList.add('open');
  const q = document.getElementById('major-modal-q');
  if (q) { q.value = ''; q.focus(); }
  filterMajorModal('');
}

function closeMajorModal() {
  document.getElementById('major-modal').classList.remove('open');
}

let majorModalQualFilter = '';

function setMajorModalQual(el, val) {
  document.querySelectorAll('#major-modal-qual-pills .f-pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  majorModalQualFilter = val;
  filterMajorModal(document.getElementById('major-modal-q').value);
}

function filterMajorModal(q) {
  const results = document.getElementById('major-modal-results');
  if (!results) return;
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = allMajors.filter(m => {
    const name = (m.name || '').toLowerCase().replace(/[–-]/g, ' ');
    const wordOk = !words.length || words.every(w => name.includes(w));
    const qt = m.qualification_type || '';
    let qualOk = true;
    if (majorModalQualFilter === 'Bachelor') qualOk = qt.startsWith('Bachelor') && !qt.includes('Honours');
    else if (majorModalQualFilter === 'Honours') qualOk = qt.includes('Honours');
    else if (majorModalQualFilter === 'Master') qualOk = qt.startsWith('Master');
    else if (majorModalQualFilter === 'Postgrad') qualOk = qt.startsWith('Postgraduate') || qt.startsWith('Graduate');
    else if (majorModalQualFilter) qualOk = qt.includes(majorModalQualFilter);
    return wordOk && qualOk;
  });

  if (!matches.length) {
    results.innerHTML = '<div class="modal-empty">No majors found</div>';
    return;
  }

  results.innerHTML = matches.map(m => {
    const subject = (m.name || '').split(/\s*[–-]\s*/)[0].trim();
    const qual = m.qualification_type || '';
    const safe = escAttr(m.name || '');
    return `<div class="modal-row" onclick="selectMajorFromModal('${safe}')" style="cursor:pointer">
      <span class="modal-code" style="min-width:0;flex:1;font-weight:500;font-size:13px">${esc(subject)}</span>
      <span class="modal-title" style="color:var(--ink3);font-size:12px">${esc(qual)}</span>
      <span class="modal-cr" style="white-space:nowrap;font-size:11px;color:var(--green)">${m.credit_target ? m.credit_target+'cr' : ''}</span>
    </div>`;
  }).join('') + (matches.length >= 380 ? '' : `<div style="padding:8px 12px;font-size:11px;color:var(--ink3)">${matches.length} results</div>`);
}

function selectMajorFromModal(name) {
  document.getElementById('major-input').value = name;
  closeMajorModal();
  generatePlan();
}

// ── Generate ──────────────────────────────────────────────────────────────────

async function generatePlan() {
  const major = document.getElementById('major-input').value.trim();
  if (!major) {
    const inp = document.getElementById('major-input');
    inp.style.borderColor = 'var(--red)';
    inp.focus();
    setTimeout(() => inp.style.borderColor = '', 1800);
    toast('Please enter a major first.');
    return;
  }

  const btn = document.getElementById('btn-generate');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  showLoading();
  closeSidebar();

  const body = {
    major,
    double_major: document.getElementById('double-input').value.trim() || null,
    start_year:   parseInt(document.getElementById('start-year').value),
    start_semester: document.getElementById('start-sem').value,
    max_credits:  parseInt(document.getElementById('max-credits').value),
    max_per_semester: parseInt(document.getElementById('max-per-sem').value) || null,
    campus:       document.getElementById('campus').value,
    mode:         document.getElementById('mode').value,
    transfer_credits: parseInt(document.getElementById('transfer').value)||0,
    completed:    getTags('completed-wrap'),
    prefer:       getTags('prefer-wrap'),
    exclude:      getTags('exclude-wrap'),
    no_summer:    document.getElementById('no-summer').checked,
    auto_fill:    document.getElementById('auto-fill').checked,
  };

  const ICON = '<svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v11M1 6.5h11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg> Generate plan';

  function finishBtn() {
    btn.disabled = false;
    btn.innerHTML = ICON;
  }

  try {
    const res = await fetch(`${API}/plan/stream`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });

    if (!res.ok || !res.body) {
      const data = await res.json().catch(() => ({detail: 'Unknown error'}));
      showError(data.detail || 'Plan generation failed.');
      finishBtn();
      return;
    }

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let   buffer  = '';

    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(6)); } catch(e) { continue; }

        if (evt.type === 'progress') {
          updateGenProgress(evt.pct, evt.msg);
        } else if (evt.type === 'done') {
          const data = evt.plan;
          currentPlan = {request: body, response: data};
          fillerCodes = new Set(data.filler_codes||[]);
          sharedCodes = new Set();
          if (data.double_major_info?.shared_codes) {
            data.double_major_info.shared_codes.forEach(c => sharedCodes.add(c));
          }
          modalCache = null;
          renderPlan(data);
          pushUrl(body, data.plan_id);
          setExportButtons(true);
        } else if (evt.type === 'error') {
          let msg = evt.detail || 'Plan generation failed.';
          if (msg.includes('lack a') && msg.includes('offering')) {
            const m = msg.match(/Valid combinations[^:]*: ([^."]+)/);
            if (m) msg += `\n\nTry one of these campus/mode combos: ${m[1].trim()}`;
          }
          showError(msg);
        }
      }
    }
  } catch(e) {
    showError('Network error. Is the coursemap server running?');
  }

  finishBtn();
}

function updateGenProgress(pct, msg) {
  const fill  = document.getElementById('gen-progress-fill');
  const label = document.getElementById('gen-progress-label');
  if (fill)  fill.style.width  = pct + '%';
  if (label) label.textContent = msg || '';
}

function setExportButtons(enabled) {
  ['btn-json','btn-ical','btn-html','btn-share','btn-save'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !enabled;
  });
}

// ── Render ────────────────────────────────────────────────────────────────────

function showLoading() {
  const es = document.getElementById('empty-state');
  if (es) es.remove();
  document.getElementById('main').innerHTML = `
    <div class="loading-wrap">
      <div class="spinner"></div>
      <div class="gen-progress-wrap">
        <div class="gen-progress-label" id="gen-progress-label">Preparing…</div>
        <div class="gen-progress-track">
          <div class="gen-progress-fill" id="gen-progress-fill"></div>
        </div>
      </div>
    </div>`;
}

function showError(msg) {
  // Check for "Valid combinations: X/Y" pattern to offer quick-fix buttons
  const altMatch = msg.match(/Valid combinations for this major: ([^.]+)/);
  let altHtml = '';
  if (altMatch) {
    const alts = altMatch[1].trim().split(/[,\s]+/).filter(x => /^[A-Z]+\/[A-Z]+$/.test(x));
    if (alts.length) {
      altHtml = `<div class="error-alts">
        <div class="error-alts-label">Available via:</div>
        ${alts.map(a => {
          const [cam, mod] = a.split('/');
          return `<button class="btn-sm" onclick="quickSwitch('${cam}','${mod}')">${a}</button>`;
        }).join('')}
      </div>`;
    }
  }
  // A required course is SS-only while Summer School is disabled. Offer a
  // one-click fix to re-enable it rather than making the student dig through
  // the checkbox themselves.
  if (/Summer School is disabled \(--no-summer\)/.test(msg) && !altHtml) {
    altHtml = `<div class="error-alts">
      <div class="error-alts-label">Quick fix:</div>
      <button class="btn-sm" onclick="quickAllowSummer()">Allow Summer School</button>
    </div>`;
  }
  // A required course only exists at a different campus/mode than selected,
  // offer the same quick-switch buttons used for the whole-major case above,
  // built from each "only X/Y" fragment in the per-course explanations.
  if (!altHtml) {
    const comboMatches = [...msg.matchAll(/only ([A-Z]+\/[A-Z]+(?:,\s*[A-Z]+\/[A-Z]+)*)\s*\(try/g)];
    const combos = [...new Set(comboMatches.flatMap(m => m[1].split(/,\s*/)))];
    if (combos.length) {
      altHtml = `<div class="error-alts">
        <div class="error-alts-label">Available via:</div>
        ${combos.map(a => {
          const [cam, mod] = a.split('/');
          return `<button class="btn-sm" onclick="quickSwitch('${cam}','${mod}')">${a}</button>`;
        }).join('')}
      </div>`;
    }
  }
  document.getElementById('main').innerHTML = `
    <div class="error-state">
      <div class="error-icon">⚠</div>
      <div class="error-title">Could not generate plan</div>
      <div class="error-body">${esc(msg)}</div>
      ${altHtml}
    </div>`;
}

function quickAllowSummer() {
  document.getElementById('no-summer').checked = false;
  generatePlan();
}

function quickSwitch(campus, mode) {
  document.getElementById('campus').value = campus;
  document.getElementById('mode').value = mode;
  generatePlan();
}

function renderPlan(data) {
  lastPlanId = data.plan_id || null;
  const meta = data.meta;
  const sems = data.semesters;
  const maxCr = Math.max(...sems.map(s => s.credits), 60);
  const totalPlanned = (meta.credits_planned||0) + (meta.credits_prior||0) + (meta.credits_transfer||0);
  const gap     = meta.free_elective_gap || 0;    // residual (0 when auto-filled)
  const rawGap  = meta.raw_elective_gap  || 0;    // original major-data gap
  const isDouble = !!data.double_major_info;

  const main = document.getElementById('main');
  main.innerHTML = '';

  // ── Disclaimer
  const disc = document.createElement('div');
  disc.className = 'disclaimer';
  disc.innerHTML = `<span class="disc-icon">⚠</span><span>Unofficial tool, not affiliated with Massey University.
    Major requirements, prerequisites and fees are <strong>approximate</strong>. Always verify with
    <a href="https://www.massey.ac.nz/study/" target="_blank" rel="noopener noreferrer">official Massey programme info</a>
    and your academic advisor before enrolling.</span>`;
  main.appendChild(disc);

  // ── Header
  const hdr = document.createElement('div');
  hdr.className = 'plan-hdr';
  const degreeLabel = isDouble
    ? `${data.double_major_info.first_label} + ${data.double_major_info.second_label}`
    : meta.major;
  const startSem = meta.start_semester || 'S1';
  hdr.innerHTML = `
    <div class="plan-title">
      <h1>${esc(degreeLabel)}</h1>
      <div class="sub">${meta.start_year} ${startSem} · ${meta.campus}/${meta.mode}${meta.credits_transfer ? ' · ' + meta.credits_transfer + 'cr transferred' : ''}</div>
    </div>
    <div class="plan-actions">
      <button class="btn-sm" onclick="window.print()" title="Print or save as PDF">⎙ Print</button>
      <button class="btn-sm" onclick="downloadJson()">↓ JSON</button>
      <button class="btn-sm" onclick="downloadIcal()">↓ iCal</button>
      <button class="btn-sm" onclick="downloadHtml()">↓ HTML</button>
      <button class="btn-sm" onclick="downloadAdvisorSummary()" title="Plain-text summary for advisor">↓ Advisor</button>
      <button class="btn-sm" onclick="downloadMarkdown()" title="Markdown export for Notion/Obsidian">↓ MD</button>
      <button class="btn-sm" onclick="openCompareModal()">&#8644; Compare</button>
      <button class="btn-sm" onclick="openCourseModal()">Browse</button>
    </div>`;
  main.appendChild(hdr);

  // ── Progress indicator (when completed courses exist)
  const completedCodes = [...document.querySelectorAll('.completed-tag')].map(t => t.dataset.code).filter(Boolean);
  if (completedCodes.length > 0 && meta.credits_prior > 0) {
    const pct = Math.round(100 * meta.credits_total / meta.degree_target);
    const progressDiv = document.createElement('div');
    progressDiv.className = 'stat-card';
    progressDiv.style.cssText = 'margin:0 0 12px;padding:12px 16px';
    progressDiv.innerHTML = `
      <div class="progress-summary">
        <span>Degree progress</span>
        <strong>${meta.credits_total}cr of ${meta.degree_target}cr</strong>
        <span style="color:var(--green)">${pct}% complete</span>
        <span style="color:var(--text3)">${meta.credits_prior}cr already earned</span>
      </div>
      <div class="progress-bar-wrap">
        <div class="progress-bar-fill" style="width:${Math.min(pct,100)}%"></div>
      </div>`;
    main.appendChild(progressDiv);
  }

  // ── Warnings
  (data.warnings||[]).forEach(w => {
    const el = document.createElement('div');
    el.className = 'warn-banner' + (w.includes('full academic year') ? ' warn-full-year' : '');
    // Make prerequisite warnings link to the refresh guide
    const warnText = w.includes('prerequisite') 
      ? w + ' <a href="DATA_QUALITY.md" style="color:inherit;text-decoration:underline">Learn more ↗</a>'
      : w;
    el.innerHTML = `<span>⚠</span><span>${warnText}</span>`;
    main.appendChild(el);
  });

  // Long-degree advisory
  const years = new Set(sems.map(s => s.year)).size;
  const maxCredPerSem = parseInt(document.getElementById('max-credits')?.value || '60');
  const isPartTime = maxCredPerSem <= 30;
  if (years > (isPartTime ? 8 : 5)) {
    const el = document.createElement('div');
    el.className = 'warn-banner info';
    el.innerHTML = `<span>ℹ</span><span>This plan spans <strong>${years} years</strong>. Consider increasing credits/semester or checking for summer school options.</span>`;
    main.appendChild(el);
  }

  // First-use disclaimer modal
  if (!localStorage.getItem('cm-disclaimer-seen')) {
    showDisclaimerModal();
  }

  // ── Stats
  const sg = document.createElement('div');
  sg.className = 'stats-grid';
  const studentType = localStorage.getItem('cm-student-type') || 'domestic';
  const feeCalc = estimatePlanFees(sems, studentType);
  const estFees = feeCalc.total;
  const statsData = [
    { val: sems.length,          lbl: 'Semesters', cls: '' },
    { val: `${totalPlanned}cr`,  lbl: 'Credits planned', cls: 'green' },
    { val: `${meta.degree_target||360}cr`, lbl: 'Degree target', cls: '' },
    { val: gap > 0 ? `${gap}cr` : '-', lbl: 'Elective gap', cls: gap > 0 ? 'amber' : '' },
    { val: formatNZD(estFees),   lbl: `Est. total fees (${studentType})*`, cls: '' },
  ];
  if (isDouble) statsData.push({ val: `${data.double_major_info.saved_credits}cr`, lbl: 'Credits saved', cls: 'green' });
  statsData.forEach(s => {
    const c = document.createElement('div');
    c.className = `stat-card ${s.cls}`;
    c.innerHTML = `<div class="stat-val">${s.val}</div><div class="stat-lbl">${s.lbl}</div>`;
    sg.appendChild(c);
  });
  main.appendChild(sg);

  // Fetch the backend's own fee estimate for this plan, which - unlike the
  // client-side estimatePlanFees() above (kept for the instant stat-card
  // number) - also returns a plan-specific confidence signal (e.g. "72% of
  // courses in this plan have no subject-specific rate and used the flat
  // default instead") and the full list of excluded non-tuition costs.
  // That richer text was already being computed by estimate_plan_fees() on
  // every request but never actually shown anywhere in the UI - only a
  // generic, always-identical disclaimer was. Best-effort and
  // non-blocking: never delays the stat cards above, and silently does
  // nothing if the request fails.
  updateFeesConfidenceNote(data.plan_id, studentType);

  // ── Double major shared-courses banner
  if (isDouble && sharedCodes.size > 0) {
    const sb = document.createElement('div');
    sb.className = 'shared-banner';
    const codeList = [...sharedCodes].map(code => {
      const c = data.semesters.flatMap(s=>s.courses).find(c=>c.code===code);
      return `<span class="pnode-code" style="cursor:pointer" onclick="openDrawer('${code}')" title="${c?esc(c.title):''}">${code}</span>`;
    }).join('');
    sb.innerHTML = `
      <h4>Shared courses · ${data.double_major_info.saved_credits}cr saved</h4>
      <p>These courses count toward both majors, reducing the total time and credits needed.</p>
      <div class="shared-codes">${codeList}</div>`;
    main.appendChild(sb);
  }

  // ── Progress bar
  renderProgressBar(main, meta, totalPlanned);

  // ── Validation panel
  if (currentPlan) renderValidationPanel(main, currentPlan.request);

  // ── Gap banner
  if (gap > 0 && !meta.auto_filled_codes?.length) {  // unfilled gap
    const gb = document.createElement('div');
    gb.className = 'gap-banner';
    const gapMsg = meta.gap_explanation ||
      `Your major covers ${meta.degree_target - gap}cr of ${meta.degree_target}cr. ` +
      `You need to schedule ${gap}cr more. Enable Auto-fill or add a second major.`;
    gb.innerHTML = `
      <h4>Free elective gap &middot; ${gap}cr unscheduled</h4>
      <p>${esc(gapMsg)}</p>
      <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
        <button class="btn-sm"
          onclick="document.getElementById('auto-fill').checked=true;generatePlan()">
          &#10022; Auto-fill ${gap}cr
        </button>
        <button class="btn-sm"
          onclick="(function(){var el=document.getElementById('double-input');if(el){el.scrollIntoView({behavior:'smooth',block:'center'});setTimeout(function(){el.focus();},350);}})()">
          + Add second major
        </button>
      </div>`;
    main.appendChild(gb);
  }

  if (rawGap > 0 && meta.auto_filled_codes?.length) {  // gap was auto-filled
    const el = document.createElement('div');
    el.className = 'gap-banner';
    const allC = data.semesters.flatMap(s=>s.courses);
    const fillerInPlan = meta.auto_filled_codes.map(code => allC.find(c=>c.code===code)).filter(Boolean);
    el.innerHTML = `
      <h4>${rawGap}cr free elective gap · filled with ${fillerInPlan.length} suggested courses</h4>
      <p>These courses were selected automatically to complete your degree. 
         You can replace any of them by adding preferred course codes in the sidebar.</p>
      <div class="elective-list">${fillerInPlan.map(c => `
        <div class="elective-row">
          <span class="elective-code" style="cursor:pointer" onclick="openDrawer('${c.code}')">${c.code}</span>
          <span class="elective-cr">${c.credits}cr</span>
          <span class="elective-title">${esc(c.title)}</span>
          <span class="elective-sem">${c.offered_semesters?.join('/') || ''}</span>
        </div>`).join('')}
      </div>`;
    main.appendChild(el);
  }

  // ── Semesters
  const semsWrap = document.createElement('div');
  const calMap = {
    S1: { label:'Feb – Jun', enrol:'Enrol by late Jan', results:'Results mid Jul' },
    S2: { label:'Jul – Nov', enrol:'Enrol by late Jun', results:'Results mid Dec' },
    SS: { label:'Nov – Feb', enrol:'Enrol by early Nov', results:'Results late Feb' },
  };

  let prevYear = null;
  let yearWrap = null;
  sems.forEach((sem, si) => {
    if (sem.year !== prevYear) {
      const yearHdr = document.createElement('div');
      yearHdr.className = 'year-header';
      const yearCr = sems.filter(s=>s.year===sem.year).reduce((a,s)=>a+s.credits,0);
      const studentType = localStorage.getItem('cm-student-type') || 'domestic';
      const yearSems = sems.filter(s=>s.year===sem.year);
      const feeYr = estimatePlanFees(yearSems, studentType);
      const yearFees = feeYr.total;
      yearHdr.innerHTML = `
        <span class="year-label">${sem.year}</span>
        <span class="year-line"></span>
        <span class="year-cr">${yearCr}cr · ${formatNZD(yearFees)}</span>`;
      semsWrap.appendChild(yearHdr);
      prevYear = sem.year;
    }

    const block = document.createElement('div');
    block.className = 'sem-block';

    const pct = Math.round((sem.credits / maxCr) * 100);
    const cal = calMap[sem.semester] || {};
    const highLevelCr = sem.courses.filter(c=>c.level>=300).reduce((a,c)=>a+c.credits,0);

    let warnHtml = '';
    if (sem.credits > 60) {
      warnHtml = `<span class="sem-warn">⚠ Heavy: ${sem.credits}cr</span>`;
    } else if (si < 2 && highLevelCr >= 30) {
      warnHtml = `<span class="sem-warn">⚠ L3 in year 1</span>`;
    }

    const nowYear = new Date().getFullYear();
    const nowSem  = new Date().getMonth() < 6 ? 'S1' : 'S2';
    const isPast  = sem.year < nowYear || (sem.year === nowYear && sem.semester <= nowSem);
    const markBtn = isPast
      ? `<button class="mark-done-btn" onclick="event.stopPropagation();markDone(${JSON.stringify(sem.courses.map(c=>c.code))})">✓ Mark done</button>`
      : '';

    block.innerHTML = `
      <div class="sem-head" title="${esc(cal.enrol||'')} · ${esc(cal.results||'')}">
        <span class="sem-label">${sem.year} ${sem.semester}</span>
        <span class="sem-cal">${cal.label||''}</span>
        <span class="sem-cr">${sem.credits}cr</span>
        <div class="sem-bar"><div class="sem-bar-fill" style="width:${pct}%"></div></div>
        ${warnHtml}
        ${markBtn}
      </div>
      <div class="sem-courses" id="sem-${sem.year}-${sem.semester}"></div>`;

    const grid = block.querySelector('.sem-courses');
    sem.courses.forEach(c => {
      const isFiller = fillerCodes.has(c.code);
      const isShared = sharedCodes.has(c.code);
      const card = document.createElement('div');
      card.className = `course-card${isFiller?' filler':''}`;
      card.onclick = () => openDrawer(c.code);

      // Build set of codes scheduled BEFORE this semester for prereq check
      const priorToThisSem = new Set();
      sems.slice(0, si).forEach(ps => ps.courses.forEach(pc => priorToThisSem.add(pc.code)));
      (data.prior_completed || []).forEach(pc => priorToThisSem.add(pc.code || pc));

      const badge = isShared
        ? `<span class="shared-badge">×2</span>`
        : isFiller
          ? `<span class="filler-badge" title="Free elective, swap this for any course at the same level that interests you">elective ↔</span>`
          : '';
      const fullYearBadge = c.has_full_year_offering
        ? `<span class="full-year-badge" title="Full Year enrolment, must enrol for both S1 and S2 as a unit">FY</span>`
        : '';

      // Prereq satisfaction dot
      const prereqSat = getPrereqSatisfaction(c, priorToThisSem);
      const prereqDot = prereqSat === 'satisfied'
        ? `<span class="prereq-ok" title="Prerequisites met"></span>`
        : prereqSat === 'missing'
          ? `<span class="prereq-miss" title="Check prerequisites"></span>`
          : prereqSat === 'unverified'
            ? `<span class="prereq-unverified" title="No prerequisite data recorded for this course. This usually means the data wasn't captured, not that there isn't one. Check massey.ac.nz before enrolling."></span>`
            : '';

      const inferredBadge = c.offering_inferred
        ? `<span class="inferred-badge" title="Offering data not confirmed for 2026, verify availability at Massey">?</span>`
        : '';

      card.innerHTML = `
        ${badge}${fullYearBadge}
        <div class="course-code">${prereqDot}${c.code}${inferredBadge}</div>
        <div class="course-title">${esc(c.title)}</div>
        <div class="course-meta">
          <span class="course-level-badge">${c.level ? 'L'+c.level : ''}</span>
          <span>${c.credits}cr</span>
          ${c.offered_semesters?.length ? `<span>${c.offered_semesters.join('/')}</span>` : ''}
        </div>`;
      grid.appendChild(card);
    });

    semsWrap.appendChild(block);
  });
  main.appendChild(semsWrap);

  // ── Verification checklist ────────────────────────────────────────────────
  const chkDiv = document.createElement('div');
  chkDiv.style.cssText = 'margin:28px 0 4px;padding:16px 20px;background:var(--bg3);border:1px solid var(--border1);border-radius:10px;font-size:13px';
  chkDiv.innerHTML = `
    <div style="font-weight:600;margin-bottom:10px;color:var(--ink2)">Before enrolling: verify this plan</div>
    <ol style="margin:0;padding-left:18px;color:var(--ink2);line-height:2.1">
      <li>Check your <a href="https://www.massey.ac.nz/study/" target="_blank" rel="noopener" style="color:var(--green)">programme requirements</a> on Massey's website match this plan</li>
      <li>Verify <strong>every course's prerequisites</strong>, this tool's prereq data is incomplete</li>
      <li>Confirm course <strong>availability</strong> for your specific enrollment year</li>
      <li>If taking a <strong>minor</strong>, add those papers manually (minors not yet in this tool)</li>
      <li>Book a session with your <a href="https://www.massey.ac.nz/student-life/student-services/student-advisory-services/" target="_blank" rel="noopener" style="color:var(--green)">academic advisor</a>, they can approve and finalise your plan</li>
    </ol>`;
  main.appendChild(chkDiv);
}

function renderProgressBar(container, meta, totalPlanned) {
  const target = meta.degree_target || 360;
  const completed = meta.credits_prior || 0;
  const transfer  = meta.credits_transfer || 0;
  const planned   = (meta.credits_planned || 0) + transfer;
  const compPct   = Math.min(100, ((completed) / target) * 100);
  const planPct   = Math.min(100 - compPct, (planned / target) * 100);

  const el = document.createElement('div');
  el.className = 'progress-wrap';
  el.innerHTML = `
    <div class="progress-labels">
      <span>Degree progress</span>
      <strong>${Math.round(totalPlanned)}cr / ${target}cr</strong>
    </div>
    <div class="progress-track">
      <div class="progress-fill-completed" style="width:${compPct}%"></div>
      <div class="progress-fill-planned" style="width:${planPct}%"></div>
    </div>
    <div class="progress-legend">
      <span><span class="legend-dot" style="background:var(--green)"></span>Completed (${completed}cr)</span>
      <span><span class="legend-dot" style="background:rgba(82,183,136,0.4)"></span>Planned (${planned}cr)</span>
    </div>`;
  container.appendChild(el);
}

// ── Validation panel ──────────────────────────────────────────────────────────

async function renderValidationPanel(container, req) {
  const panel = document.createElement('div');
  panel.className = 'val-panel';
  panel.innerHTML = `
    <div class="val-header" onclick="toggleVal(this)">
      <span class="val-badge" id="val-badge">…</span>
      <span class="val-title">Degree requirements check</span>
      <span class="val-chevron">▼</span>
    </div>
    <div class="val-body" id="val-body"></div>`;
  container.appendChild(panel);

  try {
    const res = await fetch(`${API}/plan/validate`, {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(req)
    });
    const data = await res.json();
    const badge = panel.querySelector('#val-badge');
    const body  = panel.querySelector('#val-body');
    // API returns data.passed and data.checklist (tree node, not array)
    if (data.passed) {
      badge.className = 'val-badge pass'; badge.textContent = 'PASS';
    } else {
      badge.className = 'val-badge fail'; badge.textContent = 'ISSUES';
    }
    const root = data.checklist;
    if (root) {
      // Flatten top-level all_of children for cleaner display
      const nodes = (root.type === 'all_of' && root.children) ? root.children : [root];
      body.innerHTML = nodes.map(n => renderCheckNode(n)).join('');
    } else {
      body.innerHTML = '<div style="color:var(--ink3);font-size:12px;padding:8px">No validation data.</div>';
    }
  } catch(e) {
    panel.querySelector('#val-badge').textContent = '?';
  }
}

function renderCheckNode(node, depth) {
  depth = depth || 0;
  if (!node) return '';
  const passed = node.passed !== false;
  // Build human label from node type + description
  let lbl = '';
  if (node.type === 'course') {
    lbl = node.label || node.description || node.code || '';
  } else if (node.type === 'choose_credits') {
    lbl = node.label || node.description || 'Elective pool';
  } else if (node.type === 'total_credits') {
    lbl = node.label || node.description || 'Total credits';
  } else {
    lbl = node.label || node.description || '';
  }
  const childHtml = (node.children && node.children.length && depth < 2)
    ? `<div class="check-children">${node.children.slice(0,8).map(c => renderCheckNode(c, depth+1)).join('')}${node.children.length > 8 ? `<div class="check-item"><span class="check-icon" style="color:var(--ink3)">…</span><div class="check-label" style="color:var(--ink3)">${node.children.length - 8} more</div></div>` : ''}</div>`
    : '';
  return `<div class="check-item">
    <span class="check-icon ${passed?'check-pass':'check-fail'}">${passed?'✓':'✗'}</span>
    <div>
      <div class="check-label">${esc(lbl)}</div>
      ${childHtml}
    </div>
  </div>`;
}

function toggleVal(header) {
  header.classList.toggle('open');
  const body = document.getElementById('val-body');
  body.classList.toggle('open');
}

// ── Course drawer ─────────────────────────────────────────────────────────────

async function openDrawer(code) {
  const overlay = document.getElementById('overlay');
  const drawer  = document.getElementById('drawer');
  const content = document.getElementById('drawer-content');
  content.innerHTML = `<div class="loading-wrap" style="height:200px"><div class="spinner"></div></div>`;
  overlay.classList.add('open');
  drawer.classList.add('open');

  try {
    const res = await fetch(`${API}/courses/${code}`);
    if (!res.ok) { content.innerHTML = `<p style="color:var(--red)">Course not found.</p>`; return; }
    const c = await res.json();

    const levelLbl = c.level ? `L${c.level}` : '';
    const inferredNote = c.offering_inferred
      ? `<div class="warn-banner" style="margin:8px 0 0;font-size:12px">
           ⚠ Availability not confirmed for 2026, verify at 
           <a href="${c.url||'https://www.massey.ac.nz/study/'}" target="_blank" rel="noopener" style="color:inherit;text-decoration:underline">Massey ↗</a>
         </div>`
      : '';
    const studentType = localStorage.getItem('cm-student-type') || 'domestic';
    const courseFee = (c.credits && c.level != null)
      ? Math.round(c.credits * feePerCredit(c.subject_area, c.level, studentType) / 10) * 10
      : null;
    const feeHtml = courseFee
      ? `<div style="font-size:12px;color:var(--ink3);margin-top:6px">
           Est. fee: <strong style="color:var(--ink2)">${formatNZD(courseFee)}</strong>
           <span style="font-size:10px">(${studentType}, approximate)</span>
         </div>`
      : '';
    const offeringHtml = c.offerings?.map(o =>
      `<span class="offering-pill">${escAttr(o.campus)}/${escAttr(o.mode)}/${escAttr(o.semester)}</span>`
    ).join('') || '<span style="color:var(--ink3);font-size:12px">No offerings listed</span>';

    let prereqHtml = '<span style="color:var(--ink3);font-size:12px">None</span>';
    if (c.prerequisite_expression) {
      prereqHtml = `<div class="prereq-tree">${renderPrereqExpr(c.prerequisite_expression)}</div>`;
    } else if (c.prereq_data_available === false && (c.level || 0) >= 200) {
      const massey_url = c.url || 'https://www.massey.ac.nz/study/courses/';
      prereqHtml = `<span style="color:var(--blue);font-size:12px">
        ⚠ No prerequisite data recorded for this course. This usually means the
        data wasn't captured during scraping, NOT that there isn't one.
        Check <a href="${escAttr(massey_url)}" target="_blank" rel="noopener">massey.ac.nz</a>
        before enrolling.
      </span>`;
    }

    // Fetch prereq chain for visual diagram
    let chainHtml = '';
    try {
      const prereqRawWrap = document.querySelector('.prereq-raw-wrap');
      const prereqRawEl = document.getElementById('drawer-prereq-raw');
      const prereqHuman = detail.prerequisites_human || detail.prerequisites_text;
      if (prereqRawEl && prereqHuman) {
        prereqRawEl.textContent = prereqHuman;
        prereqRawWrap?.removeAttribute('hidden');
      } else if (prereqRawWrap) {
        prereqRawWrap.setAttribute('hidden', '');
      }

      const chainRes = await fetch(`${API}/courses/${code}/prereq-chain`);
      if (chainRes.ok) {
        const chain = await chainRes.json();
        if (chain.nodes && chain.nodes.length > 1) {
          chainHtml = renderPrereqChain(chain, currentPlan);
        }
      }
    } catch(e) { /* chain vis optional */ }

    // Restrictions, always escape codes, never render raw
    let restrictHtml = '';
    if (c.restrictions?.length) {
      const rCodes = c.restrictions.map(r => `<span class="pnode-code">${escAttr(r)}</span>`).join(', ');
      restrictHtml = `<div class="drawer-section"><h4>Restrictions</h4><div class="prereq-tree">${rCodes}</div></div>`;
    }

    // Use the course URL if available, otherwise fall back to Massey search
    const masseyUrl = c.url || `https://www.massey.ac.nz/study/courses/?q=${encodeURIComponent(c.code)}`;

    content.innerHTML = `
      <div class="drawer-code">${escAttr(c.code)}</div>
      <div class="drawer-title">${esc(c.title)}</div>
      <div class="drawer-badges">
        ${levelLbl ? `<span class="badge green">${escAttr(levelLbl)}</span>` : ''}
        <span class="badge">${c.credits}cr</span>
        ${c.subject ? `<span class="badge">${esc(c.subject)}</span>` : ''}
      </div>
      ${c.description ? `<div class="drawer-section"><h4>About</h4><div class="drawer-desc">${esc(c.description)}</div></div>` : ''}
      ${feeHtml}
      <div class="drawer-section">
        <h4>Offerings</h4>
        <div class="offering-pills">${offeringHtml}</div>
        ${inferredNote}
        ${c.subject_area ? `<div style="font-size:11px;color:var(--ink3);margin-top:6px">Subject area: ${esc(c.subject_area)}</div>` : ''}
      </div>
      <div class="drawer-section">
        <h4>Prerequisites</h4>
        ${prereqHtml}
        ${chainHtml ? `<div class="prereq-chain-wrap">${chainHtml}</div>` : ''}
        <div class="prereq-raw-wrap" hidden style="margin:4px 0 10px">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--text3);margin-bottom:3px">Prerequisites</div>
          <div id="drawer-prereq-raw" style="font-size:12px;color:var(--text2);line-height:1.5;font-family:var(--mono)"></div>
        </div>
        <div style="margin-top:8px">
          <button class="btn-sm" onclick="openPrereqDag(currentDrawerCode)" style="font-size:11px">
            &#9672; Visual prereq graph &#8599;
          </button>
        </div>
      </div>
      ${restrictHtml}
      <div class="drawer-section">
        <h4>Links</h4>
        <a href="${escAttr(masseyUrl)}" target="_blank" rel="noopener noreferrer" class="btn-sm" style="display:inline-block;text-decoration:none">
          View on Massey ↗
        </a>
      </div>
      <div class="drawer-actions">
        <button class="btn-sm" onclick="addToCompleted('${escAttr(c.code)}')">✓ Mark done</button>
        <button class="btn-sm" onclick="addToPrefer('${escAttr(c.code)}')">★ Prefer</button>
        <button class="btn-sm" onclick="addToExclude('${escAttr(c.code)}')">✗ Exclude</button>
      </div>`;
  } catch(e) {
    content.innerHTML = `<p style="color:var(--red)">Failed to load course.</p>`;
  }
}

function renderPrereqExpr(expr) {
  if (!expr) return '<span style="color:var(--ink3)">None</span>';
  // type/code format (from API)
  if (expr.type === 'course' && expr.code) {
    const safeCode = escAttr(expr.code);
    return `<a class="pnode-code" onclick="closeDrawer();setTimeout(()=>openDrawer('${safeCode}'),200)" href="#">${safeCode}</a>`;
  }
  if (expr.type === 'and' && expr.children) {
    const sep = `<span class="pnode-op">AND</span>`;
    return expr.children.map(a => renderPrereqExpr(a)).join(sep);
  }
  if (expr.type === 'or' && expr.children) {
    const sep = `<span class="pnode-op">OR</span>`;
    return expr.children.map(a => renderPrereqExpr(a)).join(sep);
  }
  // Legacy op/args format
  if (expr.op === 'AND' || expr.op === 'OR') {
    const sep = `<span class="pnode-op">${expr.op}</span>`;
    return (expr.args||[]).map(a => renderPrereqExpr(a)).join(sep);
  }
  if (typeof expr === 'string') {
    const safeCode = escAttr(expr);
    return `<a class="pnode-code" onclick="closeDrawer();setTimeout(()=>openDrawer('${safeCode}'),200)" href="#">${safeCode}</a>`;
  }
  return `<span style="color:var(--ink3)">${esc(JSON.stringify(expr))}</span>`;
}


document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeCourseModal();
    closeCompareModal();
    closeMajorModal();
    closeDrawer();
    return;
  } if (e.key === 'Escape') closeDrawer(); });
function openPrereqDag(code) {
  if (!code) return;
  const w = window.open('', '_blank', 'width=900,height=620,resizable=yes');
  if (!w) { toast('Allow pop-ups to view the prereq graph.'); return; }
  const safeCode = String(code).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
  const apiUrl = '/api/courses/' + encodeURIComponent(code) + '/prereq-chain';
  w.document.write('<!DOCTYPE html><html lang="en"><head>'
    + '<meta charset="UTF-8"><title>Prereq graph: ' + safeCode + '<\/title>'
    + '<style>'
    + '*{box-sizing:border-box;margin:0;padding:0}'
    + 'body{background:#0b1012;color:#e8ebe9;font-family:system-ui,sans-serif;display:flex;flex-direction:column;align-items:center;padding:24px}'
    + 'h2{margin:0 0 16px;font-size:17px;font-weight:500}'
    + '#dag{overflow:auto;max-width:100%;width:100%}'
    + '.e{fill:none;stroke:#52b788;stroke-width:1.5;opacity:.6;marker-end:url(#a)}'
    + '#m{color:#8fa89a;margin-top:40px;font-size:13px}'
    + '<\/style><\/head><body>'
    + '<h2>Prerequisite graph \u2014 ' + safeCode + '<\/h2>'
    + '<div id="dag"><p id="m">Loading\u2026<\/p><\/div>'
    + '<script>(async()=>{'
    +   'try{'
    +     'const d=await(await fetch("' + apiUrl + '")).json();'
    +     'const nodes=d.nodes||[],edges=d.edges||[];'
    +     'if(!nodes.length){document.getElementById("m").textContent="No prerequisite data found.";return;}'
    +     'const byD={};nodes.forEach(n=>{(byD[n.depth]=byD[n.depth]||[]).push(n);});'
    +     'const maxD=Math.max(...nodes.map(n=>n.depth));'
    +     'const NW=148,NH=52,RH=100,PAD=28;'
    +     'const maxPR=Math.max(...Object.values(byD).map(r=>r.length));'
    +     'const W=Math.max(600,maxPR*(NW+16)+PAD*2);'
    +     'const H=(maxD+1)*RH+60;'
    +     'const pos={};'
    +     'Object.entries(byD).forEach(([dep,ns])=>{'
    +       'const y=parseInt(dep)*RH+PAD;'
    +       'ns.forEach((n,i)=>{pos[n.code]={x:PAD+(i+0.5)*(W-PAD*2)/ns.length-NW/2,y};});'
    +     '});'
    +     'let svg=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`'
    +       '+"<defs><marker id=\\"a\\" markerWidth=\\"8\\" markerHeight=\\"8\\" refX=\\"6\\" refY=\\"3\\" orient=\\"auto\\"><path d=\\"M0,0L0,6L8,3z\\" fill=\\"#52b788\\"\/><\/marker><\/defs>";'
    +     'edges.forEach(e=>{'
    +       'const f=pos[e.from],t=pos[e.to];'
    +       'if(f&&t){const fx=f.x+NW/2,fy=f.y+NH,tx=t.x+NW/2,ty=t.y,my=(fy+ty)/2;'
    +         'svg+=`<path class="e" d="M${fx},${fy} C${fx},${my} ${tx},${my} ${tx},${ty}"\/>`}'
    +     '});'
    +     'nodes.forEach(n=>{'
    +       'const p=pos[n.code];if(!p)return;'
    +       'const isT=(n.code==="' + code + '");'
    +       'const fill=isT?"rgba(82,183,136,.18)":"#1e2527";'
    +       'const stroke=isT?"#52b788":"rgba(255,255,255,.15)";'
    +       'svg+=`<g>`'
    +         '+`<rect x="${p.x}" y="${p.y}" width="${NW}" height="${NH}" fill="${fill}" stroke="${stroke}" stroke-width="${isT?2:1}" rx="6"\/>`'
    +         '+`<text x="${p.x+NW/2}" y="${p.y+18}" text-anchor="middle" font-size="11" font-weight="600" fill="#e8ebe9" font-family="monospace">${n.code}<\/text>`'
    +         '+`<text x="${p.x+NW/2}" y="${p.y+32}" text-anchor="middle" font-size="10" fill="#8fa89a">${n.title.slice(0,22)}<\/text>`'
    +         '+`<text x="${p.x+NW/2}" y="${p.y+46}" text-anchor="middle" font-size="9" fill="#556860">depth ${n.depth} \xb7 ${n.credits}cr<\/text>`'
    +         '+"<\/g>";'
    +     '});'
    +     'svg+="<\/svg>";'
    +     'document.getElementById("dag").innerHTML=svg;'
    +   '}catch(e){document.getElementById("m").textContent="Error: "+e.message;}'
    + '})();<\/script><\/body><\/html>');
  w.document.close();
}

function openCompareModal() {
  document.getElementById('compare-modal').style.display = 'flex';
  const firstInput = document.querySelector('.cmp-input');
  if (firstInput) setTimeout(() => firstInput.focus(), 50);
  // Pre-fill first input from current major if available
  const curMajor = document.getElementById('major-input')?.value;
  const inputs = document.querySelectorAll('.cmp-input');
  if (curMajor && inputs[0] && !inputs[0].value) inputs[0].value = curMajor;
}

function closeCompareModal() {
  document.getElementById('compare-modal').style.display = 'none';
}

function addCmpRow() {
  const rows = document.getElementById('cmp-rows');
  if (rows.children.length >= 4) { toast('Maximum 4 majors to compare.'); return; }
  const inp = document.createElement('input');
  inp.type = 'text';
  inp.className = 'cmp-input';
  inp.placeholder = `Major ${rows.children.length + 1}`;
  inp.style.cssText = 'width:100%;padding:7px 10px;border-radius:6px;border:1px solid var(--border1);background:var(--bg2);color:var(--text1);font-size:13px';
  rows.appendChild(inp);
  inp.focus();
}

async function runCompare() {
  const inputs = [...document.querySelectorAll('.cmp-input')]
    .map(i => i.value.trim()).filter(Boolean);
  if (inputs.length < 2) { toast('Enter at least 2 majors to compare.'); return; }
  const res_div = document.getElementById('cmp-results');
  res_div.innerHTML = '<p style="color:var(--text2);font-size:13px">Generating plans…</p>';
  try {
    const campus   = document.getElementById('campus-select')?.value || 'D';
    const mode     = document.getElementById('mode-select')?.value   || 'DIS';
    const startY   = parseInt(document.getElementById('start-year')?.value  || new Date().getFullYear());
    const startS   = document.getElementById('start-sem')?.value     || 'S1';
    const res = await fetch(`${API}/plan/compare`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({majors:inputs,campus,mode,start_year:startY,start_semester:startS,no_summer:true}),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({detail: res.status}));
      res_div.innerHTML = `<p style="color:var(--red);font-size:13px">Error: ${esc(String(err.detail||res.status))}</p>`;
      return;
    }
    const data = await res.json();
    const comps = data.comparisons || [];
    let html = '<table style="width:100%;border-collapse:collapse;font-size:13px">';
    html += '<thead><tr style="border-bottom:2px solid var(--border1)">';
    html += '<th style="text-align:left;padding:8px 10px;color:var(--text2);font-weight:500">Metric</th>';
    comps.forEach(c => {
      const color = c.error ? 'var(--red)' : 'var(--green)';
      html += `<th style="text-align:center;padding:8px 10px;color:${color};font-weight:500;max-width:200px;word-break:break-word">${esc(c.major)}</th>`;
    });
    html += '</tr></thead><tbody>';
    const ROWS = [
      ['Semesters to complete', c => c.error ? '-' : `<strong>${c.semesters}</strong>`],
      ['Credits scheduled',     c => c.error ? '-' : `${c.credits_scheduled}cr`],
      ['Degree target',         c => c.error ? '-' : `${c.degree_target}cr`],
      ['Free elective gap',     c => c.error ? '-' : (c.free_elective_gap > 0 ? `<span style="color:var(--amber)">${c.free_elective_gap}cr gap</span>` : '<span style="color:var(--green)">✓ filled</span>')],
      ['Prereq data coverage',  c => c.error ? '-' : `${c.prereq_coverage_pct}%`],
      ['Shared with first major', c => (!c.error && c.shared_with_first > 0) ? c.shared_with_first + ' courses' : '-'],
    ];
    ROWS.forEach(([label, fn], ri) => {
      html += `<tr style="border-bottom:1px solid var(--border1);background:${ri%2===0?'transparent':'var(--bg2)'}">`;
      html += `<td style="padding:7px 10px;color:var(--text2)">${label}</td>`;
      comps.forEach(c => {
        html += `<td style="text-align:center;padding:7px 10px;color:var(--text1)">${fn(c)}</td>`;
      });
      html += '</tr>';
    });
    html += '</tbody></table>';
    const errs = comps.filter(c => c.error);
    if (errs.length) {
      html += `<p style="color:var(--amber);font-size:12px;margin-top:8px">&#9888; ${errs.length} major(s) could not be found. Check the name matches exactly.</p>`;
    }
    res_div.innerHTML = html;
  } catch(e) {
    res_div.innerHTML = `<p style="color:var(--red);font-size:13px">Network error: ${esc(e.message)}</p>`;
  }
}

// Close compare modal on backdrop click
document.getElementById('compare-modal')?.addEventListener('click', function(e) {
  if (e.target === this) closeCompareModal();
});

function closeDrawer() {
  document.getElementById('overlay').classList.remove('open');
  document.getElementById('drawer').classList.remove('open');
}

// ── Course modal ──────────────────────────────────────────────────────────────

async function openCourseModal() {
  document.getElementById('course-modal').classList.add('open');
  document.getElementById('modal-q').value = '';
  document.getElementById('modal-q').focus();
  // Load a smaller initial set, server handles filtering
  await fetchModalCourses('', modalLevel);
}

function closeCourseModal() {
  document.getElementById('course-modal').classList.remove('open');
  _modalSem = null;
  document.querySelectorAll('#modal-sem-filters .f-pill').forEach((p, i) => {
    p.classList.toggle('active', i === 0);
  });
}

let modalSearchTimer = null;
function modalSearch(q) {
  clearTimeout(modalSearchTimer);
  // Debounce search, wait 250ms after last keystroke before hitting the API
  modalSearchTimer = setTimeout(() => fetchModalCourses(q, modalLevel), 250);
}

function setModalSemester(el, sem) {
  document.querySelectorAll('#modal-sem-filters .f-pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  _modalSem = sem || null;
  fetchModalCourses(document.getElementById('modal-q').value, modalLevel);
}

function setModalLevel(el, lvl) {
  document.querySelectorAll('[data-level]').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  modalLevel = lvl;
  fetchModalCourses(document.getElementById('modal-q').value, modalLevel);
}

function setModalSubject(el, subj) {
  document.querySelectorAll('[data-subj]').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  modalSubject = subj;
  fetchModalCourses(document.getElementById('modal-q').value, modalLevel);
}

async function fetchModalCourses(q, lvl) {
  const campus = document.getElementById('campus').value;
  const mode   = document.getElementById('mode').value;
  const params = new URLSearchParams({ limit: 150, campus, mode });
  if (q && q.trim()) params.set('search', q.trim());
  if (lvl === 'exclude_research') {
    params.set('exclude_research', '1');
  } else if (lvl) {
    params.set('level', lvl === '700' ? '700' : lvl);
  }
  if (modalSubject) params.set('subject_area', modalSubject);
  if (_modalSem) params.set('semester', _modalSem);
  params.set('min_credits', '1');

  document.getElementById('modal-results').innerHTML =
    `<div class="modal-empty"><div class="spinner" style="margin:0 auto 8px"></div>Loading…</div>`;
  document.getElementById('modal-count').textContent = 'Loading…';

  try {
    const res = await fetch(`${API}/courses?${params}`);
    const data = await res.json();
    const courses = data.courses || [];
    const total = data.count || courses.length;

    document.getElementById('modal-count').textContent =
      `${total.toLocaleString()} courses${q ? ` matching "${q}"` : ''}${total > 150 ? ' (showing first 150)' : ''}`;

    if (!courses.length) {
      document.getElementById('modal-results').innerHTML = `<div class="modal-empty">No courses found.</div>`;
      return;
    }

    document.getElementById('modal-results').innerHTML = courses.map(c => {
      const sems = (c.offered_semesters || []).join('/');
      const safeCode = escAttr(c.code);
      const inferredMark = c.offering_inferred ? ' <span title="Offering not confirmed 2026" style="color:var(--amber);font-size:10px">?</span>' : '';
      const subjectTag = c.subject_area ? `<span style="font-size:10px;color:var(--ink3);margin-left:4px">${esc(c.subject_area)}</span>` : '';
      return `<div class="modal-row" onclick="closeCourseModal();openDrawer('${safeCode}')">
        <span class="modal-code">${escAttr(c.code)}${inferredMark}</span>
        <span class="modal-title">${esc(c.title)}${subjectTag}</span>
        <span class="modal-cr">${c.credits}cr</span>
        <span class="modal-sem">${escAttr(sems)}</span>
      </div>`;
    }).join('') + (total > 150 ? `<div class="modal-empty" style="padding:12px;font-size:12px;color:var(--ink3)">Showing first 150 of ${total.toLocaleString()}. Refine your search to narrow down</div>` : '');
  } catch(e) {
    document.getElementById('modal-results').innerHTML = `<div class="modal-empty">Failed to load courses.</div>`;
    document.getElementById('modal-count').textContent = '';
  }
}

// ── Mark semester done ────────────────────────────────────────────────────────

function markDone(codes) {
  codes.forEach(c => addTag('completed-wrap', c));
  toast(`${codes.length} course${codes.length===1?'':'s'} marked as completed. Click "Generate plan" to update your schedule.`);
  // Visually mark the semester as done
  codes.forEach(code => {
    document.querySelectorAll('.course-card').forEach(card => {
      if (card.querySelector('.course-code')?.textContent.includes(code)) {
        card.classList.add('done');
      }
    });
  });
}

// ── Saved plans ───────────────────────────────────────────────────────────────

function getSaved() {
  try { return JSON.parse(localStorage.getItem('cm_saved_plans')||'[]'); }
  catch(e) { return []; }
}

function setSaved(plans) {
  localStorage.setItem('cm_saved_plans', JSON.stringify(plans));
}

function renderSavedPlans() {
  const list = document.getElementById('saved-list');
  const plans = getSaved();
  if (!plans.length) {
    list.innerHTML = `<div class="saved-empty">No saved plans yet.</div>`;
    return;
  }
  list.innerHTML = plans.map((p, i) => {
    const dateStr = p.savedAt
      ? new Date(p.savedAt).toLocaleDateString('en-NZ', {day:'numeric',month:'short',year:'numeric'})
      : '';
    const shareBtn = p.plan_id
      ? `<button class="saved-btn" title="Copy share link"
           onclick="event.stopPropagation();copySavedLink('${escAttr(p.plan_id)}')">⬡</button>`
      : '';
    return `<div class="saved-item" onclick="loadSaved(${i})">
      <div class="saved-item-left">
        <span class="saved-name">${esc(p.name)}</span>
        <span class="saved-meta">${p.credits||'?'}cr${dateStr ? ' · ' + dateStr : ''}</span>
      </div>
      <div class="saved-actions">
        ${shareBtn}
        <button class="saved-btn" onclick="event.stopPropagation();deleteSaved(${i})" title="Delete">✕</button>
      </div>
    </div>`;
  }).join('');
}

function promptSave() {
  document.getElementById('save-row').style.display = 'flex';
  document.getElementById('save-name').value = '';
  document.getElementById('save-name').focus();
  document.getElementById('btn-save').style.display = 'none';
}

function cancelSave() {
  document.getElementById('save-row').style.display = 'none';
  document.getElementById('btn-save').style.display = '';
}

function commitSave() {
  const name = document.getElementById('save-name').value.trim();
  if (!name || !currentPlan) return;
  const plans = getSaved();
  const meta  = currentPlan.response.meta || {};
  const planId = currentPlan.response.plan_id || null;

  // Check for duplicate name, warn but still save
  const dupeIdx = plans.findIndex(p => p.name === name);
  if (dupeIdx >= 0) {
    plans.splice(dupeIdx, 1); // replace
    toast(`Updated "${name}".`);
  } else {
    toast('Plan saved.');
  }

  plans.unshift({
    name,
    credits: (meta.credits_planned||0) + (meta.credits_prior||0) + (meta.credits_transfer||0),
    major:   meta.major || currentPlan.request?.major || '',
    request: currentPlan.request,
    plan_id: planId,
    savedAt: new Date().toISOString(),
  });

  // Keep at most 20 saved plans
  if (plans.length > 20) plans.length = 20;

  setSaved(plans);
  cancelSave();
  renderSavedPlans();
}

async function loadSaved(i) {
  const plan = getSaved()[i];
  if (!plan) return;

  // If we have a plan_id, try fetching the cached plan directly (no re-run)
  if (plan.plan_id) {
    showLoading();
    closeSidebar();
    try {
      const res = await fetch(`${API}/plan/${plan.plan_id}`);
      if (res.ok) {
        const data = await res.json();
        currentPlan = {request: plan.request, response: data};
        fillerCodes = new Set(data.filler_codes||[]);
        sharedCodes = new Set(data.double_major_info?.shared_codes||[]);
        renderPlan(data);
        pushUrl(plan.request, data.plan_id);
        setExportButtons(true);
        // Restore form state too
        _restoreFormFromRequest(plan.request);
        return;
      }
    } catch(e) {}
    // Cache miss, fall through to regenerate
    toast('Cached plan expired, regenerating…');
  }

  // Fallback: restore form and regenerate
  _restoreFormFromRequest(plan.request || {});
  generatePlan();
}

function _restoreFormFromRequest(req) {
  if (!req) return;
  if (req.major)            document.getElementById('major-input').value = req.major;
  if (req.double_major)     document.getElementById('double-input').value = req.double_major || '';
  if (req.start_year)       document.getElementById('start-year').value   = req.start_year;
  if (req.start_semester)   document.getElementById('start-sem').value    = req.start_semester;
  if (req.max_credits)      document.getElementById('max-credits').value  = req.max_credits;
  if (req.campus)           document.getElementById('campus').value       = req.campus;
  if (req.mode)             document.getElementById('mode').value         = req.mode;
  if (req.transfer_credits !== undefined) document.getElementById('transfer').value = req.transfer_credits;
  document.getElementById('no-summer').checked = !!req.no_summer;
  document.getElementById('auto-fill').checked  = !!req.auto_fill;
  ['completed-wrap','prefer-wrap','exclude-wrap'].forEach(id => {
    document.querySelectorAll(`#${id} .tag`).forEach(t => t.remove());
  });
  (req.completed||[]).forEach(c => addTag('completed-wrap', c));
  (req.prefer||[]).forEach(c    => addTag('prefer-wrap', c));
  (req.exclude||[]).forEach(c   => addTag('exclude-wrap', c));
}

async function copySavedLink(planId) {
  const url = `${location.origin}${location.pathname}?pid=${planId}`;
  try {
    await navigator.clipboard.writeText(url);
    toast('Share link copied!');
  } catch(e) {
    prompt('Copy this link:', url);
  }
}

function deleteSaved(i) {
  const plans = getSaved();
  const name  = plans[i]?.name || 'plan';
  plans.splice(i, 1);
  setSaved(plans);
  renderSavedPlans();
  toast(`"${name}" deleted.`);
}

// ── URL state ─────────────────────────────────────────────────────────────────

function pushUrl(req, planId) {
  const p = new URLSearchParams();
  if (req.major)          p.set('major', req.major);
  if (req.double_major)   p.set('dm', req.double_major);
  if (req.start_year)     p.set('year', req.start_year);
  if (req.start_semester) p.set('sem', req.start_semester);
  if (req.max_credits)    p.set('cr', req.max_credits);
  if (req.campus)         p.set('campus', req.campus);
  if (req.mode)           p.set('mode', req.mode);
  if (req.no_summer)      p.set('nosummer', '1');
  if (req.auto_fill)      p.set('fill', '1');
  if (req.transfer_credits) p.set('transfer', req.transfer_credits);
  if (req.completed?.length) p.set('done', req.completed.join(','));
  if (req.prefer?.length)    p.set('prefer', req.prefer.join(','));
  if (req.exclude?.length)   p.set('exclude', req.exclude.join(','));
  // Stable plan_id, share links load the cached plan, not a re-run
  if (planId) p.set('pid', planId);
  history.replaceState(null,'',`?${p.toString()}`);
}

async function restoreFromUrl() {
  const p = new URLSearchParams(location.search);
  if (p.get('major')) document.getElementById('major-input').value = p.get('major');
  if (p.get('dm'))    document.getElementById('double-input').value = p.get('dm');
  if (p.get('year'))  document.getElementById('start-year').value = p.get('year');
  if (p.get('sem'))   document.getElementById('start-sem').value = p.get('sem');
  if (p.get('cr'))    document.getElementById('max-credits').value = p.get('cr');
  if (p.get('campus')) document.getElementById('campus').value = p.get('campus');
  if (p.get('mode'))   document.getElementById('mode').value = p.get('mode');
  if (p.get('nosummer')) document.getElementById('no-summer').checked = true;
  if (p.get('fill'))     document.getElementById('auto-fill').checked = true;
  if (p.get('transfer')) document.getElementById('transfer').value = p.get('transfer');
  if (p.get('done'))     p.get('done').split(',').filter(Boolean).forEach(c => addTag('completed-wrap',c));
  if (p.get('prefer'))   p.get('prefer').split(',').filter(Boolean).forEach(c => addTag('prefer-wrap',c));
  if (p.get('exclude'))  p.get('exclude').split(',').filter(Boolean).forEach(c => addTag('exclude-wrap',c));

  if (p.get('pid')) {
    // Shared link with a plan_id, fetch the cached plan directly (deterministic)
    showLoading();
    try {
      const res = await fetch(`${API}/plan/${p.get('pid')}`);
      if (res.ok) {
        const data = await res.json();
        currentPlan = { request: _reqFromUrl(p), response: data };
        fillerCodes = new Set(data.filler_codes||[]);
        sharedCodes = new Set(data.double_major_info?.shared_codes||[]);
        renderPlan(data);
        setExportButtons(true);
        return;
      }
    } catch(e) {}
    // Cache miss, fall through to re-generate
  }

  if (p.get('major')) setTimeout(() => generatePlan(), 300);
}

function _reqFromUrl(p) {
  return {
    major: p.get('major')||'',
    double_major: p.get('dm')||null,
    start_year: parseInt(p.get('year'))||new Date().getFullYear(),
    start_semester: p.get('sem')||'S1',
    max_credits: parseInt(p.get('cr'))||60,
    campus: p.get('campus')||'D',
    mode: p.get('mode')||'DIS',
    no_summer: !!p.get('nosummer'),
    auto_fill: !!p.get('fill'),
    transfer_credits: parseInt(p.get('transfer'))||0,
    completed: (p.get('done')||'').split(',').filter(Boolean),
    prefer: (p.get('prefer')||'').split(',').filter(Boolean),
    exclude: (p.get('exclude')||'').split(',').filter(Boolean),
  };
}

function copyLink() {
  navigator.clipboard.writeText(location.href).then(() => toast('Share link copied!'));
}

// ── Downloads ─────────────────────────────────────────────────────────────────

function downloadJson() {
  if (!currentPlan) return;
  const blob = new Blob([JSON.stringify(currentPlan.response, null, 2)], {type:'application/json'});
  dlBlob(blob, 'coursemap-plan.json');
}

async function downloadAdvisorSummary() {
  if (!lastPlanId) { toast('Generate a plan first.'); return; }
  try {
    const r = await fetch(`${API}/plan/${encodeURIComponent(lastPlanId)}/advisor-summary`);
    if (!r.ok) { toast('Could not fetch advisor summary.'); return; }
    const blob = await r.blob();
    dlBlob(blob, `degree_plan_${lastPlanId}.txt`);
  } catch(e) { toast('Network error: ' + e.message); }
}

async function downloadMarkdown() {
  if (!lastPlanId) { toast('Generate a plan first.'); return; }
  try {
    const r = await fetch(`${API}/plan/${encodeURIComponent(lastPlanId)}/markdown`);
    if (!r.ok) { toast('Could not fetch Markdown export.'); return; }
    const blob = await r.blob();
    dlBlob(blob, `degree_plan_${lastPlanId}.md`);
  } catch(e) { toast('Network error: ' + e.message); }
}

async function downloadIcal() {
  if (!currentPlan) return;
  try {
    const res = await fetch(`${API}/plan/ical`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(currentPlan.request)
    });
    if (!res.ok) { toast('iCal generation failed.'); return; }
    const blob = await res.blob();
    dlBlob(blob, 'coursemap-plan.ics');
  } catch(e) { toast('Network error.'); }
}

function downloadHtml() {
  if (!currentPlan) return;
  const plan = currentPlan.response;
  const meta = plan.meta;
  const sems = plan.semesters;
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>coursemap: ${escHtml(meta.major)}</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;background:#f9f9f7;color:#1a1a18}
  h1{font-size:24px;margin:0 0 4px}
  .sub{font-size:12px;color:#666;margin-bottom:1.5rem}
  .sem{margin-bottom:1.5rem;border:1px solid #ddd;border-radius:8px;overflow:hidden}
  .sem-head{background:#f0f0ec;padding:8px 14px;font-weight:500;font-size:13px;display:flex;gap:12px;border-bottom:1px solid #ddd}
  .sem-label{font-weight:600}
  .sem-cr{color:#666}
  table{width:100%;border-collapse:collapse}
  td{padding:7px 14px;font-size:12px;border-bottom:1px solid #eee}
  tr:last-child td{border-bottom:none}
  .code{font-family:monospace;color:#2a5c45}
  .elective{color:#888;font-size:10px}
  .disclaimer{font-size:11px;color:#888;margin-top:2rem;padding:10px;background:#fff3e0;border-radius:6px}

/* ── Prerequisite chain visualisation ─────────────────────────────── */
.prereq-chain-wrap {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.prereq-chain {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  padding: 12px;
  background: var(--bg);
  border-radius: var(--r2);
  border: 1px solid var(--border);
  overflow-x: auto;
}
.pchain-col {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.pchain-arrow {
  font-size: 16px;
  color: var(--ink3);
  padding: 0 2px;
  flex-shrink: 0;
}
.pchain-node {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: var(--r);
  cursor: pointer;
  min-width: 120px;
  max-width: 150px;
  transition: border-color 0.15s, background 0.15s;
  position: relative;
}
.pchain-node:hover { border-color: var(--green); background: var(--green-lt); }
.pchain-node.target {
  border-color: var(--green);
  background: var(--green-lt);
}
.pchain-node.planned {
  border-color: var(--green);
  opacity: 0.85;
}
.pchain-code { font-family: var(--mono); font-size: 11px; color: var(--ink3); font-weight: 500; }
.pchain-title { font-size: 11px; color: var(--ink); line-height: 1.3; }
.pchain-tick {
  position: absolute;
  top: 4px; right: 6px;
  font-size: 10px;
  color: var(--green);
  font-weight: 700;
}

/* ── Fees estimate ───────────────────────────────────────────────── */
.fees-toggle {
  font-size: 11px;
  color: var(--ink3);
  cursor: pointer;
  text-decoration: underline;
  text-decoration-style: dotted;
  margin-top: 4px;
  display: block;
}
.fees-toggle:hover { color: var(--green); }

/* ── Print styles ──────────────────────────────────────────────── */
@media print {
  .sidebar, .header, .export-bar, .disclaimer,
  .btn-sm, .mark-done-btn, #overlay, #drawer,
  #course-modal, .tab-bar, .toast-wrap { display: none !important; }
  .main { margin: 0 !important; padding: 16px !important; }
  .course-card { break-inside: avoid; }
  .sem-block { break-inside: avoid; }
  body { background: white !important; color: black !important; }
}

/* ── Prereq satisfaction indicator on course cards ─────────────── */
.course-card .prereq-ok {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--green);
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
  flex-shrink: 0;
}
.course-card .prereq-miss {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--amber);
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
  flex-shrink: 0;
}
.course-card .prereq-unverified {
  display: inline-block;
  width: 6px; height: 6px;
  background: var(--blue);
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
  flex-shrink: 0;
}

/* ── Student type toggle ─────────────────────────────────────────── */
.student-type-btn {
  font-size: 11px;
  padding: 5px 8px;
  transition: background 0.15s, color 0.15s;
}
.student-type-btn.active {
  background: var(--green);
  color: #fff;
  border-color: var(--green);
}


/* ── Error state alternative suggestions ────────────────────────── */
.error-alts {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
.error-alts-label {
  font-size: 12px;
  color: var(--ink3);
}
.error-state { text-align: center; padding: 48px 24px; }
.error-icon  { font-size: 32px; margin-bottom: 12px; }
.error-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; color: var(--ink); }
.error-body  { font-size: 13px; color: var(--ink2); max-width: 480px; margin: 0 auto; line-height: 1.5; }


/* ── Done/completed course cards ─────────────────────────────────── */
.course-card.done {
  opacity: 0.55;
  position: relative;
}
.course-card.done::after {
  content: '✓';
  position: absolute;
  top: 6px; right: 8px;
  font-size: 13px;
  color: var(--green);
  font-weight: 700;
}


/* ── Info (non-warning) banner ──────────────────────────────────── */
.warn-banner.warn-full-year {
  border-left:3px solid var(--amber);
  background:var(--amber-lt);
}
.warn-banner.info {
  background: color-mix(in srgb, var(--green) 8%, var(--bg2));
  border-color: color-mix(in srgb, var(--green) 30%, var(--border));
  color: var(--ink2);
}


/* ── Drawer action buttons ───────────────────────────────────────── */
.drawer-actions {
  display: flex;
  gap: 8px;
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  background: var(--bg);
  margin-top: auto;
  flex-shrink: 0;
}
.drawer-actions .btn-sm {
  flex: 1;
  justify-content: center;
  font-size: 11.5px;
}

</style>
</head>
<body>
<h1>${escHtml(meta.major)}</h1>
<div class="sub">Generated by coursemap · ${meta.start_year} ${meta.start_semester} · ${meta.campus}/${meta.mode} · ${meta.credits_planned + meta.credits_prior}cr</div>
${sems.map(s => `
<div class="sem">
  <div class="sem-head">
    <span class="sem-label">${s.year} ${s.semester}</span>
    <span class="sem-cr">${s.credits}cr</span>
  </div>
  <table>${s.courses.map(c => `
    <tr>
      <td class="code">${c.code}</td>
      <td>${escHtml(c.title)}${plan.filler_codes?.includes(c.code)?'<span class="elective"> · elective</span>':''}</td>
      <td>${c.credits}cr</td>
    </tr>`).join('')}
  </table>
</div>`).join('')}
<div class="disclaimer">⚠ This plan is generated by coursemap, an unofficial tool. Always verify with Massey University's official programme information and your academic advisor.</div>
</body></html>`;
  dlBlob(new Blob([html],{type:'text/html'}), 'coursemap-plan.html');
}

function dlBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), {href:url, download:filename});
  a.click();
  URL.revokeObjectURL(url);
}

// ── Mobile sidebar ────────────────────────────────────────────────────────────

function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebar-backdrop').classList.toggle('open');
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebar-backdrop').classList.remove('open');
}

// ── Toast ─────────────────────────────────────────────────────────────────────

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2800);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function escAttr(s) { return esc(s); }
function escHtml(s) { return esc(s); }

// ── Mobile tab bar ──────────────────────────────────────────────────────────
// On mobile, the hamburger + sidebar-overlay pattern requires too many taps.
// A bottom tab bar lets students switch between Settings, Plan and Courses
// with a single tap, matching native app conventions on iOS/Android.

function initTabBar() {
  const bar = document.getElementById('mobile-tabs');
  if (!bar) return;
  // Show tab bar only on mobile
  if (window.innerWidth > 900) return;
  bar.style.display = 'flex';
  // Adjust main padding so content isn't hidden under the tab bar
  document.querySelector('.main').style.paddingBottom = '70px';
  setActiveTab('plan');
}

function setActiveTab(tab) {
  document.querySelectorAll('.mob-tab').forEach(t => t.classList.remove('active'));
  const el = document.getElementById(`tab-${tab}`);
  if (el) el.classList.add('active');

  if (tab === 'settings') {
    openSidebar();
  } else if (tab === 'plan') {
    closeSidebar();
    document.getElementById('main').scrollIntoView({behavior:'smooth'});
  } else if (tab === 'courses') {
    closeSidebar();
    openCourseModal();
  }
}

function openSidebar() {
  document.querySelector('.sidebar')?.classList.add('open');
  document.querySelector('.sidebar-backdrop')?.classList.add('open');
}

// ── Start ─────────────────────────────────────────────────────────────────────
init();
// Tab bar runs after init so elements exist
setTimeout(initTabBar, 0);

// ── Prerequisite chain visualisation ─────────────────────────────────────────

function renderPrereqChain(chain, plan) {
  // Build a visual horizontal chain: root → ... → target
  const nodes = chain.nodes || [];
  const targetCode = chain.code;
  
  // Get all planned/completed codes
  const plannedCodes = new Set();
  if (plan) {
    (plan.semesters || []).forEach(s => (s.courses || []).forEach(c => plannedCodes.add(c.code)));
    (plan.prior_completed || []).forEach(c => plannedCodes.add(c.code || c));
  }

  if (nodes.length <= 1) return '';

  // Group nodes by depth
  const byDepth = {};
  nodes.forEach(n => {
    if (!byDepth[n.depth]) byDepth[n.depth] = [];
    byDepth[n.depth].push(n);
  });
  const maxDepth = Math.max(...Object.keys(byDepth).map(Number));

  let html = '<div class="prereq-chain">';
  for (let d = 0; d <= maxDepth; d++) {
    const dNodes = byDepth[d] || [];
    const isLast = d === maxDepth;
    html += '<div class="pchain-col">';
    dNodes.forEach(n => {
      const isPlanned = plannedCodes.has(n.code);
      const isTarget  = n.code === targetCode;
      const cls = isTarget ? 'pchain-node target' : isPlanned ? 'pchain-node planned' : 'pchain-node';
      const tick = isPlanned && !isTarget ? '<span class="pchain-tick">✓</span>' : '';
      html += `<div class="${cls}" onclick="closeDrawer();setTimeout(()=>openDrawer('${escAttr(n.code)}'),200)" title="${esc(n.title)}">
        ${tick}
        <span class="pchain-code">${esc(n.code)}</span>
        <span class="pchain-title">${esc(n.title.length > 22 ? n.title.slice(0,21)+'…' : n.title)}</span>
      </div>`;
    });
    html += '</div>';
    if (!isLast) html += '<div class="pchain-arrow">→</div>';
  }
  html += '</div>';
  return html;
}

// ── Prereq satisfaction in course cards ──────────────────────────────────────

function getPrereqSatisfaction(course, plannedCodes) {
  // Returns: 'satisfied' | 'partial' | 'missing' | 'unverified' | 'none'
  //
  // 'unverified' means: no prerequisite is recorded for this course, AND
  // it's at a level (200+) where Massey courses almost always have one.
  // This is NOT the same as "confirmed no prerequisite". The dataset has
  // a real, substantial gap here (around a third of L200+ courses have no
  // prerequisite recorded, which is a data-collection gap, not a fact about
  // the course). Surfacing this distinctly means a student isn't shown the
  // same "all clear" appearance for "we don't have this data" as for
  // "this genuinely has no prerequisite". Those are very different things
  // to rely on before enrolling.
  if (!course.prerequisite_expression) {
    if (course.prereq_data_available === false && (course.level || 0) >= 200) {
      return 'unverified';
    }
    return 'none';
  }

  function check(expr) {
    if (!expr) return true;
    if (expr.type === 'course') return plannedCodes.has(expr.code);
    if (expr.type === 'and') return (expr.children || []).every(check);
    if (expr.type === 'or')  return (expr.children || []).some(check);
    if (typeof expr === 'string') return plannedCodes.has(expr);
    return true;
  }
  
  const satisfied = check(course.prerequisite_expression);
  return satisfied ? 'satisfied' : 'missing';
}

// ── NZ fees estimator ─────────────────────────────────────────────────────────
// The rate table below is a FALLBACK ONLY, used if /api/fees/constants can't
// be reached at startup (e.g. briefly offline). Once loadFeeConstants() below
// succeeds, FEE_RATES_DOMESTIC etc. are overwritten with the live values from
// coursemap/domain/fees.py, the single source of truth. Do not hand-edit
// this table to add a subject; edit fees.py instead, or the two will drift
// apart again (this already happened once: this copy was missing "Software
// Engineering" and "Information Sciences", silently understating their fee
// estimate to the flat default rate while the backend was already correct).

let FEE_RATES_DOMESTIC = {
  "Art History": 52, "Classical Studies": 52, "Classics": 52, "Development Studies": 52,
  "Music": 58, "Philosophy": 52, "Politics": 52, "Sociology": 52,
  "International Relations": 52, "History": 52, "Geography": 55,
  "Criminology": 54, "Counselling": 58, "Psychology": 55, "Social Work": 58,
  "Accounting": 60, "Business": 60, "Business Administration": 62, "Business Law": 60,
  "Economics": 58, "Finance": 62, "Financial Planning": 60, "Human Resources": 60,
  "Management": 60, "Marketing": 60, "Strategic Studies": 60,
  "Applied Statistics": 62, "Biomedical Science": 65, "Chemistry": 65,
  "Computer Science": 65, "Data Science": 65, "Environmental Science": 62,
  "Information Systems": 62, "Information Technology": 62, "Mathematics": 62,
  "Physics": 65, "Statistics": 62, "Agriculture": 65, "Construction": 68,
  "Environmental Management": 62, "Defence Studies": 55, "Dietetics": 72,
  "Education": 58, "Health Science": 65, "Midwifery": 75, "Nursing": 72,
  "Paramedicine": 72, "Physiotherapy": 78, "Sport & Exercise Science": 65,
  "Sport Science": 65, "Design": 70, "Research Methods": 58, "Foundation Studies": 50,
};
let FEE_INTL_MULTIPLIER = 2.8;
let FEE_DEFAULT_UG = 60;
let FEE_DEFAULT_PG = 75;
let FEE_PG_MIN_RATE = 70;
let feeConstantsLoaded = false;

async function loadFeeConstants() {
  try {
    const c = await fetch(`${API}/fees/constants`, {signal: AbortSignal.timeout(5000)}).then(r => r.json());
    if (c && c.subject_fee_per_credit) {
      FEE_RATES_DOMESTIC = c.subject_fee_per_credit;
      FEE_INTL_MULTIPLIER = c.international_multiplier ?? FEE_INTL_MULTIPLIER;
      FEE_DEFAULT_UG = c.default_fee_per_credit_ug ?? FEE_DEFAULT_UG;
      FEE_DEFAULT_PG = c.default_fee_per_credit_pg ?? FEE_DEFAULT_PG;
      FEE_PG_MIN_RATE = c.postgrad_min_rate ?? FEE_PG_MIN_RATE;
      feeConstantsLoaded = true;
    }
  } catch (e) {
    // Server briefly unreachable. Keep the bundled fallback table above.
    // It may be slightly stale but estimates are approximate either way.
  }
}

function feePerCredit(subjectArea, level, studentType) {
  let base = (subjectArea && FEE_RATES_DOMESTIC[subjectArea])
    ? FEE_RATES_DOMESTIC[subjectArea]
    : (level >= 700 ? FEE_DEFAULT_PG : FEE_DEFAULT_UG);
  if (level >= 700 && base < FEE_PG_MIN_RATE) base = Math.max(base, FEE_PG_MIN_RATE);
  if (studentType === 'international') base *= FEE_INTL_MULTIPLIER;
  return base;
}

function estimateCourseFee(course, studentType) {
  return course.credits * feePerCredit(course.subject_area, course.level, studentType);
}

function estimatePlanFees(semesters, studentType) {
  let total = 0;
  const byYear = {};
  for (const sem of semesters) {
    let semTotal = 0;
    for (const c of sem.courses) {
      semTotal += estimateCourseFee(c, studentType);
    }
    byYear[sem.year] = (byYear[sem.year] || 0) + semTotal;
    total += semTotal;
  }
  return { total: Math.round(total / 10) * 10, byYear };
}

// Legacy single-value estimate for backward compatibility
function formatNZD(n) {
  return 'NZ$' + n.toLocaleString('en-NZ');
}


// ── Student type (domestic / international) ───────────────────────────────────

function setStudentType(type) {
  localStorage.setItem('cm-student-type', type);
  document.getElementById('btn-domestic').classList.toggle('active', type === 'domestic');
  document.getElementById('btn-international').classList.toggle('active', type === 'international');
  const note = document.getElementById('fees-note');
  if (note) {
    note.textContent = type === 'domestic'
      ? 'NZ/AU citizen or permanent resident'
      : 'International student fee rates';
  }
  // Re-render plan if one is loaded to refresh the fee estimate
  if (currentPlan) renderPlan(currentPlan.response || currentPlan);
}

function initStudentType() {
  const saved = localStorage.getItem('cm-student-type') || 'domestic';
  setStudentType(saved);
}

// Fetches the backend's own per-plan fee estimate (POST /api/plan/fees),
// which computes a confidence signal specific to this plan (e.g. what
// fraction of its courses had no subject-specific rate and fell back to
// the flat default) - this was already being computed by
// estimate_plan_fees() in coursemap/domain/fees.py on every request, but
// the UI never called this endpoint at all, so it was never shown.
// Best-effort: the static type label from setStudentType() above already
// gives the user something correct while this is in flight, and this
// silently leaves that label alone if the fetch fails or a newer plan/
// student-type change has superseded this request.
async function updateFeesConfidenceNote(planId, studentType) {
  const note = document.getElementById('fees-note');
  if (!note || !planId) return;
  let feeInfo;
  try {
    const resp = await fetch(`${API}/plan/fees`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({plan_id: planId, student_type: studentType}),
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return;
    feeInfo = await resp.json();
  } catch (e) {
    return;
  }
  // Stale-response guard: if the plan changed (or was regenerated) while
  // this request was in flight, don't overwrite a newer, correct note
  // with a fee estimate for a plan the user is no longer looking at.
  if (lastPlanId !== planId) return;
  const typeLabel = studentType === 'domestic'
    ? 'NZ/AU citizen or permanent resident'
    : 'International student fee rates';
  const excludesTitle = Array.isArray(feeInfo.excludes) ? feeInfo.excludes.join('; ') : '';
  const confidenceLine = feeInfo.confidence
    ? `<br><span title="Excludes: ${excludesTitle}">${feeInfo.confidence}</span>`
    : '';
  note.innerHTML = `${typeLabel}${confidenceLine}`;
}


// ── First-use disclaimer modal ───────────────────────────────────────────────

function showDisclaimerModal() {
  const overlay = document.createElement('div');
  overlay.id = 'disclaimer-modal';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:9999;display:flex;align-items:center;justify-content:center;padding:1rem';
  overlay.innerHTML = `
    <div style="background:var(--bg2);border:1px solid var(--border2);border-radius:14px;max-width:480px;width:100%;padding:2rem;display:flex;flex-direction:column;gap:1rem">
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:24px">⚠️</span>
        <h2 style="font-family:var(--serif);font-size:22px;font-weight:400;letter-spacing:-0.02em">Unofficial tool</h2>
      </div>
      <p style="font-size:14px;color:var(--ink2);line-height:1.6">
        <strong style="color:var(--ink)">coursemap is not affiliated with Massey University.</strong>
        Degree requirements, prerequisites, and course availability in this tool
        may be incomplete or out of date.
      </p>
      <p style="font-size:14px;color:var(--ink2);line-height:1.6">
        <strong style="color:var(--ink)">Always verify your plan</strong> with Massey's official
        <a href="https://www.massey.ac.nz/study/" target="_blank" rel="noopener" style="color:var(--green)">programme information</a>
        and consult your academic advisor before enrolling in any courses.
      </p>
      <p style="font-size:13px;color:var(--ink3);line-height:1.5">
        Fee estimates are rough approximations only. Actual fees vary by subject area and change annually.
        Check <a href="https://www.massey.ac.nz/fees" target="_blank" rel="noopener" style="color:var(--green)">massey.ac.nz/fees</a> for current rates.
      </p>
      <button onclick="document.getElementById('disclaimer-modal').remove();localStorage.setItem('cm-disclaimer-seen','1')"
        style="background:var(--green);color:var(--bg);border:none;border-radius:8px;padding:12px;font-size:14px;font-weight:600;cursor:pointer;font-family:var(--sans);transition:background 0.15s"
        onmouseover="this.style.background='#63cfA0'" onmouseout="this.style.background='var(--green)'">
        I understand, show me the planner
      </button>
    </div>`;
  document.body.appendChild(overlay);
}

// ── Drawer quick-actions ───────────────────────────────────────────────────────

// ── Study load presets ───────────────────────────────────────────────────────

function applyStudyPreset(preset) {
  const credSel = document.getElementById('max-credits');
  const noSumCb = document.getElementById('no-summer');
  if (preset === 'full')  { credSel.value = '60'; noSumCb.checked = true; }
  if (preset === 'part')  { credSel.value = '30'; noSumCb.checked = true; }
  if (preset === 'light') { credSel.value = '15'; noSumCb.checked = true; }
}

function addToCompleted(code) {
  addTag('completed-wrap', code);
  closeDrawer();
  if (currentPlan) {
    toast(`${code} marked done, re-generating plan…`);
    setTimeout(() => generatePlan(), 400);
  } else {
    toast(`${code} added to completed courses.`);
  }
}

function addToExclude(code) {
  addTag('exclude-wrap', code);
  toast(`${code} excluded.`);
  closeDrawer();
}

function addToPrefer(code) {
  addTag('prefer-wrap', code);
  toast(`${code} added to preferred electives.`);
  closeDrawer();
}

