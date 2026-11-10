"""``report.html`` for a ``spindoctor test`` run folder.

One self-contained page (no network, no files besides the run folder's own
screenshots and logs): summary cards, HyperSpin's startup, a tile per game
with its screenshot, filters and search, a per-wheel table and the games
that were skipped.  Rewritten from ``run.json`` and ``results.csv`` whenever
``results.json`` is, so it is always current, also after ``--recover``.
"""
from __future__ import annotations

import json
from pathlib import Path

from ._utils import atomic_write_bytes


def write_report(run_dir: Path, data: dict) -> Path:
    """Write ``report.html`` for *data* (``{"run": run.json, "results": rows}``)."""
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = _TEMPLATE.replace("/*DATA*/", payload)
    path = run_dir / "report.html"
    atomic_write_bytes(path, html.encode("utf-8"))
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Game Test Report</title>
<style>
:root { --bg:#f5f6f8; --card:#fff; --text:#1b1e23; --muted:#5d6570; --line:#e1e4e9; --accent:#2f5bd3;
  --pass:#1d7f46; --warn:#a85f00; --fail:#c22a2a; --skip:#5d6570;
  --passbg:#e6f4eb; --warnbg:#fdf1de; --failbg:#fbe9e9; --skipbg:#eceef1; }
@media (prefers-color-scheme: dark) { :root { --bg:#131519; --card:#1c1f25; --text:#e6e8eb; --muted:#9aa1ab;
  --line:#2b2f37; --accent:#86a6ff; --pass:#52c483; --warn:#f0a63c; --fail:#f07070; --skip:#9aa1ab;
  --passbg:#16301f; --warnbg:#382912; --failbg:#3b1a1a; --skipbg:#262a31; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 "Segoe UI", system-ui, sans-serif; }
main { max-width:1240px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:24px; margin:0 0 4px; }
h2 { font-size:18px; margin:34px 0 10px; }
a { color:var(--accent); }
.muted { color:var(--muted); }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:10px; margin-top:18px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
.card .n { font-size:26px; font-weight:600; }
.pass { color:var(--pass); } .warn { color:var(--warn); } .fail { color:var(--fail); }
.badge { display:inline-block; padding:1px 8px; border-radius:10px; font-size:12px; font-weight:600; white-space:nowrap; }
.badge.PASS { background:var(--passbg); color:var(--pass); }
.badge.WARN { background:var(--warnbg); color:var(--warn); }
.badge.FAIL { background:var(--failbg); color:var(--fail); }
.badge.SKIPPED { background:var(--skipbg); color:var(--skip); }
.box { display:flex; gap:16px; flex-wrap:wrap; background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px; }
.box img { width:320px; max-width:100%; border-radius:4px; background:#000; }
.box ul { margin:8px 0 0; padding-left:18px; font:12px/1.5 Consolas, monospace; }
.toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 12px; }
.toolbar input { padding:6px 10px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--text);
  min-width:200px; flex:1; max-width:360px; }
button { padding:6px 12px; border:1px solid var(--line); border-radius:6px; background:var(--card); color:var(--text); cursor:pointer; font:inherit; }
button.on { border-color:var(--accent); color:var(--accent); font-weight:600; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(230px, 1fr)); gap:12px; }
.tile { background:var(--card); border:1px solid var(--line); border-top:4px solid var(--line); border-radius:8px; overflow:hidden; cursor:pointer; }
.tile.PASS { border-top-color:var(--pass); } .tile.WARN { border-top-color:var(--warn); } .tile.FAIL { border-top-color:var(--fail); }
.tile img, .tile .noimg { display:block; width:100%; aspect-ratio:16/9; object-fit:cover; background:#000; }
.tile .noimg { display:flex; align-items:center; justify-content:center; color:#8a8f96; font-size:12px; }
.tile .body { padding:8px 10px 10px; }
.tile .game { font-weight:600; overflow-wrap:anywhere; }
.tile .sub { font-size:12px; color:var(--muted); margin-top:2px; }
.tile .reason, .tile .doctor { font-size:12px; margin-top:6px; overflow-wrap:anywhere; }
.tile .doctor { color:var(--warn); }
.wrap { overflow-x:auto; border:1px solid var(--line); border-radius:8px; }
table { width:100%; border-collapse:collapse; background:var(--card); }
th, td { text-align:left; padding:7px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { font-size:12px; font-weight:600; color:var(--muted); white-space:nowrap; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
td.notes { font-size:12px; color:var(--muted); min-width:240px; overflow-wrap:anywhere; }
tr:last-child td { border-bottom:0; }
.modal { position:fixed; inset:0; background:rgba(0,0,0,.6); display:flex; align-items:center; justify-content:center; padding:16px; z-index:10; }
.modal[hidden] { display:none; }
.panel { background:var(--card); border-radius:10px; max-width:900px; width:100%; max-height:92vh; overflow:auto; padding:16px; }
.panel img { width:100%; border-radius:6px; background:#000; }
.panel pre { white-space:pre-wrap; font:12px/1.5 Consolas, monospace; background:var(--bg); padding:10px; border-radius:6px; }
.panel .top { display:flex; justify-content:space-between; gap:12px; align-items:start; }
</style>
</head>
<body>
<main>
  <h1>Game Test Report</h1>
  <div id="meta" class="muted"></div>
  <div id="cards" class="cards"></div>
  <div id="hs"></div>
  <div id="cleanup"></div>
  <h2>Launch results</h2>
  <div class="toolbar" id="filters">
    <button data-f="all" class="on">All</button>
    <button data-f="FAIL">Failed</button>
    <button data-f="WARN">Warnings</button>
    <button data-f="PASS">Passed</button>
    <button data-f="DOCTOR">doctor notes</button>
    <input id="q" type="search" placeholder="Search games, systems or reasons">
  </div>
  <div id="grid" class="grid"></div>
  <button id="more" hidden></button>
  <h2>Systems</h2>
  <div class="wrap"><table id="systems"></table></div>
  <div id="skippedSection">
    <h2>Skipped games</h2>
    <p class="muted">These games weren't launched: RocketLauncher can't launch them as set up, or a skip rule left them out.</p>
    <div class="wrap"><table id="skipped"></table></div>
  </div>
</main>
<div id="modal" class="modal" hidden><div class="panel" id="panel"></div></div>
<script>const DATA = /*DATA*/;</script>
<script>
(function () {
  const $ = id => document.getElementById(id);
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const enc = p => p.split('/').map(encodeURIComponent).join('/');
  const LABEL = { PASS: 'Passed', WARN: 'Warning', FAIL: 'Failed', SKIPPED: 'Skipped' };
  const run = DATA.run || {}, ALL = DATA.results || [];
  const L = ALL.filter(r => r.Status !== 'SKIPPED'), S = ALL.filter(r => r.Status === 'SKIPPED');
  L.forEach((r, i) => { r.i = i; });

  const meta = ['started ' + esc(run.started || '')];
  if (run.ended) meta.push('ended ' + esc(run.ended));
  meta.push(L.length + ' games launched, ' + esc(run.seconds) + ' seconds each');
  if (!run.finished) meta.push('<b>not finished</b>: <code>spindoctor test --resume --apply</code> carries on');
  if (run.interrupted) meta.push('the run was interrupted and recovered');
  $('meta').innerHTML = meta.join(' &middot; ');

  const tot = { PASS: 0, WARN: 0, FAIL: 0 };
  L.forEach(r => { tot[r.Status] = (tot[r.Status] || 0) + 1; });
  const noted = ALL.filter(r => r.Doctor).length;
  const cards = [['Games launched', L.length, ''], ['Passed', tot.PASS, 'pass'], ['Warnings', tot.WARN, tot.WARN ? 'warn' : ''],
    ['Failed', tot.FAIL, tot.FAIL ? 'fail' : 'pass'], ['Skipped', S.length, ''], ['With doctor notes', noted, noted ? 'warn' : '']];
  const cl = run.cleanup;
  if (cl) cards.push(cl.mode === 'remove' ? ['New files removed', cl.removed, ''] : ['New files the games made', cl.found, cl.found ? 'warn' : '']);
  $('cards').innerHTML = cards.map(c => `<div class="card"><div class="n ${c[2]}">${Number(c[1] || 0).toLocaleString()}</div><div class="muted">${c[0]}</div></div>`).join('');

  const hs = run.hyperspin;
  if (hs) {
    const det = (hs.details || []).length ? `<ul>${hs.details.map(d => `<li>${esc(d)}</li>`).join('')}</ul>` : '';
    $('hs').innerHTML = `<h2>HyperSpin startup</h2><div class="box">${hs.screenshot ? `<img src="${enc(hs.screenshot)}" alt="HyperSpin screenshot">` : ''}<div><span class="badge ${hs.status}">${LABEL[hs.status]}</span> ${esc(hs.reason)}${det}</div></div>`;
  }
  if (cl) {
    $('cleanup').innerHTML = `<h2>Files the games created</h2><div class="box"><div>` +
      (!cl.found ? 'The games created no new files.'
        : (cl.mode === 'remove'
          ? `${cl.removed} new file(s) and folder(s) were removed, each file backed up first to <b>${esc(cl.backup_dir)}</b>.`
          : `${cl.found} new file(s) and folder(s) were left in place (<code>test_cleanup = report</code>; <code>--cleanup remove</code> backs them up and deletes them).`)
          + ' The full list is in cleanup.csv next to this report.') +
      (cl.left ? `<p class="fail">${cl.left} could not be removed (see cleanup.csv).</p>` : '') +
      (cl.baseline ? `<p class="muted">${Number(cl.baseline).toLocaleString()} items existed in ${(cl.roots || []).map(esc).join(', ')} when the run started; none of them can be touched.</p>` : '') +
      ((cl.unreadable || []).length ? `<p class="warn">Folders that couldn't be read were protected whole: ${cl.unreadable.map(esc).join(', ')}</p>` : '') +
      ((cl.skipped || []).length ? `<p class="muted">Left alone on purpose: ${cl.skipped.map(esc).join(', ')}.</p>` : '') +
      `</div></div>`;
  }

  let filter = 'all', query = '', limit = 240;
  const ORDER = { FAIL: 0, WARN: 1, PASS: 2 };
  function drawGrid() {
    const rows = L.filter(r => (filter === 'all' || r.Status === filter || (filter === 'DOCTOR' && r.Doctor)) &&
      (!query || (r.Game + ' ' + r.System + ' ' + r.Reason + ' ' + (r.Doctor || '')).toLowerCase().includes(query)));
    rows.sort((a, b) => (ORDER[a.Status] - ORDER[b.Status]) || a.System.localeCompare(b.System) || a.Game.localeCompare(b.Game));
    $('grid').innerHTML = rows.slice(0, limit).map(r => `<div class="tile ${r.Status}" data-i="${r.i}">
      ${r.Screenshot ? `<img loading="lazy" src="${enc(r.Screenshot)}" alt="">` : '<div class="noimg">No screenshot</div>'}
      <div class="body"><div class="game">${esc(r.Game)}</div><div class="sub">${esc(r.System)} &middot; ${esc(r.Seconds)}s</div>
      <div class="reason"><span class="badge ${r.Status}">${LABEL[r.Status]}</span> ${esc(r.Reason)}</div>
      ${r.Doctor ? `<div class="doctor">doctor: ${esc(r.Doctor)}</div>` : ''}</div></div>`).join('') || '<p class="muted">Nothing to show.</p>';
    $('more').hidden = rows.length <= limit;
    $('more').textContent = 'Show more (' + (rows.length - limit).toLocaleString() + ' left)';
  }
  $('filters').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    filter = b.dataset.f; limit = 240;
    document.querySelectorAll('#filters button').forEach(x => x.classList.toggle('on', x === b));
    drawGrid();
  });
  $('q').addEventListener('input', e => { query = e.target.value.trim().toLowerCase(); limit = 240; drawGrid(); });
  $('more').addEventListener('click', () => { limit += 240; drawGrid(); });
  $('grid').addEventListener('click', e => {
    const t = e.target.closest('.tile'); if (!t) return;
    const r = L[+t.dataset.i];
    $('panel').innerHTML = `<div class="top"><div><h2 style="margin:0">${esc(r.Game)}</h2>
      <div class="muted">${esc(r.System)} &middot; ${esc(r.Emulator)} &middot; ${esc(r.Seconds)}s &middot; ${esc(r.Tested)}</div></div>
      <button id="close">Close</button></div>
      <p><span class="badge ${r.Status}">${LABEL[r.Status]}</span> ${esc(r.Reason)}</p>
      ${r.Screenshot ? `<img src="${enc(r.Screenshot)}" alt="">` : ''}
      ${r.Details ? `<pre>${esc(r.Details)}</pre>` : ''}
      ${r.Doctor ? `<p class="warn">doctor: ${esc(r.Doctor)}</p>` : ''}
      ${r.Log ? `<p><a href="${enc(r.Log)}">RocketLauncher log for this launch</a></p>` : ''}`;
    $('modal').hidden = false;
    $('close').onclick = () => { $('modal').hidden = true; };
  });
  $('modal').addEventListener('click', e => { if (e.target.id === 'modal') $('modal').hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('modal').hidden = true; });
  drawGrid();

  const per = {};
  ALL.forEach(r => {
    const p = per[r.System] || (per[r.System] = { PASS: 0, WARN: 0, FAIL: 0, SKIPPED: 0 });
    p[r.Status] = (p[r.Status] || 0) + 1;
  });
  $('systems').innerHTML = '<tr><th>System</th><th class="num">Passed</th><th class="num">Warnings</th><th class="num">Failed</th><th class="num">Skipped</th></tr>' +
    Object.keys(per).sort().map(s => `<tr><td>${esc(s)}</td><td class="num">${per[s].PASS}</td><td class="num">${per[s].WARN}</td><td class="num">${per[s].FAIL}</td><td class="num">${per[s].SKIPPED}</td></tr>`).join('');
  if (!S.length) $('skippedSection').hidden = true;
  $('skipped').innerHTML = '<tr><th>System</th><th>Game</th><th>Why</th><th>Fix</th></tr>' +
    S.map(r => `<tr><td>${esc(r.System)}</td><td>${esc(r.Game)}</td><td class="notes">${esc(r.Reason)}</td><td class="notes">${esc(r.Fix)}</td></tr>`).join('');
})();
</script>
</body>
</html>
"""
