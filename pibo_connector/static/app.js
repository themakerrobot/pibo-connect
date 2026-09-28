/* pibo-connect — 화면. 의존성 0, CDN 0. 오프라인에서 그대로 돈다.
   모양은 sense-lab 의 "학습지" 테마(maker-ui.css) 를 그대로 쓴다. */
'use strict';

const TOKEN = new URLSearchParams(location.search).get('token') || '';
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const ROBOT_HOME = '/home/pi/code';

/* ── 사전 ─────────────────────────────────────────────────────────── */
const EN = {
  title: 'Pibo Connector', up: 'on', selected: 'picked', conn_off: 'offline', conn_on: 'connected',
  stp1: 'Find robots', stp2: 'Pick robots', stp3: 'Get code ready', stp4: 'Run',
  find: 'Find robots', subnet: 'Classroom network', scan: 'Find', refresh: 'Re-check',
  find_note: 'Looks for robots that are on. About 5 seconds.',
  roster: 'Attendance', roster_edit: 'Class list (robot numbers)', save: 'Save',
  roster_note: 'Type the 8-digit number on each robot\'s chest. Any spacing works.',
  list: 'Robots', select_all: 'Pick all', only_up: 'Only on', export: 'Save list', import: 'Load list',
  rules: 'Kind settings', kind: 'Kind', sn: 'Number', name: 'Name', ip: 'Address',
  os: 'Version', temp: 'Temp', status: 'Status', seen: 'Seen',
  empty: 'No robots yet.<br>Press [Find] to look.',
  code: 'Code', mode_new: 'New code', mode_file: 'File inside robot', examples: 'Pick an example…',
  open_file: 'Open my file', path: 'File location', browse: 'Browse', pull: 'Into code box',
  file_note: 'Runs this file on every picked robot, as it is. The code box is not used.',
  run: 'Run!', sync: 'Start together', stop: 'Stop', to_run: 'run', hints: 'Good to know',
  warn_shared: '⚠ Running pauses the robot\'s other features (tools, recognition, AI chat). For AI chat, call Dialog.start_llm first. The robot\'s coding screen (IDE) shows the same output, and pressing Run there stops this code.',
  warn_sync: 'Start together: everyone gets ready first, then one signal starts them all. Put a # --- GO --- line in the code — above is setup, below is the action. If the router blocks the signal it ends in [timeout]; use [Run!] then.',
  output: 'Results', expand_all: 'Expand all', collapse_all: 'Collapse all', clear: 'Clear',
  out_empty: 'After running, each robot\'s last line shows here. Click to see everything.',
  rules_title: 'Robot kind settings',
  rules_note: 'If the robot\'s version name contains this text, it is that kind. Longer text is checked first — <span class="kbd">pibrain</span> before <span class="kbd">pibo</span>.',
  add_rule: '+ Add', cancel: 'Cancel', save_apply: 'Save & sort again',
  browse_title: 'Files inside robot', use_path: 'Use this file',
  browse_note: 'Every picked robot needs this file in the same place. Robots without it show [missing].',
};
let LANG = new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'ko';
const KO = {};
function captureKo() { $$('[data-t]').forEach((el) => { KO[el.dataset.t] = el.innerHTML; }); }
function applyLang() {
  const dict = LANG === 'en' ? EN : KO;
  $$('[data-t]').forEach((el) => { const v = dict[el.dataset.t]; if (v !== undefined) el.innerHTML = v; });
  $('#langToggle').textContent = LANG === 'en' ? '한국어' : 'EN';
  document.documentElement.lang = LANG;
  render(); renderOut();
}
const T = (ko, en) => (LANG === 'en' ? en : ko);
const STATE = {
  pending: ['기다리는 중', 'waiting'], connected: ['연결됨', 'connected'], running: ['실행 중', 'running'],
  preparing: ['준비 중', 'preparing'], ready: ['준비 끝', 'ready'], done: ['끝', 'done'],
  error: ['오류', 'error'], timeout: ['시간 초과', 'timeout'], 'no-ip': ['주소 없음', 'no address'],
  stopped: ['멈춤', 'stopped'], up: ['켜짐', 'on'], ap: ['와이파이 못 붙음', 'no wifi'], offline: ['대답 없음', 'no reply'],
};
const stateLabel = (st) => (STATE[st] ? T(STATE[st][0], STATE[st][1]) : st || '');

/* ── 상태 ─────────────────────────────────────────────────────────── */
let fleet = [], roster = null, selected = new Set(), outputs = {};
let busy = false, jobStart = 0, jobKind = '', jobEverRan = false;
let mode = 'new', sortKey = 'name', sortDesc = false, onlyUp = false;
try {
  sortKey = localStorage.getItem('sortKey') || 'name';
  sortDesc = localStorage.getItem('sortDesc') === '1';
  onlyUp = localStorage.getItem('onlyUp') === '1';
  mode = localStorage.getItem('mode') === 'file' ? 'file' : 'new';
  (JSON.parse(localStorage.getItem('selected') || '[]')).forEach((s) => selected.add(s));
  const rp = localStorage.getItem('rpath'); if (rp) $('#rpath').value = rp;
  const code = localStorage.getItem('code'); if (code) $('#code').value = code;
} catch (e) {}

/* ── API (전부 상대경로 — 하위 경로 배포 대비) ─────────────────────── */
async function api(path, body) {
  const url = path + (TOKEN ? (path.includes('?') ? '&' : '?') + 'token=' + TOKEN : '');
  const opt = { headers: { 'content-type': 'application/json' } };
  if (TOKEN) opt.headers['x-token'] = TOKEN;
  if (body !== undefined) { opt.method = 'POST'; opt.body = JSON.stringify(body); }
  const r = await fetch(url, opt);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { detail: text }; }
  if (!r.ok) throw new Error((data && (data.detail || data.message)) || r.statusText);
  return data;
}

/* ── 토스트: maker-ui 의 #toast 하나를 쓴다. 2초 뒤 사라진다 ────────── */
let toastTimer = null;
function toast(msg, kind = '', ms = 2200) {
  const el = $('#toast');
  el.textContent = msg; el.className = 'toast on ' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, ms);
}
const err = (e) => toast((e && e.message ? e.message : String(e)), 'warn', 5000);

/* ── WebSocket ────────────────────────────────────────────────────── */
let ws = null, wsTimer = null;
function connect() {
  const u = new URL('ws', location.href);
  u.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  if (TOKEN) u.searchParams.set('token', TOKEN);
  ws = new WebSocket(u.href);
  ws.onopen = () => { $('#conn').classList.add('ok'); $('#conn span').textContent = T('연결됨', 'connected'); };
  ws.onclose = () => {
    $('#conn').classList.remove('ok'); $('#conn span').textContent = T('연결 끊김', 'offline');
    clearTimeout(wsTimer); wsTimer = setTimeout(connect, 1500);
  };
  ws.onmessage = (e) => { let m; try { m = JSON.parse(e.data); } catch (_) { return; } handle(m); };
}

function handle(m) {
  switch (m.type) {
    case 'hello':
      $('#ver').textContent = 'v' + m.version;
      if (!$('#subnet').value && m.subnets && m.subnets.length) $('#subnet').value = m.subnets[0];
      fleet = m.fleet || []; roster = m.roster || null; busy = !!m.busy;
      render(); break;
    case 'fleet':
      fleet = m.robots || fleet; if (m.roster) roster = m.roster; render(); break;
    case 'scan':
      if (m.phase === 'found' && m.robot) { upsertLocal(m.robot); render(); }
      else if (m.total) {
        $('#progress').hidden = false;
        const pct = Math.round((m.done / m.total) * 100);
        $('#scan-bar').style.width = pct + '%';
        $('#scan-bar').parentElement.classList.toggle('done', pct >= 100);
        $('#scan-pct').textContent = pct + '%';
        const label = m.phase === 'port' ? T('두드리는 중', 'knocking')
          : m.phase === 'identify' ? T('이름 물어보는 중', 'asking names') : T('다시 확인 중', 're-checking');
        $('#scan-msg').textContent = label + (m.found ? ` · ${m.found}` + T('대', ' found') : '');
      }
      break;
    case 'run':
      outputs[m.sn] = Object.assign(outputs[m.sn] || {}, { state: m.state, tail: m.tail !== undefined ? m.tail : (outputs[m.sn] || {}).tail });
      renderOut(); render(); break;
    case 'output':
      outputs[m.sn] = Object.assign(outputs[m.sn] || {}, { tail: m.tail, len: m.len });
      if ((outputs[m.sn] || {}).open) loadFull(m.sn);
      renderOut(); break;
    case 'job': onJob(m); break;
  }
}

function onJob(m) {
  const jobLabel = { start: T('시작', 'start'), running: T('실행 중', 'running'), preparing: T('준비 중', 'preparing'),
    trigger: T('출발 신호', 'go signal'), stopped: T('멈췄어요', 'stopped') };
  if (m.state === 'start') {
    busy = true; jobEverRan = true; jobStart = Date.now(); jobKind = m.kind || 'run'; outputs = {};
    (m.targets || []).forEach((sn) => { outputs[sn] = { state: 'pending', tail: '' }; });
  }
  if (m.state === 'trigger') {
    const nr = (m.not_ready || []).length;
    toast(T('출발 신호 보냈어요' + (nr ? ` · 준비 안 된 로봇 ${nr}대` : ''),
      'go signal sent' + (nr ? ` · ${nr} not ready` : '')), nr ? 'warn' : 'ok');
  }
  if (m.state === 'end' || m.state === 'stopped') {
    busy = false;
    if (m.state === 'end') {
      const bad = Object.values(m.states || {}).filter((v) => v !== 'done').length;
      $('#run-msg').textContent = T(`끝! ${m.elapsed}초`, `done · ${m.elapsed}s`) + (bad ? T(` · 잘 안 된 로봇 ${bad}대`, ` · ${bad} with issues`) : '');
      toast(bad ? T(`잘 안 된 로봇이 ${bad}대 있어요. 결과를 눌러 봐요`, `done, ${bad} with issues`)
                : T('모두 잘 끝났어요', 'all done'), bad ? 'warn' : 'ok', 3000);
    } else $('#run-msg').textContent = jobLabel.stopped;
  } else if (jobLabel[m.state]) $('#run-msg').textContent = jobLabel[m.state];
  renderStrip(); renderButtons(); renderOut(); renderSteps();
}

function upsertLocal(row) {
  const i = fleet.findIndex((r) => r.sn === row.sn);
  if (i >= 0) fleet[i] = Object.assign({}, fleet[i], row); else fleet.push(row);
}

/* ── 렌더 ─────────────────────────────────────────────────────────── */
const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const isUp = (r) => !!r.ip && r.mode !== 'ap' && r.mode !== 'offline';
const tempNum = (r) => { const m = /(-?\d+(\.\d+)?)/.exec(r.temp || ''); return m ? parseFloat(m[1]) : NaN; };

function rel(ts) {
  if (!ts) return '';
  const t = new Date(ts.replace(' ', 'T')); if (isNaN(t)) return ts;
  const s = Math.round((Date.now() - t) / 1000);
  if (s < 60) return T('방금', 'just now');
  if (s < 3600) return T(`${Math.floor(s / 60)}분 전`, `${Math.floor(s / 60)}m ago`);
  if (s < 86400) return T(`${Math.floor(s / 3600)}시간 전`, `${Math.floor(s / 3600)}h ago`);
  return ts.slice(5, 16);
}

function kindBadge(r) {
  const k = r.kind || 'unknown';
  const label = k === 'pibo' ? 'Pibo' : k === 'pibrain' ? 'PiBrain' : '?';
  const low = r.kind_confidence !== 'high' ? ' low' : '';
  const ev = esc(r.kind_evidence || '') + (low ? T(' — 확실하지 않아요', ' — needs checking') : '');
  return `<span class="badge kind ${k}${low}" title="${ev}">${label}</span>`;
}

function stateOf(r) {
  if (r.mode === 'ap') return ['ap', stateLabel('ap')];
  if (r.mode === 'offline') return ['offline', stateLabel('offline')];
  if (!r.ip) return ['offline', '—'];
  const st = (outputs[r.sn] || {}).state;
  if (st && busy) return [st, stateLabel(st)];
  if (st === 'done' || st === 'error' || st === 'timeout') return [st, stateLabel(st)];
  return ['up', stateLabel('up')];
}

function sortedFleet() {
  const rows = fleet.filter((r) => !onlyUp || isUp(r));
  const kindOrder = { pibo: 0, pibrain: 1, unknown: 2 };
  const key = (r) => {
    switch (sortKey) {
      case 'kind': return kindOrder[r.kind] ?? 3;
      case 'ip': return (r.ip || '999.999.999.999').split('.').map((n) => n.padStart(3, '0')).join('.');
      case 'temp': { const t = tempNum(r); return isNaN(t) ? -1 : t; }
      case 'mode': return isUp(r) ? 0 : r.mode === 'ap' ? 1 : 2;
      case 'last_seen': return r.last_seen || '';
      case 'name': return (r.name || '￿') + (r.sn || '');
      default: return r[sortKey] || '';
    }
  };
  rows.sort((a, b) => { const x = key(a), y = key(b); return (x < y ? -1 : x > y ? 1 : 0) * (sortDesc ? -1 : 1); });
  return rows;
}

function render() {
  const rows = sortedFleet();
  $('#tbody').innerHTML = rows.map((r) => {
    const [stc, stl] = stateOf(r);
    const t = tempNum(r);
    const sel = selected.has(r.sn);
    return `<tr class="${isUp(r) ? '' : 'off'} ${sel ? 'sel' : ''}" data-sn="${r.sn}">
      <td class="pick"><input type="checkbox" class="pick" data-sn="${r.sn}" ${sel ? 'checked' : ''} ${isUp(r) ? '' : 'disabled'}></td>
      <td>${kindBadge(r)}</td>
      <td class="mono">${r.sn}</td>
      <td><input class="name-edit" data-sn="${r.sn}" value="${esc(r.name)}" placeholder="${T('이름', 'name')}" maxlength="24"></td>
      <td class="mono">${r.ip || '—'}</td>
      <td class="mono hide-m" title="${esc(r.kind_evidence)}">${esc(r.os) || '—'}</td>
      <td class="mono hide-m"><span class="temp ${!isNaN(t) && t >= 70 ? 'hot' : ''}">${esc(r.temp) || '—'}</span></td>
      <td><span class="state ${stc}">${stl}</span></td>
      <td class="hide-m" title="${esc(r.last_seen)}">${rel(r.last_seen)}</td>
      <td class="del"><button class="db x" data-sn="${r.sn}" title="${T('목록에서 지우기', 'remove')}">×</button></td>
    </tr>`;
  }).join('');
  $('#empty').style.display = fleet.length ? 'none' : '';
  $('#fleet').style.display = fleet.length ? '' : 'none';
  $$('th[data-sort]').forEach((th) => {
    th.classList.toggle('sorted', th.dataset.sort === sortKey);
    th.classList.toggle('desc', th.dataset.sort === sortKey && sortDesc);
  });
  const ups = fleet.filter(isUp).map((r) => r.sn);
  $('#chk-all').checked = ups.length > 0 && ups.every((s) => selected.has(s));
  $('#chk-all').indeterminate = ups.some((s) => selected.has(s)) && !$('#chk-all').checked;
  renderStrip(); renderRoster(); renderButtons(); renderBrowseRobots(); renderSteps();
}

function renderStrip() {
  $('#st-up b').textContent = fleet.filter(isUp).length;
  $('#st-sel b').textContent = selected.size;
  const j = $('#st-job');
  if (busy) {
    j.hidden = false;
    const kind = { run: T('실행 중', 'running'), run_path: T('파일 실행 중', 'running file'), sync: T('다 같이 시작', 'sync run') }[jobKind] || jobKind;
    j.textContent = `${kind} · ${Math.floor((Date.now() - jobStart) / 1000)}s`;
  } else j.hidden = true;
}
setInterval(() => { if (busy) { renderStrip(); $$('.out .item .el').forEach((el) => { el.textContent = Math.floor((Date.now() - jobStart) / 1000) + 's'; }); } }, 1000);

/* 단계 표시: 1 찾기 → 2 고르기 → 3 코드 → 4 실행 */
function renderSteps() {
  const hasRobots = fleet.some(isUp);
  const hasPick = targets().length > 0;
  const hasCode = mode === 'file' ? /\S\/?[^/]+$/.test($('#rpath').value.trim()) && !$('#rpath').value.trim().endsWith('/') : $('#code').value.trim().length > 0;
  const st = [hasRobots, hasPick, hasCode, jobEverRan];
  let cur = st.findIndex((v) => !v); if (cur < 0) cur = 3;
  if (busy) cur = 3;
  st.forEach((done, i) => {
    const el = $('#stp' + (i + 1));
    el.classList.toggle('done', done && i !== cur);
    el.classList.toggle('on', i === cur);
  });
}

function renderRoster() {
  const sum = $('#roster-sum'), chips = $('#roster-chips');
  if (!roster || !roster.expected) {
    sum.innerHTML = `<span class="hint top0">${T('아래 출석부에 우리 반 로봇 번호를 적으면 누가 왔는지 알 수 있어요.', 'Add the class list below to see who is here.')}</span>`;
    chips.innerHTML = ''; return;
  }
  const up = roster.present || [], ap = roster.ap || [], miss = roster.missing || [], extra = roster.extra || [];
  sum.innerHTML =
    `<span class="ok"><b>${up.length}</b>/ ${roster.expected} ${T('왔어요', 'here')}</span>` +
    `<span class="${miss.length ? 'warn' : ''}"><b>${miss.length}</b>${T('안 보여요', 'missing')}</span>`;
  const nm = (sn) => { const r = fleet.find((x) => x.sn === sn); return r && r.name ? `${r.name} ` : ''; };
  chips.innerHTML =
    up.map((s) => `<span class="chip up" title="${T('왔어요', 'here')}">${nm(s)}${s}</span>`).join('') +
    ap.map((s) => `<span class="chip ap" title="${T('와이파이 못 붙음', 'no wifi')}">${nm(s)}${s}</span>`).join('') +
    miss.map((s) => `<span class="chip missing" title="${T('안 보여요', 'missing')}">${nm(s)}${s}</span>`).join('') +
    extra.map((s) => `<span class="chip extra" title="${T('출석부에 없는 로봇', 'not in list')}">${nm(s)}${s}</span>`).join('');
}

function renderButtons() {
  const has = targets().length > 0;
  $('#btn-run').disabled = busy || !has;
  $('#btn-sync').disabled = busy || !has;
  $('#btn-scan').disabled = busy; $('#btn-refresh').disabled = busy;
  $('#btn-browse').disabled = !has; $('#btn-pull').disabled = !has;
  $('#btn-run').textContent = mode === 'file' ? T('파일 실행!', 'Run file') : T('실행!', 'Run!');
}

function renderOut() {
  const sns = Object.keys(outputs);
  $('#out-empty').style.display = sns.length ? 'none' : '';
  const anyOpen = sns.some((s) => outputs[s].open);
  $('#btn-expand').textContent = anyOpen ? T('모두 접기', 'Collapse all') : T('모두 펼치기', 'Expand all');
  $('#out').innerHTML = sns.map((sn) => {
    const o = outputs[sn] || {}, r = fleet.find((x) => x.sn === sn) || {};
    const who = r.name ? `${esc(r.name)} <span class="mono">${sn}</span>` : `<span class="mono">${sn}</span>`;
    const el = busy && !['done', 'error', 'timeout', 'no-ip'].includes(o.state) ? `<span class="el">${Math.floor((Date.now() - jobStart) / 1000)}s</span>` : '';
    return `<div class="item ${o.state || ''}" data-sn="${sn}">
      <div class="h"><span class="who">${who}</span><span class="state ${o.state || ''}">${stateLabel(o.state)}</span><span class="ip">${r.ip || ''}</span>${el}</div>
      <div class="tail">${esc(o.tail || '')}</div>
      ${o.open ? `<pre>${esc(o.full == null ? T('불러오는 중…', 'loading…') : o.full || T('(아무것도 안 나왔어요)', '(no output)'))}</pre>` : ''}
    </div>`;
  }).join('');
}

async function loadFull(sn) {
  try { const d = await api(`api/output/${sn}`); outputs[sn] = Object.assign(outputs[sn] || {}, { full: d.record || '' }); renderOut(); }
  catch (e) { /* 실행 전이면 없을 수 있다 */ }
}

/* ── 선택 ─────────────────────────────────────────────────────────── */
function saveSel() { try { localStorage.setItem('selected', JSON.stringify(Array.from(selected))); } catch (e) {} }
const targets = () => Array.from(selected).filter((sn) => { const r = fleet.find((x) => x.sn === sn); return r && isUp(r); });
const firstTarget = () => targets()[0];

$('#chk-all').onchange = (e) => { selected = new Set(e.target.checked ? fleet.filter(isUp).map((r) => r.sn) : []); saveSel(); render(); };
$('#only-up').checked = onlyUp;
$('#only-up').onchange = (e) => { onlyUp = e.target.checked; try { localStorage.setItem('onlyUp', onlyUp ? '1' : '0'); } catch (_) {} render(); };
$('#fleet thead').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-sort]'); if (!th) return;
  if (sortKey === th.dataset.sort) sortDesc = !sortDesc; else { sortKey = th.dataset.sort; sortDesc = false; }
  try { localStorage.setItem('sortKey', sortKey); localStorage.setItem('sortDesc', sortDesc ? '1' : '0'); } catch (_) {}
  render();
});
$('#tbody').addEventListener('change', (e) => {
  if (!e.target.classList.contains('pick')) return;
  if (e.target.checked) selected.add(e.target.dataset.sn); else selected.delete(e.target.dataset.sn);
  saveSel(); render();
});
$('#tbody').addEventListener('click', (e) => {
  if (e.target.closest('input, button, a')) return;        // 행 아무 데나 눌러도 선택
  const tr = e.target.closest('tr[data-sn]'); if (!tr) return;
  const r = fleet.find((x) => x.sn === tr.dataset.sn); if (!r || !isUp(r)) return;
  if (selected.has(r.sn)) selected.delete(r.sn); else selected.add(r.sn);
  saveSel(); render();
});
$('#tbody').addEventListener('blur', async (e) => {
  if (!e.target.classList.contains('name-edit')) return;
  const sn = e.target.dataset.sn, r = fleet.find((x) => x.sn === sn);
  if (r && (r.name || '') === e.target.value) return;
  try { await api('api/rename', { sn, name: e.target.value }); } catch (ex) { err(ex); }
}, true);
$('#tbody').addEventListener('keydown', (e) => {
  if (e.target.classList.contains('name-edit') && (e.key === 'Enter' || e.key === 'Escape')) e.target.blur();
});
$('#tbody').addEventListener('click', async (e) => {
  const b = e.target.closest('button.x'); if (!b) return;
  const sn = b.dataset.sn;
  if (!confirm(T(`${sn} 로봇을 목록에서 지울까요?`, `Remove ${sn} from the list?`))) return;
  try { await api('api/remove', { sn }); selected.delete(sn); saveSel(); } catch (ex) { err(ex); }
});

/* ── 찾기 ─────────────────────────────────────────────────────────── */
async function guard(fn) { try { await fn(); } catch (e) { err(e); } }
function progressStart(msg) {
  $('#progress').hidden = false; $('#scan-bar').style.width = '0'; $('#scan-pct').textContent = '';
  $('#scan-bar').parentElement.classList.remove('done'); $('#scan-msg').textContent = msg;
}
function progressEnd(msg) {
  $('#scan-bar').style.width = '100%'; $('#scan-bar').parentElement.classList.add('done');
  $('#scan-pct').textContent = ''; $('#scan-msg').textContent = msg;
}

$('#btn-scan').onclick = () => guard(async () => {
  progressStart(T('찾는 중…', 'looking…'));
  const d = await api('api/scan', { subnet: $('#subnet').value.trim() });
  progressEnd(T(`${d.found}대 찾았어요`, `${d.found} found`));
  toast(d.found ? T(`로봇 ${d.found}대를 찾았어요`, `${d.found} robots found`)
    : T('로봇을 못 찾았어요. 켜져 있고 같은 와이파이인지 봐요', 'No robots found. Check power and wifi'), d.found ? 'ok' : 'warn', d.found ? 2200 : 5000);
});
$('#btn-refresh').onclick = () => guard(async () => {
  progressStart(T('다시 확인 중…', 're-checking…'));
  const d = await api('api/refresh', {});
  const msg = T(`${d.ok.length}대 그대로` + (d.lost.length ? `, ${d.lost.length}대 대답 없음` : ''),
    `${d.ok.length} same` + (d.lost.length ? `, ${d.lost.length} not replying` : ''));
  progressEnd(msg); toast(msg, d.lost.length ? 'warn' : 'ok');
});
$('#btn-roster').onclick = () => guard(async () => {
  const d = await api('api/roster', { sns: $('#roster-text').value });
  roster = d.status; renderRoster();
  toast(T(`출석부에 ${d.roster.length}대 적었어요`, `saved ${d.roster.length} in class list`), 'ok');
});

/* ── 코드 ─────────────────────────────────────────────────────────── */
function setMode(m) {
  mode = m; try { localStorage.setItem('mode', m); } catch (e) {}
  $$('#mode button').forEach((b) => b.classList.toggle('on', b.dataset.mode === m));
  $('.code-sec').classList.toggle('mode-file', m === 'file');
  $('#filebar').hidden = m !== 'file';
  renderButtons(); renderSteps();
}
$('#mode').addEventListener('click', (e) => { const b = e.target.closest('button[data-mode]'); if (b) setMode(b.dataset.mode); });
$('#rpath').addEventListener('input', () => { try { localStorage.setItem('rpath', $('#rpath').value); } catch (e) {} renderSteps(); });
$('#code').addEventListener('input', () => { try { localStorage.setItem('code', $('#code').value); } catch (e) {} renderSteps(); });
$('#code').addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault(); const ta = e.target, s = ta.selectionStart, en = ta.selectionEnd;
    ta.value = ta.value.slice(0, s) + '    ' + ta.value.slice(en); ta.selectionStart = ta.selectionEnd = s + 4;
  }
});
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !$('#btn-run').disabled) { e.preventDefault(); $('#btn-run').click(); }
});
$('#file').onchange = (e) => {
  const f = e.target.files[0]; if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { $('#code').value = rd.result; if (f.name.endsWith('.sh')) $('#codetype').value = 'shell'; $('#code').dispatchEvent(new Event('input')); };
  rd.readAsText(f, 'utf-8'); e.target.value = '';
};
async function loadExamples() {
  try {
    const d = await api('api/examples');
    const sel = $('#examples');
    (d.examples || []).forEach((ex, i) => { const o = document.createElement('option'); o.value = String(i); o.textContent = ex.title; sel.appendChild(o); });
    sel.onchange = () => {
      const ex = (d.examples || [])[+sel.value]; if (!ex) return;
      $('#code').value = ex.code; $('#codetype').value = ex.codetype; $('#code').dispatchEvent(new Event('input'));
      sel.value = ''; toast(T(`예제를 넣었어요: ${ex.name}`, `example loaded: ${ex.name}`), 'ok');
    };
  } catch (e) { /* 예제가 없어도 된다 */ }
}

/* ── 실행 ─────────────────────────────────────────────────────────── */
const needPath = () => {
  const p = $('#rpath').value.trim();
  if (!p || p.endsWith('/')) throw new Error(T('파일 위치를 적어 주세요 (예: /home/pi/code/main.py)', 'enter a file path'));
  return p;
};
$('#btn-run').onclick = () => guard(async () => {
  const tg = targets(); if (!tg.length) return;
  $('#run-msg').textContent = T('보내는 중…', 'sending…');
  if (mode === 'file') await api('api/run_path', { targets: tg, path: needPath() });
  else await api('api/run', { targets: tg, code: $('#code').value, codetype: $('#codetype').value });
});
$('#btn-sync').onclick = () => guard(async () => {
  const tg = targets(); if (!tg.length) return;
  let code = $('#code').value;
  if (mode === 'file') {
    // 로봇의 파일을 다 같이 시작하려면 내용을 알아야 GO 래퍼로 감쌀 수 있다. 첫 로봇에서 읽어온다.
    const d = await api('api/load', { sn: firstTarget(), path: needPath() });
    if (d.codetype === 'shell') throw new Error(T('다 같이 시작은 파이썬 파일만 돼요', 'sync run is Python only'));
    code = d.code;
    toast(T(`${firstTarget()} 로봇의 파일을 읽어서 다 같이 시작해요`, `read from ${firstTarget()} for sync run`), '', 3000);
  }
  $('#run-msg').textContent = T('준비 중…', 'preparing…');
  await api('api/sync', { targets: tg, code });
});
$('#btn-stop').onclick = () => guard(async () => { await api('api/stop', { targets: targets() }); busy = false; renderButtons(); renderStrip(); });
$('#btn-pull').onclick = () => guard(async () => {
  const sn = firstTarget(); if (!sn) return;
  const d = await api('api/load', { sn, path: needPath() });
  $('#code').value = d.code; $('#codetype').value = d.codetype; $('#code').dispatchEvent(new Event('input'));
  setMode('new');
  toast(T(`${sn} 로봇의 파일을 코드 창에 넣었어요`, `pulled from ${sn}`), 'ok');
});

/* ── 결과 ─────────────────────────────────────────────────────────── */
$('#out').addEventListener('click', (e) => {
  const item = e.target.closest('.item'); if (!item) return;
  const o = outputs[item.dataset.sn] = outputs[item.dataset.sn] || {};
  o.open = !o.open; if (o.open && o.full == null) loadFull(item.dataset.sn); renderOut();
});
$('#btn-expand').onclick = () => {
  const sns = Object.keys(outputs), open = !sns.some((s) => outputs[s].open);
  sns.forEach((s) => { outputs[s].open = open; if (open && outputs[s].full == null) loadFull(s); }); renderOut();
};
$('#btn-clear').onclick = () => { if (!busy) { outputs = {}; $('#run-msg').textContent = ''; renderOut(); render(); } };

/* ── 목록 저장 / 불러오기 ─────────────────────────────────────────── */
$('#btn-export').onclick = () => guard(async () => {
  const d = await api('api/export');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(d, null, 1)], { type: 'application/json' }));
  a.download = `pibo-fleet-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href);
});
$('#btn-import').onclick = () => {
  const inp = document.createElement('input'); inp.type = 'file'; inp.accept = '.json';
  inp.onchange = () => {
    const f = inp.files[0]; if (!f) return;
    const rd = new FileReader();
    rd.onload = () => guard(async () => {
      const d = await api('api/import', { payload: JSON.parse(rd.result), merge: true });
      toast(T(`로봇 ${d.imported}대를 불러왔어요`, `${d.imported} imported`), 'ok');
    });
    rd.readAsText(f, 'utf-8');
  };
  inp.click();
};

/* ── 종류 구분 설정 ───────────────────────────────────────────────── */
let rulesAll = null;
function ruleRow(frag = '', kind = 'pibo') {
  const div = document.createElement('div'); div.className = 'rule';
  div.innerHTML = `<input class="inp" type="text" value="${esc(frag)}" placeholder="${T('버전 이름에 들어가는 글자', 'fragment')}" spellcheck="false">
    <select class="inp"><option value="pibo" ${kind === 'pibo' ? 'selected' : ''}>Pibo</option><option value="pibrain" ${kind === 'pibrain' ? 'selected' : ''}>PiBrain</option></select>
    <button class="db x" title="${T('지우기', 'remove')}">×</button>`;
  div.querySelector('.x').onclick = () => div.remove();
  return div;
}
$('#btn-rules').onclick = () => guard(async () => {
  const d = await api('api/rules'); rulesAll = d.rules;
  const box = $('#rules-rows'); box.innerHTML = '';
  Object.entries(d.rules.os_contains || {}).sort((a, b) => b[0].length - a[0].length).forEach(([f, k]) => box.appendChild(ruleRow(f, k)));
  $('#rules-path').textContent = d.path || '';
  $('#rules-modal').hidden = false;
});
$('#rules-add').onclick = () => { $('#rules-rows').appendChild(ruleRow('', 'pibo')); $('#rules-rows').lastChild.querySelector('input').focus(); };
$('#rules-cancel').onclick = () => { $('#rules-modal').hidden = true; };
$('#rules-save').onclick = () => guard(async () => {
  const os_contains = {};
  $$('#rules-rows .rule').forEach((r) => { const f = r.querySelector('input').value.trim().toLowerCase(); if (f) os_contains[f] = r.querySelector('select').value; });
  if (!Object.keys(os_contains).length) throw new Error(T('글자를 하나는 넣어야 해요', 'add at least one'));
  await api('api/rules', { rules: Object.assign({}, rulesAll || {}, { os_contains }) });
  $('#rules-modal').hidden = true; toast(T('저장했어요. 종류를 다시 나눴어요', 'saved · sorted again'), 'ok');
});

/* ── 로봇 안의 파일 찾아보기 ──────────────────────────────────────── */
let bPath = ROBOT_HOME, bPick = '';
const ICON_DIR = '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
const ICON_FILE = '<svg viewBox="0 0 24 24"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/></svg>';
const ICON_UP = '<svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';

function renderBrowseRobots() {
  const sel = $('#browse-robot'), cur = sel.value, ups = fleet.filter(isUp);
  sel.innerHTML = ups.map((r) => `<option value="${r.sn}">${esc(r.name ? `${r.name} · ${r.sn}` : r.sn)} — ${r.ip}</option>`).join('');
  if (cur && ups.some((r) => r.sn === cur)) sel.value = cur; else if (firstTarget()) sel.value = firstTarget();
}
async function browse(path) {
  const sn = $('#browse-robot').value; if (!sn) return;
  const list = $('#browse-list'); list.innerHTML = `<div class="msg">${T('불러오는 중…', 'loading…')}</div>`;
  bPick = ''; $('#browse-pick').disabled = true;
  try {
    const d = await api('api/browse', { sn, path });
    bPath = d.path || path;
    const parts = bPath.split('/').filter(Boolean);
    $('#browse-path').innerHTML = '<a data-p="/">/</a>' + parts.map((p, i) => `<a data-p="/${parts.slice(0, i + 1).join('/')}">${esc(p)}</a>/`).join('');
    const ents = d.entries || [];
    list.innerHTML = (bPath !== '/' ? `<div class="ent folder" data-up="1">${ICON_UP}<span>..</span></div>` : '') +
      ents.map((e) => `<div class="ent ${e.type} ${e.protect ? 'protect' : ''}" data-name="${esc(e.name)}" data-type="${e.type}">
        ${e.type === 'folder' ? ICON_DIR : ICON_FILE}<span>${esc(e.name)}</span>${e.protect ? `<span class="tag">${T('보호됨', 'protected')}</span>` : ''}</div>`).join('') ||
      `<div class="msg">${T('빈 폴더예요', 'empty folder')}</div>`;
  } catch (e) { list.innerHTML = `<div class="msg warn">${esc(e.message)}</div>`; }
}
$('#btn-browse').onclick = () => {
  renderBrowseRobots(); $('#browse-modal').hidden = false;
  const cur = $('#rpath').value.trim();
  browse(cur && cur.startsWith('/') ? cur.replace(/\/[^/]*$/, '') || '/' : ROBOT_HOME);
};
$('#browse-robot').onchange = () => browse(bPath);
$('#browse-path').addEventListener('click', (e) => { const a = e.target.closest('a[data-p]'); if (a) browse(a.dataset.p); });
$('#browse-list').addEventListener('click', (e) => {
  const ent = e.target.closest('.ent'); if (!ent) return;
  if (ent.dataset.up) return browse(bPath.replace(/\/[^/]*$/, '') || '/');
  const full = (bPath === '/' ? '' : bPath) + '/' + ent.dataset.name;
  if (ent.dataset.type === 'folder') return browse(full);
  $$('#browse-list .ent').forEach((x) => x.classList.remove('sel')); ent.classList.add('sel');
  bPick = full; $('#browse-pick').disabled = false;
});
$('#browse-list').addEventListener('dblclick', (e) => { const ent = e.target.closest('.ent.file'); if (ent && bPick) $('#browse-pick').click(); });
$('#browse-pick').onclick = () => { if (!bPick) return; $('#rpath').value = bPick; $('#rpath').dispatchEvent(new Event('input')); $('#browse-modal').hidden = true; };
$('#browse-cancel').onclick = () => { $('#browse-modal').hidden = true; };
$$('.modal').forEach((m) => m.addEventListener('click', (e) => { if (e.target === m) m.hidden = true; }));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $$('.modal').forEach((m) => { m.hidden = true; }); });

/* ── 한/영 ────────────────────────────────────────────────────────── */
$('#langToggle').onclick = () => {
  LANG = LANG === 'en' ? 'ko' : 'en';
  const u = new URL(location.href); if (LANG === 'en') u.searchParams.set('lang', 'en'); else u.searchParams.delete('lang');
  history.replaceState(null, '', u); applyLang();
};

/* ── 시작 ─────────────────────────────────────────────────────────── */
captureKo(); applyLang(); setMode(mode); connect(); loadExamples();
api('api/fleet').then((d) => {
  fleet = d.robots || []; roster = d.roster;
  $('#roster-text').value = (d.roster_list || []).join(' ');
  selected = new Set(Array.from(selected).filter((s) => fleet.some((r) => r.sn === s)));   // 사라진 로봇은 선택에서 뺀다
  render();
}).catch(() => {});
setInterval(() => { if (ws && ws.readyState === 1) ws.send('ping'); }, 20000);
