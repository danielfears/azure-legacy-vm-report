"""Self-contained interactive HTML report with CSP hashing, sorting, filtering and live February 2027 hike modelling."""

from __future__ import annotations

import base64
import hashlib
from html import escape
from typing import List, Optional

from .collect import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARNING
from .dates import format_datetime
from .model import POWER_DEALLOCATED, TYPE_VMSS
from .pricing import POLICY_SERVICE_HEALTH, REGIONAL_FEB_2027_HIKES
from .report import GenerationSummary, Report, TenantReport
from .textfmt import (
    clean_text,
    currency_symbol,
    format_hourly,
    format_money,
    format_pct,
    plural,
)

STYLE = """
:root{color-scheme:dark;--bg:#0a0b16;--panel:rgba(255,255,255,.035);--line:rgba(255,255,255,.09);--text:#e9eaf7;--muted:#9a9fc2;--accent:#b455ff;--accent2:#ff4fd1;--ok:#3ddc97;--warn:#ffb454;--bad:#ff5c7a}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;min-height:100vh;color:var(--text);font:15.5px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:radial-gradient(1100px 620px at 12% -8%,rgba(180,85,255,.18),transparent 62%),radial-gradient(900px 560px at 108% 4%,rgba(255,79,209,.10),transparent 58%),linear-gradient(180deg,#0a0b16,#0c0d1d);background-attachment:fixed}
main{max-width:1680px;margin:0 auto;padding:18px 20px 32px;display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
h1{margin:0;font-size:24px;letter-spacing:.2px}
h1 span{background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin:0;font-size:19px}
h3{margin:0;font-size:14px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
p{margin:0}
.sub{color:var(--muted);margin-top:4px;font-size:14px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.banner{border-color:rgba(255,180,84,.45);color:var(--warn);background:rgba(255,180,84,.07)}
.hero{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
.hcard{padding:16px 18px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.025);display:flex;flex-direction:column;gap:7px}
.hcard.stay{border-color:rgba(255,92,122,.35);background:linear-gradient(180deg,rgba(255,92,122,.07),rgba(255,255,255,.02))}
.hcard.mig{border-color:rgba(61,220,151,.38);background:linear-gradient(180deg,rgba(61,220,151,.08),rgba(255,255,255,.02))}
.hcard .kicker{font-size:13px;font-weight:650;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.hcard .big{font-size:32px;font-weight:750;line-height:1.12;font-variant-numeric:tabular-nums}
.hcard .yr{font-size:14.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.hpills{display:flex;flex-wrap:wrap;gap:7px;margin-top:4px}
.hpill{padding:5px 10px;border-radius:8px;font-size:13.5px;font-weight:600;background:rgba(255,255,255,.05);border:1px solid var(--line);font-variant-numeric:tabular-nums}
.hpill.bad{background:rgba(255,92,122,.13);border-color:rgba(255,92,122,.4);color:#ff8fa3}
.hpill.ok{background:rgba(61,220,151,.13);border-color:rgba(61,220,151,.4);color:#66e8b1}
.hpill.warn{background:rgba(255,180,84,.13);border-color:rgba(255,180,84,.4);color:#ffc97e}
.brief-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:11px}
.bcard{padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.022);display:flex;flex-direction:column;gap:3px}
.bcard .bk{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.065em;color:var(--muted)}
.bcard .bv{font-size:18px;font-weight:750;color:var(--text);line-height:1.2;font-variant-numeric:tabular-nums}
.bcard .bs{font-size:12.5px;color:var(--muted);line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
details.adv{margin-top:8px;border-top:1px solid var(--line);padding-top:8px}
details.adv>summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--muted);user-select:none;list-style:none;display:inline-flex;align-items:center;gap:6px}
details.adv>summary::-webkit-details-marker{display:none}
details.adv>summary::before{content:"\\25B8";display:inline-block;color:var(--accent);transition:transform .15s}
details.adv[open]>summary::before{transform:rotate(90deg)}
details.adv>summary:hover{color:var(--text)}
details.adv .adv-body{margin-top:8px}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px}
.tgroup{display:flex;flex-wrap:wrap;align-items:center;gap:9px}
.chip{display:inline-flex;align-items:center;gap:6px;padding:5px 11px;border-radius:8px;border:1px solid var(--line);background:rgba(255,255,255,.04);font-size:13.5px;cursor:pointer;user-select:none}
.chip:hover{border-color:var(--accent)}
.chip input{margin:0;accent-color:var(--accent);width:15px;height:15px}
.btn{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:5px 11px;font:13.5px/1.3 inherit;cursor:pointer}
.btn:hover{border-color:var(--accent)}
.btn[aria-pressed=true]{background:rgba(180,85,255,.2);border-color:var(--accent);color:#fff;font-weight:600}
label.ctrl{display:inline-flex;align-items:center;gap:6px;font-size:13.5px;color:var(--muted)}
input[type=number],select{background:#14162b;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:5px 8px;width:66px;font:13.5px inherit;font-variant-numeric:tabular-nums}
select{width:auto}
input[type=search]{background:#14162b;border:1px solid var(--line);color:var(--text);border-radius:8px;padding:6px 11px;min-width:230px;font:14px inherit}
input:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px}
.tenant{display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
.meta{color:var(--muted);font-size:13.5px}
.meta code{color:var(--text);background:rgba(255,255,255,.06);padding:2px 7px;border-radius:6px}
.block{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:rgba(255,255,255,.018)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:space-between;margin-bottom:10px}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.tabs{display:flex;flex-wrap:wrap;gap:7px}
.tab-btn{background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:6px 13px;font:600 13.5px/1.3 inherit;cursor:pointer}
.tab-btn:hover{color:var(--text);border-color:var(--accent)}
.tab-btn[aria-selected=true]{background:rgba(180,85,255,.18);border-color:var(--accent);color:#fff}
.scroll-wrap{position:relative}
.scroll-hint{display:none;align-items:center;gap:6px;font-size:12.5px;font-weight:600;color:#d6a4ff;background:rgba(180,85,255,.14);border:1px solid rgba(180,85,255,.45);border-radius:999px;padding:3px 10px}
.scroll-hint.visible{display:inline-flex}
.scroll-btn{background:rgba(180,85,255,.22);border:1px solid rgba(180,85,255,.5);color:#fff;border-radius:6px;padding:1px 7px;font:600 12px/1.3 inherit;cursor:pointer}
.scroll-btn:hover{background:var(--accent)}
.scroll{overflow-x:auto;scrollbar-width:thin;scrollbar-color:var(--accent) rgba(255,255,255,.07);padding-bottom:4px}
.scroll::-webkit-scrollbar{height:10px}
.scroll::-webkit-scrollbar-track{background:rgba(255,255,255,.06);border-radius:6px}
.scroll::-webkit-scrollbar-thumb{background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:6px}
.scroll.has-overflow-right{box-shadow:inset -18px 0 16px -12px rgba(180,85,255,.35)}
.scroll.has-overflow-left{box-shadow:inset 18px 0 16px -12px rgba(180,85,255,.35)}
.scroll.has-overflow-left.has-overflow-right{box-shadow:inset 18px 0 16px -12px rgba(180,85,255,.35),inset -18px 0 16px -12px rgba(180,85,255,.35)}
table{width:100%;border-collapse:collapse;font-size:14px}
table.vm-tbl{font-size:13.5px}
th,td{padding:7px 7px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line);vertical-align:middle}
table.vm-tbl th,table.vm-tbl td{padding:6px 5.5px}
td.wrap{white-space:normal}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:650;font-size:11.5px;line-height:1.25;text-transform:uppercase;letter-spacing:.035em;white-space:normal;vertical-align:bottom}
thead tr.group-head th{padding:6px 7px;font-size:11.5px;letter-spacing:.05em;white-space:normal;vertical-align:middle;border-bottom:1px solid rgba(255,255,255,.14)}
th.g-today{color:var(--text);background:rgba(255,255,255,.03);border-left:1px solid var(--line)}
th.g-stay{color:#ff8fa3;background:rgba(255,92,122,.07);border-left:1px solid rgba(255,92,122,.25)}
th.g-mig{color:#66e8b1;background:rgba(61,220,151,.07);border-left:1px solid rgba(61,220,151,.25)}
td.c-today{border-left:1px solid var(--line);font-weight:600}
td.c-stay{border-left:1px solid rgba(255,92,122,.2);background:rgba(255,92,122,.02)}
td.c-mig{border-left:1px solid rgba(61,220,151,.2);background:rgba(61,220,151,.02)}
th button{all:unset;cursor:pointer;color:inherit;font:inherit;text-transform:inherit;letter-spacing:inherit}
th button:hover,th button:focus-visible{color:var(--text);text-decoration:underline}
th[aria-sort=ascending] button::after{content:" \\25B2";color:var(--accent)}
th[aria-sort=descending] button::after{content:" \\25BC";color:var(--accent)}
tbody tr:hover td{background:rgba(180,85,255,.07)}
tr.total-row td{font-weight:700;border-top:2px solid var(--line)}
.cell-main{display:block;font-size:14px;font-weight:600;color:var(--text);overflow-wrap:anywhere}
.cell-sub{display:block;font-size:12px;color:var(--muted);margin-top:2px;white-space:normal;max-width:280px;line-height:1.3}
.badge{display:inline-block;padding:1px 7px;border-radius:999px;font-size:12px;border:1px solid currentColor;line-height:1.45;white-space:nowrap}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.dim{color:var(--muted)}.accent{color:var(--accent)}
.gen-inline{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap}
.gen-inline .meta{font-size:12.5px}
.gen-v1{color:var(--bad)}.gen-v2{color:var(--warn)}.gen-v3{color:var(--accent2)}.gen-v4,.gen-v5,.gen-v6{color:var(--accent)}
.note{padding:6px 0;border-bottom:1px solid var(--line);font-size:13.5px}
.note:last-child{border-bottom:0}
.empty{color:var(--muted);padding:8px 0}
footer{color:var(--muted);font-size:13px;text-align:center}
@media (max-width:1360px){.brief-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:960px){.hero,.brief-grid{grid-template-columns:1fr}}
"""

SCRIPT = """
(function () {
  function cellValue(cell) {
    var sort = cell.getAttribute('data-sort');
    return (sort !== null ? sort : cell.textContent).trim().toLowerCase();
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var heads = table.querySelectorAll('thead tr:last-child th');
    heads.forEach(function (th, index) {
      var button = th.querySelector('button');
      if (!button) { return; }
      button.addEventListener('click', function () {
        var ascending = th.getAttribute('aria-sort') !== 'ascending';
        heads.forEach(function (other) { other.removeAttribute('aria-sort'); });
        th.setAttribute('aria-sort', ascending ? 'ascending' : 'descending');
        var numeric = th.classList.contains('num');
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          if (a.classList.contains('total-row')) { return 1; }
          if (b.classList.contains('total-row')) { return -1; }
          var x = cellValue(a.cells[index]), y = cellValue(b.cells[index]);
          if (numeric) {
            x = parseFloat(x); y = parseFloat(y);
            x = isNaN(x) ? -Infinity : x; y = isNaN(y) ? -Infinity : y;
            return ascending ? x - y : y - x;
          }
          return ascending ? x.localeCompare(y) : y.localeCompare(x);
        });
        rows.forEach(function (row) { body.appendChild(row); });
      });
    });
  });

  function updateScrollCues() {
    document.querySelectorAll('.scroll').forEach(function (sc) {
      var overflows = sc.scrollWidth > sc.clientWidth + 4;
      var left = sc.scrollLeft > 4;
      var right = (sc.scrollLeft + sc.clientWidth) < (sc.scrollWidth - 4);
      sc.classList.toggle('has-overflow-left', overflows && left);
      sc.classList.toggle('has-overflow-right', overflows && right);
      var block = sc.closest('.block, .panel');
      if (!block) { return; }
      var hint = block.querySelector('.scroll-hint');
      if (!hint && overflows) {
        var bar = block.querySelector('.bar');
        if (bar) {
          hint = document.createElement('span');
          hint.className = 'scroll-hint visible';
          hint.innerHTML = '\u21c4 Scroll table <button type="button" class="scroll-btn" data-dir="-1">\u2190</button><button type="button" class="scroll-btn" data-dir="1">\u2192</button>';
          hint.querySelectorAll('button').forEach(function (b) {
            b.addEventListener('click', function () {
              var d = parseInt(b.getAttribute('data-dir'), 10) || 1;
              sc.scrollBy({ left: d * 320, behavior: 'smooth' });
            });
          });
          bar.appendChild(hint);
        }
      } else if (hint) {
        hint.classList.toggle('visible', overflows);
      }
    });
  }
  document.querySelectorAll('.scroll').forEach(function (sc) {
    sc.addEventListener('scroll', updateScrollCues);
  });
  window.addEventListener('resize', updateScrollCues);
  setTimeout(updateScrollCues, 50);

  document.querySelectorAll('.tab-btn[data-tab-target]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var group = btn.getAttribute('data-tab-group');
      var target = btn.getAttribute('data-tab-target');
      document.querySelectorAll('.tab-btn[data-tab-group="' + group + '"]').forEach(function (b) {
        b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
      });
      document.querySelectorAll('.tab-pane[data-tab-group="' + group + '"]').forEach(function (pane) {
        pane.hidden = (target !== 'all' && pane.getAttribute('data-pane') !== target);
      });
      setTimeout(updateScrollCues, 20);
    });
  });

  function applyFilters(tableId) {
    var table = document.getElementById(tableId);
    if (!table) { return; }
    var searchInput = document.querySelector('input[data-filter="' + tableId + '"]');
    var genSelect = document.querySelector('select[data-gen-filter="' + tableId + '"]');
    var hikedOnlyCb = document.querySelector('input[data-hiked-filter="' + tableId + '"]');
    var activeOnlyCb = document.querySelector('input[data-active-filter="' + tableId + '"]');
    var countBadge = document.querySelector('[data-count-for="' + tableId + '"]');
    var query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    var gen = genSelect ? genSelect.value : '';
    var hikedOnly = hikedOnlyCb && hikedOnlyCb.checked;
    var activeOnly = activeOnlyCb && activeOnlyCb.checked;
    var shown = 0, total = table.tBodies[0].rows.length;
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      var rowGen = row.getAttribute('data-gen') || '';
      var matchGen = !gen || rowGen === gen;
      var matchText = !query || row.textContent.toLowerCase().indexOf(query) !== -1;
      var rowDelta = parseFloat(row.getAttribute('data-live-delta') || '0');
      var matchHiked = !hikedOnly || Math.abs(rowDelta) > 0.005;
      var matchActive = !activeOnly || row.getAttribute('data-billed') === '1';
      var vis = matchGen && matchText && matchHiked && matchActive;
      row.hidden = !vis;
      if (vis) { shown += 1; }
    });
    if (countBadge) {
      countBadge.textContent = shown === total ? (total + ' items') : (shown + ' of ' + total);
    }
  }

  document.querySelectorAll('input[data-filter]').forEach(function (input) {
    var id = input.getAttribute('data-filter');
    input.addEventListener('input', function () { applyFilters(id); });
  });
  document.querySelectorAll('select[data-gen-filter]').forEach(function (sel) {
    var id = sel.getAttribute('data-gen-filter');
    sel.addEventListener('change', function () { applyFilters(id); });
  });
  document.querySelectorAll('input[data-hiked-filter], input[data-active-filter]').forEach(function (cb) {
    var id = cb.getAttribute('data-hiked-filter') || cb.getAttribute('data-active-filter');
    cb.addEventListener('change', function () { applyFilters(id); });
  });

  var simPanel = document.getElementById('hike-simulator');
  if (!simPanel) { return; }
  var sym = simPanel.getAttribute('data-symbol') || '£';
  var v1Input = document.getElementById('sim-v1');
  var v2Input = document.getElementById('sim-v2');
  var v3Input = document.getElementById('sim-v3');
  var costSourceSelect = document.getElementById('sim-cost-source');
  var deallocCheck = document.getElementById('sim-dealloc');
  var targetTierSelect = document.getElementById('sim-target-tier');
  var genMigChecks = simPanel.querySelectorAll('input.gen-mig-check');
  var shutIdleCheck = document.getElementById('sim-shut-idle');
  var modeButtons = simPanel.querySelectorAll('button[data-mode]');
  var presetButtons = simPanel.querySelectorAll('button[data-mig-preset]');
  var currentMode = simPanel.getAttribute('data-initial-mode') || 'service-health';

  function fmtMoney(val, signed) {
    var abs = Math.abs(val);
    var formatted = abs.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (signed) {
      return (val > 0.004 ? '+' : (val < -0.004 ? '-' : '+')) + sym + formatted;
    }
    return (val < -0.004 ? '-' : '') + sym + formatted;
  }

  function fmtPct(val) {
    var r = Math.round(val * 10) / 10;
    var prefix = r >= 0 ? '+' : '';
    return prefix + (Math.abs(r - Math.round(r)) < 0.01 ? Math.round(r) : r.toFixed(1)) + '%';
  }

  function fmtDeltaAndPct(delta, base) {
    if (Math.abs(delta) < 0.005) { return 'No hike (' + sym + '0)'; }
    var pct = base > 0 ? (delta / base) * 100 : 0;
    return fmtMoney(delta, true) + ' (' + fmtPct(pct) + ')';
  }

  function fmtNetVsStay(deltaVsFeb, feb) {
    if (Math.abs(deltaVsFeb) < 0.005) { return 'No change (' + sym + '0)'; }
    var pct = feb > 0 ? Math.abs((deltaVsFeb / feb) * 100) : 0;
    var pctStr = (Math.abs(pct - Math.round(pct)) < 0.05 ? Math.round(pct) : pct.toFixed(1)) + '%';
    if (deltaVsFeb < 0) {
      return 'Saves ' + fmtMoney(-deltaVsFeb, false) + ' (-' + pctStr + ')';
    }
    return fmtMoney(deltaVsFeb, true) + ' (+' + pctStr + ')';
  }

  function buildPlainBreakdown(legSku, tgtSku, hikePct, pctVsCur, pctVsFeb, deltaVsCur, deltaVsFeb) {
    var stayPart = hikePct > 0.05
      ? ('Not migrating: ' + fmtPct(hikePct) + ' hike on ' + legSku + ' in Feb 2027')
      : ('Not migrating: 0% list-price hike on ' + legSku + ' in Feb 2027');
    var curPart = '';
    if (pctVsCur < -0.1) {
      curPart = 'Migrating to ' + tgtSku + ': down ' + fmtPct(pctVsCur) + ' (' + fmtMoney(deltaVsCur, true) + '/mo vs today — new SKU is cheaper)';
    } else if (pctVsCur > 0.1) {
      curPart = 'Migrating to ' + tgtSku + ': up ' + fmtPct(pctVsCur) + ' (' + fmtMoney(deltaVsCur, true) + '/mo vs today due to new SKU rate/size)';
    } else {
      curPart = 'Migrating to ' + tgtSku + ': 0% (' + fmtMoney(0, false) + '/mo vs today — same rate)';
    }
    var febPart = '';
    if (pctVsFeb < -0.1) {
      febPart = 'saves ' + Math.abs(pctVsFeb).toFixed(1) + '% (' + fmtMoney(-deltaVsFeb, false) + '/mo) vs not migrating in Feb 2027';
    } else if (pctVsFeb > 0.1) {
      febPart = 'paying ' + fmtPct(pctVsFeb) + ' (' + fmtMoney(deltaVsFeb, true) + '/mo) vs not migrating in Feb 2027';
    } else {
      febPart = '0% vs Feb 2027 PAYG (unlocks 3Y RI/SP)';
    }
    return stayPart + ' · ' + curPart + '; ' + febPart;
  }

  function resolveBaseline(row, source, includeDealloc) {
    var provCur = parseFloat(row.getAttribute('data-prov-cur') || '0');
    var schedCur = parseFloat(row.getAttribute('data-sched-cur') || provCur);
    var billedNow = row.getAttribute('data-billed') === '1';
    var retailCur = (billedNow || includeDealloc) ? provCur : 0;
    var retailSchedCur = (billedNow || includeDealloc) ? schedCur : 0;
    if (source === 'retail') {
      return retailCur;
    }
    if (source === 'retail-scheduled') {
      return retailSchedCur;
    }
    var hasCm = row.getAttribute('data-has-cm') === '1';
    if (!hasCm) {
      return retailSchedCur;
    }
    var lmCost = parseFloat(row.getAttribute('data-lm-cost') || '0');
    var mtdExt = parseFloat(row.getAttribute('data-mtd-ext') || '0');
    if (source === 'last-month') {
      return (lmCost === 0 && includeDealloc) ? provCur : lmCost;
    }
    if (source === 'mtd') {
      return (mtdExt === 0 && includeDealloc) ? provCur : mtdExt;
    }
    if (lmCost > 0) { return lmCost; }
    if (mtdExt > 0) { return mtdExt; }
    return includeDealloc ? provCur : 0;
  }

  function computeCandidateCosts(row, cur, tier) {
    var v5Ratio = parseFloat(row.getAttribute('data-v5-ratio') || '1');
    var v6Ratio = parseFloat(row.getAttribute('data-v6-ratio') || String(v5Ratio));
    var v5Ri24x7 = parseFloat(row.getAttribute('data-v5-ri-24x7') || '0');
    var v6Ri24x7 = parseFloat(row.getAttribute('data-v6-ri-24x7') || String(v5Ri24x7));
    var paygV5 = cur * v5Ratio;
    var paygV6 = cur * v6Ratio;
    var riV5 = cur > 0 ? (v5Ri24x7 > 0 ? Math.min(paygV5, v5Ri24x7) : paygV5 * 0.55) : 0;
    var riV6 = cur > 0 ? (v6Ri24x7 > 0 ? Math.min(paygV6, v6Ri24x7) : paygV6 * 0.55) : 0;
    var isV6 = (tier === 'v6-payg' || tier === 'v6-ri');
    var candMo = tier === 'v6-payg' ? paygV6 : (tier === 'v5-ri' ? riV5 : (tier === 'v6-ri' ? riV6 : paygV5));
    var candRiMo = isV6 ? riV6 : riV5;
    var baseRatio = isV6 ? v6Ratio : v5Ratio;
    return { candMo: candMo, candRiMo: candRiMo, baseRatio: baseRatio };
  }

  function resolveTargetSkuName(row, tier) {
    var v5Sku = row.getAttribute('data-v5-sku') || '';
    var v6Sku = row.getAttribute('data-v6-sku') || v5Sku;
    if (tier === 'v6-payg') { return v6Sku; }
    if (tier === 'v5-ri') { return v5Sku + ' (3Y RI)'; }
    if (tier === 'v6-ri') { return v6Sku + ' (3Y RI)'; }
    return v5Sku;
  }

  function resolveHikePct(row, gen, v1Pct, v2Pct, v3Pct) {
    var shPct = parseFloat(row.getAttribute('data-sh-pct') || '0');
    var regPct = parseFloat(row.getAttribute('data-reg-pct') || '0');
    if (currentMode === 'service-health') {
      return shPct;
    }
    if (currentMode === 'legacy-25') {
      return (gen === 'v1' || gen === 'v2' || gen === 'v3') ? v1Pct : regPct;
    }
    if (gen === 'v1') { return v1Pct; }
    if (gen === 'v2') { return v2Pct; }
    if (gen === 'v3') { return v3Pct; }
    return regPct;
  }

  function syncParentCheckboxes() {
    document.querySelectorAll('tr.sku-summary-row').forEach(function (srow) {
      var sCb = srow.querySelector('input.sku-mig-check');
      if (!sCb) { return; }
      var sku = sCb.getAttribute('data-sku') || '';
      var tenant = sCb.getAttribute('data-tenant') || '';
      var total = 0, checked = 0;
      document.querySelectorAll('tr.vm-row').forEach(function (r) {
        if (r.getAttribute('data-sku') === sku && r.getAttribute('data-tenant') === tenant) {
          var cb = r.querySelector('input.vm-mig-check');
          if (cb) {
            total += 1;
            if (cb.checked) { checked += 1; }
          }
        }
      });
      if (total > 0) {
        sCb.checked = checked > 0;
        sCb.indeterminate = checked > 0 && checked < total;
      }
    });
    genMigChecks.forEach(function (gCb) {
      var gen = gCb.getAttribute('data-gen') || '';
      var boxes = document.querySelectorAll('tr.vm-row[data-gen="' + gen + '"] input.vm-mig-check');
      var total = boxes.length, checked = 0;
      Array.prototype.forEach.call(boxes, function (cb) {
        if (cb.checked) { checked += 1; }
      });
      if (total > 0) {
        gCb.checked = checked > 0;
        gCb.indeterminate = checked > 0 && checked < total;
      }
    });
  }

  function recalc() {
    var v1Pct = parseFloat(v1Input.value) || 0;
    var v2Pct = parseFloat(v2Input.value) || 0;
    var v3Pct = parseFloat(v3Input.value) || 0;
    var costSource = costSourceSelect ? costSourceSelect.value : 'auto';
    var includeDealloc = deallocCheck && deallocCheck.checked;
    var tier = targetTierSelect ? targetTierSelect.value : 'v5-payg';
    var shutIdle = shutIdleCheck && shutIdleCheck.checked;

    var vmRows = document.querySelectorAll('tr.vm-row');
    if (!vmRows.length) { return; }

    var genStats = {
      v1: { cur: 0, feb: 0, plan: 0, planRi: 0 },
      v2: { cur: 0, feb: 0, plan: 0, planRi: 0 },
      v3: { cur: 0, feb: 0, plan: 0, planRi: 0 },
      v4: { cur: 0, feb: 0, plan: 0, planRi: 0 },
      v5: { cur: 0, feb: 0, plan: 0, planRi: 0 },
      v6: { cur: 0, feb: 0, plan: 0, planRi: 0 }
    };
    var skuStats = {};
    var subStats = {};
    var mgStats = {};
    var waveStats = {};
    var totalCur = 0, totalFeb = 0, totalPlan = 0, totalPlanRi = 0;
    var migratedCount = 0, stayedCount = 0, idleShutCount = 0;

    vmRows.forEach(function (row) {
      var gen = row.getAttribute('data-gen') || 'v3';
      var sku = row.getAttribute('data-sku') || '';
      var sub = row.getAttribute('data-sub') || '';
      var mg = row.getAttribute('data-mg') || 'Tenant Root';
      var wave = row.getAttribute('data-wave') || '';
      var tenant = row.getAttribute('data-tenant') || '';
      var instCount = parseInt(row.getAttribute('data-inst') || '1', 10) || 1;
      var isIdle = row.getAttribute('data-idle') === '1';
      var vmCheck = row.querySelector('input.vm-mig-check');
      var isMigrated = vmCheck ? vmCheck.checked : true;

      var cur = resolveBaseline(row, costSource, includeDealloc);
      var pct = resolveHikePct(row, gen, v1Pct, v2Pct, v3Pct);
      var feb = cur * (1 + pct / 100);
      var delta = feb - cur;
      row.setAttribute('data-live-delta', delta.toFixed(2));

      var costs = computeCandidateCosts(row, cur, tier);
      var candMo = costs.candMo;
      var candRiMo = costs.candRiMo;

      var planMo = (shutIdle && isIdle) ? 0 : (isMigrated ? candMo : feb);
      var planRiMo = (shutIdle && isIdle) ? 0 : (isMigrated ? candRiMo : feb);

      var deltaVsCur = planMo - cur;
      var pctVsCur = cur > 0 ? (deltaVsCur / cur) * 100 : (isMigrated ? (costs.baseRatio - 1) * 100 : pct);
      var deltaVsFeb = planMo - feb;
      var pctVsFeb = feb > 0 ? (deltaVsFeb / feb) * 100 : 0;
      var saveVsFeb = feb - planMo;

      if (shutIdle && isIdle) {
        idleShutCount += instCount;
      } else if (isMigrated) {
        migratedCount += instCount;
      } else {
        stayedCount += instCount;
      }

      var baseTgtLabel = resolveTargetSkuName(row, tier);
      var tgtSkuLabel = (shutIdle && isIdle)
        ? 'Stop Idle VM'
        : (isMigrated ? baseTgtLabel : (sku + ' (Stay)'));

      var curCell = row.querySelector('[data-col="cur"]');
      var febCell = row.querySelector('[data-col="feb"]');
      var deltaCell = row.querySelector('[data-col="delta"]');
      var pctCell = row.querySelector('[data-col="pct"]');
      var tgtSkuCell = row.querySelector('[data-col="tgtsku"]');
      var v5Cell = row.querySelector('[data-col="v5"]');
      var migSubEl = row.querySelector('[data-col="migsub"]');
      var migCurCell = row.querySelector('[data-col="migcur"]');
      var v5SaveCell = row.querySelector('[data-col="v5save"]');
      var breakdownCell = row.querySelector('[data-col="breakdown"]');

      if (curCell) { curCell.textContent = fmtMoney(cur, false); curCell.setAttribute('data-sort', cur.toFixed(2)); }
      if (febCell) { febCell.textContent = fmtMoney(feb, false); febCell.setAttribute('data-sort', feb.toFixed(2)); }
      if (deltaCell) {
        deltaCell.textContent = fmtDeltaAndPct(delta, cur);
        deltaCell.setAttribute('data-sort', delta.toFixed(2));
        deltaCell.className = 'num ' + (delta > 0.005 ? 'bad' : 'dim');
      }
      if (pctCell) { pctCell.textContent = fmtPct(pct); pctCell.setAttribute('data-sort', pct.toFixed(2)); }
      if (tgtSkuCell) { tgtSkuCell.textContent = tgtSkuLabel; }
      if (v5Cell) {
        var v5Main = v5Cell.querySelector('.cell-main');
        if (v5Main) { v5Main.textContent = fmtMoney(planMo, false); }
        else { v5Cell.textContent = fmtMoney(planMo, false); }
        v5Cell.setAttribute('data-sort', planMo.toFixed(2));
      }
      if (migSubEl) {
        migSubEl.textContent = Math.abs(deltaVsCur) > 0.005 ? ('vs Today: ' + fmtMoney(deltaVsCur, true)) : '';
      }
      if (migCurCell) {
        migCurCell.textContent = fmtDeltaAndPct(deltaVsCur, cur);
        migCurCell.setAttribute('data-sort', deltaVsCur.toFixed(2));
        migCurCell.className = 'num ' + (deltaVsCur < -0.01 ? 'ok' : (deltaVsCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5SaveCell) {
        v5SaveCell.textContent = fmtNetVsStay(deltaVsFeb, feb);
        v5SaveCell.setAttribute('data-sort', saveVsFeb.toFixed(2));
        v5SaveCell.className = 'num ' + (deltaVsFeb < -0.01 ? 'ok' : (deltaVsFeb > 0.01 ? 'bad' : 'dim'));
      }
      if (breakdownCell) {
        breakdownCell.textContent = buildPlainBreakdown(sku, baseTgtLabel, pct, pctVsCur, pctVsFeb, deltaVsCur, deltaVsFeb);
      }

      if (genStats[gen]) {
        genStats[gen].cur += cur; genStats[gen].feb += feb;
        genStats[gen].plan += planMo; genStats[gen].planRi += planRiMo;
      }
      totalCur += cur; totalFeb += feb; totalPlan += planMo; totalPlanRi += planRiMo;

      var skuKey = tenant + '|' + sku;
      if (!skuStats[skuKey]) { skuStats[skuKey] = { cur: 0, feb: 0, plan: 0, pct: pct }; }
      skuStats[skuKey].cur += cur; skuStats[skuKey].feb += feb; skuStats[skuKey].plan += planMo;

      var subKey = tenant + '|' + sub;
      if (!subStats[subKey]) { subStats[subKey] = { cur: 0, feb: 0, plan: 0 }; }
      subStats[subKey].cur += cur; subStats[subKey].feb += feb; subStats[subKey].plan += planMo;

      var mgKey = tenant + '|' + mg;
      if (!mgStats[mgKey]) { mgStats[mgKey] = { cur: 0, feb: 0, plan: 0 }; }
      mgStats[mgKey].cur += cur; mgStats[mgKey].feb += feb; mgStats[mgKey].plan += planMo;

      var waveKey = tenant + '|' + wave;
      if (!waveStats[waveKey]) { waveStats[waveKey] = { cur: 0, feb: 0, plan: 0, planRi: 0 }; }
      waveStats[waveKey].cur += cur; waveStats[waveKey].feb += feb;
      waveStats[waveKey].plan += planMo; waveStats[waveKey].planRi += planRiMo;
    });

    var totalDelta = totalFeb - totalCur;
    var totalYrDelta = totalDelta * 12;
    var totalPct = totalCur > 0 ? (totalDelta / totalCur) * 100 : 0;
    var blendedVsCur = totalPlan - totalCur;
    var blendedVsCurPct = totalCur > 0 ? (blendedVsCur / totalCur) * 100 : 0;
    var blendedVsFeb = totalPlan - totalFeb;
    var blendedVsFebPct = totalFeb > 0 ? (blendedVsFeb / totalFeb) * 100 : 0;

    var kpiCur = document.getElementById('kpi-current-mo');
    var kpiCurYr = document.getElementById('kpi-current-yr');
    var kpiFeb = document.getElementById('kpi-feb-mo');
    var kpiFebYr = document.getElementById('kpi-feb-yr');
    var kpiDelta = document.getElementById('kpi-delta-mo');
    var kpiYr = document.getElementById('kpi-delta-yr');
    var kpiPlanMo = document.getElementById('kpi-plan-mo');
    var kpiPlanYr = document.getElementById('kpi-plan-yr');
    var kpiPlanVsCur = document.getElementById('kpi-plan-vs-cur');
    var kpiPlanVsFeb = document.getElementById('kpi-plan-vs-feb');

    if (kpiCur) { kpiCur.textContent = fmtMoney(totalCur, false) + ' / mo'; }
    if (kpiCurYr) { kpiCurYr.textContent = fmtMoney(totalCur * 12, false) + ' / yr'; }
    if (kpiFeb) { kpiFeb.textContent = fmtMoney(totalFeb, false) + ' / mo'; }
    if (kpiFebYr) { kpiFebYr.textContent = fmtMoney(totalFeb * 12, false) + ' / yr'; }
    if (kpiDelta) { kpiDelta.textContent = 'vs Today: ' + fmtMoney(totalDelta, true) + '/mo (' + fmtPct(totalPct) + ')'; }
    if (kpiYr) { kpiYr.textContent = fmtMoney(totalYrDelta, true) + ' / yr hike'; }

    if (kpiPlanMo) { kpiPlanMo.textContent = fmtMoney(totalPlan, false) + ' / mo'; }
    if (kpiPlanYr) {
      var idleSuffix = idleShutCount > 0 ? (' · ' + idleShutCount + ' idle stopped') : '';
      kpiPlanYr.textContent = fmtMoney(totalPlan * 12, false) + ' / yr · ' + migratedCount + ' migrated, ' + stayedCount + ' staying' + idleSuffix;
    }
    if (kpiPlanVsCur) {
      kpiPlanVsCur.textContent = 'vs Today: ' + fmtMoney(blendedVsCur, true) + '/mo (' + fmtPct(blendedVsCurPct) + ')';
      kpiPlanVsCur.className = 'hpill ' + (blendedVsCur <= 0.01 ? 'ok' : 'warn');
    }
    if (kpiPlanVsFeb) {
      kpiPlanVsFeb.textContent = 'vs Do Nothing: ' + fmtMoney(blendedVsFeb, true) + '/mo (' + fmtPct(blendedVsFebPct) + ') · ' + fmtMoney(blendedVsFeb * 12, true) + '/yr';
      kpiPlanVsFeb.className = 'hpill ' + (blendedVsFeb <= 0.01 ? 'ok' : 'bad');
    }

    document.querySelectorAll('tr.gen-summary-row').forEach(function (row) {
      var g = row.getAttribute('data-gen-summary');
      var st = g === 'Total' ? { cur: totalCur, feb: totalFeb, plan: totalPlan, planRi: totalPlanRi } : genStats[g];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mCur = st.plan - st.cur;
      var mFeb = st.plan - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      var v5riEl = row.querySelector('[data-col="v5ri"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); }
      if (dEl) {
        dEl.textContent = fmtDeltaAndPct(d, st.cur);
        dEl.className = 'num ' + (d > 0.005 ? 'bad' : 'dim');
      }
      if (v5El) { v5El.textContent = fmtMoney(st.plan, false); }
      if (mCurEl) {
        mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur);
        mCurEl.className = 'num ' + (mCur < -0.01 ? 'ok' : (mCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5sEl) {
        v5sEl.textContent = fmtNetVsStay(mFeb, st.feb);
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
      if (v5riEl) { v5riEl.textContent = fmtMoney(st.planRi, false); }
    });

    document.querySelectorAll('tr.sku-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sku-key');
      var st = skuStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mCur = st.plan - st.cur;
      var mFeb = st.plan - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mSubEl = row.querySelector('[data-col="migsub"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) {
        dEl.textContent = fmtDeltaAndPct(d, st.cur);
        dEl.setAttribute('data-sort', d.toFixed(2));
        dEl.className = 'num ' + (d > 0.005 ? 'bad' : 'dim');
      }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
      if (v5El) {
        var v5Main = v5El.querySelector('.cell-main');
        if (v5Main) { v5Main.textContent = fmtMoney(st.plan, false); }
        else { v5El.textContent = fmtMoney(st.plan, false); }
        v5El.setAttribute('data-sort', st.plan.toFixed(2));
      }
      if (mSubEl) {
        mSubEl.textContent = Math.abs(mCur) > 0.005 ? ('vs Today: ' + fmtMoney(mCur, true)) : '';
      }
      if (mCurEl) {
        mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur);
        mCurEl.setAttribute('data-sort', mCur.toFixed(2));
        mCurEl.className = 'num ' + (mCur < -0.01 ? 'ok' : (mCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5sEl) {
        v5sEl.textContent = fmtNetVsStay(mFeb, st.feb);
        v5sEl.setAttribute('data-sort', (-mFeb).toFixed(2));
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
    });

    document.querySelectorAll('tr.sub-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sub-key');
      var st = subStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mFeb = st.plan - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) {
        dEl.textContent = fmtDeltaAndPct(d, st.cur);
        dEl.setAttribute('data-sort', d.toFixed(2));
        dEl.className = 'num ' + (d > 0.005 ? 'bad' : 'dim');
      }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
      if (v5El) { v5El.textContent = fmtMoney(st.plan, false); v5El.setAttribute('data-sort', st.plan.toFixed(2)); }
      if (v5sEl) {
        v5sEl.textContent = fmtNetVsStay(mFeb, st.feb);
        v5sEl.setAttribute('data-sort', (-mFeb).toFixed(2));
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
    });

    document.querySelectorAll('tr.mg-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-mg-key');
      var st = mgStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mFeb = st.plan - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) {
        dEl.textContent = fmtDeltaAndPct(d, st.cur);
        dEl.setAttribute('data-sort', d.toFixed(2));
        dEl.className = 'num ' + (d > 0.005 ? 'bad' : 'dim');
      }
      if (v5El) { v5El.textContent = fmtMoney(st.plan, false); v5El.setAttribute('data-sort', st.plan.toFixed(2)); }
      if (v5sEl) {
        v5sEl.textContent = fmtNetVsStay(mFeb, st.feb);
        v5sEl.setAttribute('data-sort', (-mFeb).toFixed(2));
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
    });

    document.querySelectorAll('tr.wave-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-wave-key');
      var st = waveStats[key];
      if (!st) { return; }
      var mCur = st.plan - st.cur;
      var mFeb = st.plan - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      var v5riEl = row.querySelector('[data-col="v5ri"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); }
      if (v5El) { v5El.textContent = fmtMoney(st.plan, false); }
      if (mCurEl) {
        mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur);
        mCurEl.className = 'num ' + (mCur < -0.01 ? 'ok' : (mCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5sEl) {
        v5sEl.textContent = fmtNetVsStay(mFeb, st.feb);
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
      if (v5riEl) { v5riEl.textContent = fmtMoney(st.planRi, false); }
    });
    var discValEl = document.getElementById('brief-disc-val');
    var discSubEl = document.getElementById('brief-disc-sub');
    if (discValEl && discSubEl) {
      var origDiscVal = discValEl.getAttribute('data-orig-val') || '';
      var origDiscSub = discSubEl.getAttribute('data-orig-sub') || '';
      var origDiscCls = discValEl.getAttribute('data-orig-cls') || '';
      if (costSource === 'retail' || costSource === 'retail-scheduled') {
        discValEl.textContent = 'Retail PAYG';
        discValEl.className = 'bv dim';
        discSubEl.textContent = 'Public list rates selected';
      } else {
        discValEl.textContent = origDiscVal;
        discValEl.className = origDiscCls;
        discSubEl.textContent = origDiscSub;
      }
    }
    document.querySelectorAll('table[id^="vms-"]').forEach(function (tbl) {
      applyFilters(tbl.id);
    });
  }

  function syncGenChecksToRows(gen, checked) {
    document.querySelectorAll('tr.vm-row[data-gen="' + gen + '"] input.vm-mig-check').forEach(function (cb) {
      cb.checked = checked;
    });
    syncParentCheckboxes();
    recalc();
  }

  genMigChecks.forEach(function (gCb) {
    gCb.addEventListener('change', function () {
      syncGenChecksToRows(gCb.getAttribute('data-gen') || '', gCb.checked);
    });
  });
  if (targetTierSelect) { targetTierSelect.addEventListener('change', recalc); }
  if (shutIdleCheck) { shutIdleCheck.addEventListener('change', recalc); }

  document.querySelectorAll('input.sku-mig-check').forEach(function (skuCb) {
    skuCb.addEventListener('change', function () {
      var sku = skuCb.getAttribute('data-sku') || '';
      var tenant = skuCb.getAttribute('data-tenant') || '';
      document.querySelectorAll('tr.vm-row').forEach(function (r) {
        if (r.getAttribute('data-sku') === sku && r.getAttribute('data-tenant') === tenant) {
          var cb = r.querySelector('input.vm-mig-check');
          if (cb) { cb.checked = skuCb.checked; }
        }
      });
      syncParentCheckboxes();
      recalc();
    });
  });

  document.querySelectorAll('input.vm-mig-check').forEach(function (vmCb) {
    vmCb.addEventListener('change', function () {
      syncParentCheckboxes();
      recalc();
    });
  });

  presetButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var preset = btn.getAttribute('data-mig-preset');
      var tier = targetTierSelect ? targetTierSelect.value : 'v5-payg';
      var costSource = costSourceSelect ? costSourceSelect.value : 'auto';
      var includeDealloc = deallocCheck && deallocCheck.checked;
      var v1Pct = parseFloat(v1Input.value) || 0;
      var v2Pct = parseFloat(v2Input.value) || 0;
      var v3Pct = parseFloat(v3Input.value) || 0;
      document.querySelectorAll('tr.vm-row').forEach(function (row) {
        var cb = row.querySelector('input.vm-mig-check');
        if (!cb) { return; }
        var gen = row.getAttribute('data-gen') || 'v3';
        if (preset === 'all') {
          cb.checked = true;
        } else if (preset === 'none') {
          cb.checked = false;
        } else if (preset === 'v1v2') {
          cb.checked = (gen === 'v1' || gen === 'v2');
        } else if (preset === 'cheaper-feb') {
          var cur = resolveBaseline(row, costSource, includeDealloc);
          var pct = resolveHikePct(row, gen, v1Pct, v2Pct, v3Pct);
          var costs = computeCandidateCosts(row, cur, tier);
          if (cur > 0) {
            var feb = cur * (1 + pct / 100);
            cb.checked = (costs.candMo <= feb + 0.005);
          } else {
            cb.checked = (costs.baseRatio <= (1 + pct / 100) + 0.0001);
          }
        }
      });
      syncParentCheckboxes();
      recalc();
    });
  });

  modeButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var mode = btn.getAttribute('data-mode');
      currentMode = mode;
      modeButtons.forEach(function (b) { b.setAttribute('aria-pressed', b === btn ? 'true' : 'false'); });
      if (mode === 'legacy-25') {
        v1Input.value = '25'; v2Input.value = '25'; v3Input.value = '25';
      } else if (mode === 'service-health') {
        v1Input.value = '25'; v2Input.value = '25'; v3Input.value = '0';
      }
      recalc();
    });
  });

  [v1Input, v2Input, v3Input].forEach(function (inp) {
    if (!inp) { return; }
    inp.addEventListener('input', function () {
      currentMode = 'custom';
      modeButtons.forEach(function (b) {
        b.setAttribute('aria-pressed', b.getAttribute('data-mode') === 'custom' ? 'true' : 'false');
      });
      recalc();
    });
  });
  if (costSourceSelect) { costSourceSelect.addEventListener('change', recalc); }
  if (deallocCheck) { deallocCheck.addEventListener('change', recalc); }
})();
"""

_LEVEL_LABELS = {LEVEL_ERROR: ("Error", "bad"), LEVEL_WARNING: ("Warning", "warn"), LEVEL_INFO: ("Note", "dim")}


def csp_hash(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def content_security_policy() -> str:
    return (
        f"default-src 'none'; style-src {csp_hash(STYLE)}; script-src {csp_hash(SCRIPT)}; "
        "base-uri 'none'; form-action 'none'"
    )


def _e(value: object) -> str:
    return escape(clean_text(value), quote=True)


def _td(
    text: object,
    *,
    cls: str = "",
    sort: Optional[object] = None,
    title: str = "",
    col: str = "",
    html: str = "",
) -> str:
    attrs = ""
    if cls:
        attrs += f' class="{cls}"'
    if sort is not None:
        attrs += f' data-sort="{_e(sort)}"'
    if title:
        attrs += f' title="{_e(title)}"'
    if col:
        attrs += f' data-col="{_e(col)}"'
    return f"<td{attrs}>{html or _e(text)}</td>"


def _th(label: str, *, numeric: bool = False, sortable: bool = True, title: str = "") -> str:
    cls = ' class="num"' if numeric else ""
    t_attr = f' title="{_e(title)}"' if title else ""
    inner = f'<button type="button">{_e(label)}</button>' if sortable else _e(label)
    return f"<th{cls}{t_attr}>{inner}</th>"


def _badge(text: str, style: Optional[str]) -> str:
    return f'<span class="badge {style or "dim"}">{_e(text)}</span>'


def _fmt_hike_cell(delta: float, pct: float, cur: str) -> str:
    if abs(delta) < 0.005:
        return f"No hike ({currency_symbol(cur)}0)"
    return f"{format_money(delta, cur, signed=True)} ({format_pct(pct, signed=True)})"


def _fmt_net_vs_stay(delta_vs_feb: float, pct_vs_feb: float, cur: str) -> str:
    if abs(delta_vs_feb) < 0.005:
        return f"No change ({currency_symbol(cur)}0)"
    if delta_vs_feb < 0:
        return f"Saves {format_money(-delta_vs_feb, cur)} ({format_pct(pct_vs_feb, signed=True)})"
    return f"{format_money(delta_vs_feb, cur, signed=True)} ({format_pct(pct_vs_feb, signed=True)})"


def _render_executive_brief(report: Report, cur: str) -> str:
    recs = report.all_records()
    if not recs:
        return ""
    sym = currency_symbol(cur)
    zero_amt = f"{sym}0"
    hiked_inst = sum(r.instance_count for r in recs if r.monthly_delta > 0.005)
    zero_active_inst = sum(
        r.instance_count for r in recs if r.monthly_delta <= 0.005 and r.power_state != POWER_DEALLOCATED
    )
    zero_off_inst = sum(
        r.instance_count for r in recs if r.monthly_delta <= 0.005 and r.power_state == POWER_DEALLOCATED
    )
    zero_inst = zero_active_inst + zero_off_inst
    total_inst = hiked_inst + zero_inst
    total_hike = round(sum(r.monthly_delta for r in recs), 2)
    total_cur = round(sum(r.current_monthly for r in recs), 2)

    # Panel 1: Hike Exposure (compact KPI + tooltip breakdown)
    if hiked_inst > 0:
        p1_cls = "warn"
        p1_val = f"{hiked_inst} / {total_inst} instances"
        p1_sub = f"{zero_inst} at {zero_amt} hike" if zero_inst > 0 else "100% of fleet affected"
        p1_tip = (
            f"{hiked_inst} hiked ({format_money(total_hike, cur, signed=True)}/mo); "
            f"{zero_active_inst} active in 0%-hike series/region, {zero_off_inst} deallocated"
        )
    else:
        p1_cls = "ok"
        p1_val = f"0 hiked ({zero_amt})"
        p1_sub = f"All {plural(total_inst, 'instance')} at 0%"
        p1_tip = "All legacy instances in scope are in 0%-hike regions/series or deallocated"

    # Panel 2: Detected Discount (compact KPI + tooltip explanation, neutral peer styling)
    obs_disc = report.observed_discount
    if obs_disc is not None and report.cost_source != "retail":
        d_pct, d_ratio = obs_disc
        disc_val = f"-{d_pct:.1f}% off Retail"
        disc_sub = "Kept on PAYG \u00b7 RIs un-stacked"
        disc_tip = (
            f"Cost Management actuals average {d_ratio:.3f}x public Retail PAYG; "
            "preserved on PAYG targets, while 3-Year RIs use un-stacked public RI rates"
        )
        disc_cls = ""
    elif report.has_cost_management_data and report.cost_source != "retail":
        disc_val = "Retail PAYG"
        disc_sub = "0% discount in actuals"
        disc_tip = "Cost Management actuals match public Retail PAYG rates"
        disc_cls = ""
    else:
        disc_val = "Retail PAYG"
        disc_sub = "Public list rates"
        disc_tip = "Costed from Azure Retail Prices API list rates"
        disc_cls = "dim"

    # Panel 3: Concentration (compact KPI; top names in tooltip + Subscription table directly below)
    subs = report.all_subscription_rows()
    hiked_subs = [s for s in subs if s.monthly_delta > 0.005]
    if hiked_subs and total_hike > 0:
        top_n = hiked_subs[:3]
        top_delta = round(sum(s.monthly_delta for s in top_n), 2)
        top_pct = round((top_delta / total_hike) * 100.0)
        p2_kicker = "Hike Concentration"
        if len(subs) == 1:
            p2_val = "1 subscription"
            p2_sub = f"{format_money(top_delta, cur, signed=True)}/mo hike"
        else:
            p2_val = f"{top_pct}% in top {len(top_n)} subs"
            p2_sub = f"Out of {plural(len(subs), 'subscription')}"
        p2_tip = "Top hiked: " + ", ".join(s.subscription_name for s in top_n)
    elif subs and total_cur > 0:
        active_subs = sorted(subs, key=lambda s: (-s.current_monthly, s.subscription_name.lower()))
        top_n = [s for s in active_subs if s.current_monthly > 0][:3]
        top_cur = round(sum(s.current_monthly for s in top_n), 2)
        top_pct = round((top_cur / total_cur) * 100.0)
        p2_kicker = "Spend Concentration"
        p2_val = f"{top_pct}% in top {len(top_n)} subs"
        p2_sub = f"Out of {plural(len(subs), 'subscription')}"
        p2_tip = "Top spend: " + ", ".join(s.subscription_name for s in top_n)
    else:
        p2_kicker = "Concentration"
        p2_val = plural(len(subs), "subscription")
        p2_sub = f"No active spend ({zero_amt})"
        p2_tip = "No active billed legacy spend"

    # Panel 4: Azure Advisor
    adv_idle = sum(1 for r in recs if "shut down idle vm" in r.advisor_recommendation.lower())
    adv_right = sum(
        1 for r in recs
        if r.advisor_recommendation and "shut down idle vm" not in r.advisor_recommendation.lower()
    )
    adv_total = adv_idle + adv_right
    adv_val = f"{plural(adv_total, 'VM')} flagged" if adv_total > 0 else "0 alerts"
    adv_parts = []
    if adv_idle:
        adv_parts.append(f"{adv_idle} idle")
    if adv_right:
        adv_parts.append(f"{adv_right} right-size")
    adv_sub = " \u00b7 ".join(adv_parts) if adv_parts else "No idle or oversized VMs"
    adv_tip = (
        "Tick 'Stop Advisor idle VMs' in the toolbar below to model shutting down idle VMs"
        if adv_idle > 0
        else "Azure Advisor Cost recommendations matched to legacy VMs"
    )

    # Panel 5: Quota & RI Check (deduplicated by subscription + region + target quota family, active blockers first)
    any_quota_checked = any(bool(r.quota_status) for r in recs)
    quota_by_fam = {}
    for r in recs:
        if "Increase Needed" in r.quota_status or "Quota 0/" in r.quota_status:
            fam_id = (r.target_quota_family or r.quota_status.split("(")[-1].split(":")[0].rstrip(")")).strip().lower()
            qkey = (r.subscription_id.lower(), r.region.lower(), fam_id)
            prev = quota_by_fam.get(qkey)
            if prev is None or (r.is_billed_now and not prev[0]):
                quota_by_fam[qkey] = (r.is_billed_now, r.subscription_name, r.region, r.quota_status)
    ri_cov = sum(r.instance_count for r in recs if "RI Covered" in r.ri_status or "Partial RI" in r.ri_status)
    ri_short = f"{plural(ri_cov, 'active RI')}" if ri_cov != 1 else "1 active RI"

    if quota_by_fam:
        ordered_q = sorted(quota_by_fam.values(), key=lambda x: (0 if x[0] else 1, x[1].lower()))
        active_q = sum(1 for item in ordered_q if item[0])
        off_q = len(ordered_q) - active_q
        q_val = f"{plural(len(ordered_q), 'quota uplift')} needed"
        if active_q and off_q:
            q_sub = f"{active_q} active, {off_q} off \u00b7 {ri_short}"
        elif off_q and not active_q:
            q_sub = f"Deallocated only \u00b7 {ri_short}"
        else:
            q_sub = ri_short
        q_tip = " | ".join(f"{sq[1]} ({sq[2]}): {sq[3]}" for sq in ordered_q[:3])
        q_cls = "bad" if active_q > 0 else "warn"
    elif any_quota_checked:
        q_val = "Quotas ready"
        q_sub = ri_short
        q_tip = "Sufficient regional target vCPU family headroom across all scanned subscriptions"
        q_cls = "ok"
    else:
        q_val = "Quotas unchecked"
        q_sub = ri_short
        q_tip = "Grant Microsoft.Compute/locations/usages/read to pre-check regional v5 vCPU limits"
        q_cls = "dim"

    return "\n".join([
        '<section class="panel">',
        '<div class="brief-grid">',
        f'<div class="bcard" title="{_e(p1_tip)}">',
        '<span class="bk">Hike Exposure</span>',
        f'<span class="bv {p1_cls}">{_e(p1_val)}</span>',
        f'<span class="bs">{_e(p1_sub)}</span>',
        "</div>",
        '<div class="bcard"' + f' title="{_e(disc_tip)}">',
        '<span class="bk">Detected Discount</span>',
        f'<span class="bv {disc_cls}" id="brief-disc-val" data-orig-val="{_e(disc_val)}" data-orig-cls="bv {disc_cls}">{_e(disc_val)}</span>',
        f'<span class="bs" id="brief-disc-sub" data-orig-sub="{_e(disc_sub)}">{_e(disc_sub)}</span>',
        "</div>",
        f'<div class="bcard" title="{_e(p2_tip)}">',
        f'<span class="bk">{_e(p2_kicker)}</span>',
        f'<span class="bv">{_e(p2_val)}</span>',
        f'<span class="bs">{_e(p2_sub)}</span>',
        "</div>",
        f'<div class="bcard" title="{_e(adv_tip)}">',
        '<span class="bk">Azure Advisor</span>',
        f'<span class="bv {"warn" if adv_total else "ok"}">{_e(adv_val)}</span>',
        f'<span class="bs">{_e(adv_sub)}</span>',
        "</div>",
        f'<div class="bcard" title="{_e(q_tip)}">',
        '<span class="bk">Quota &amp; RIs</span>',
        f'<span class="bv {q_cls}">{_e(q_val)}</span>',
        f'<span class="bs">{_e(q_sub)}</span>',
        "</div>",
        "</div>",
        "</section>",
    ])


def render_html(report: Report) -> str:
    tz = report.tz
    cur = report.currency
    sym = currency_symbol(cur)
    gt = report.grand_total()
    by_gen = report.totals_by_generation()
    any_ok = any(t.fetched for t in report.tenants)

    parts: List[str] = [
        "<!doctype html>",
        '<html lang="en-GB">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{content_security_policy()}">',
        "<title>Azure Legacy VM SKU (v1, v2, v3) Cost &amp; February 2027 Hike Report</title>",
        f"<style>{STYLE}</style>",
        "</head>",
        "<body>",
        "<main>",
    ]

    if report.demo:
        parts.append(
            '<div class="panel banner"><strong>Demo data:</strong> synthetic and generated locally. '
            "Nothing was read from Azure.</div>"
        )

    parts += [
        '<header class="panel">',
        '<div class="bar" style="margin:0">',
        "<div>",
        '<h1>Azure Legacy VM (<span>v1, v2 &amp; v3</span>) Cost &amp; February 2027 Hike Report</h1>',
        f'<p class="sub">Generated {_e(format_datetime(report.generated_at, tz))} ({_e(report.tz_name)}) '
        f"&middot; {_e(report.cost_basis_description)}</p>",
        "</div>",
        "</div>",
    ]
    for note in report.notes:
        parts.append(f'<p class="sub warn">{_e(note)}</p>')
    parts.append("</header>")

    # 3 Hero Comparison Cards: 1. Today vs 2. Feb 2027 Do Nothing vs 3. Feb 2027 Migrate
    cur_mo_str = f"{format_money(gt.current_monthly, cur)} / mo" if any_ok else "n/a"
    cur_yr_str = f"{format_money(gt.current_monthly * 12.0, cur)} / yr" if any_ok else ""
    feb_mo_str = f"{format_money(gt.feb_monthly, cur)} / mo" if any_ok else "n/a"
    feb_yr_str = f"{format_money(gt.feb_monthly * 12.0, cur)} / yr" if any_ok else ""
    stay_delta_str = (
        f"vs Today: {format_money(gt.monthly_delta, cur, signed=True)}/mo ({format_pct(gt.effective_hike_pct, signed=True)})"
        if any_ok
        else "n/a"
    )
    stay_yr_delta_str = f"{format_money(gt.annual_delta, cur, signed=True)} / yr hike" if any_ok else "n/a"

    plan_mo_str = f"{format_money(gt.target_v5_monthly, cur)} / mo" if any_ok else "n/a"
    plan_yr_str = (
        f"{format_money(gt.target_v5_monthly * 12.0, cur)} / yr \u00b7 {gt.instance_count} migrated, 0 staying"
        if any_ok
        else ""
    )
    plan_vs_cur_str = (
        f"vs Today: {format_money(gt.target_v5_delta_vs_current, cur, signed=True)}/mo "
        f"({format_pct(gt.target_v5_pct_vs_current, signed=True)})"
        if any_ok
        else "n/a"
    )
    plan_vs_feb_str = (
        f"vs Do Nothing: {format_money(gt.target_v5_delta_vs_feb, cur, signed=True)}/mo "
        f"({format_pct(gt.target_v5_pct_vs_feb, signed=True)}) \u00b7 "
        f"{format_money(gt.target_v5_delta_vs_feb * 12.0, cur, signed=True)}/yr"
        if any_ok
        else "n/a"
    )

    parts += [
        '<section class="hero">',
        '<div class="hcard">',
        '<span class="kicker">1. Current Cost Today</span>',
        f'<span class="big" id="kpi-current-mo">{_e(cur_mo_str)}</span>',
        f'<span class="yr" id="kpi-current-yr">{_e(cur_yr_str)}</span>',
        '<div class="hpills">',
        f'<span class="hpill">{gt.instance_count} instances ({gt.running_instances} active / {gt.deallocated_instances} off)</span>',
        f'<span class="hpill">{gt.total_vcpus} vCPUs</span>',
        "</div>",
        "</div>",
        '<div class="hcard stay">',
        '<span class="kicker">2. Feb 2027 \u2014 Do Nothing (Stay on Legacy)</span>',
        f'<span class="big warn" id="kpi-feb-mo">{_e(feb_mo_str)}</span>',
        f'<span class="yr" id="kpi-feb-yr">{_e(feb_yr_str)}</span>',
        '<div class="hpills">',
        f'<span class="hpill bad" id="kpi-delta-mo">{_e(stay_delta_str)}</span>',
        f'<span class="hpill bad" id="kpi-delta-yr">{_e(stay_yr_delta_str)}</span>',
        "</div>",
        "</div>",
        '<div class="hcard mig">',
        '<span class="kicker">3. Feb 2027 \u2014 Migrate (Selected Tickbox Plan)</span>',
        f'<span class="big ok" id="kpi-plan-mo">{_e(plan_mo_str)}</span>',
        f'<span class="yr" id="kpi-plan-yr">{_e(plan_yr_str)}</span>',
        '<div class="hpills">',
        f'<span class="hpill {"ok" if gt.target_v5_delta_vs_current <= 0 else "warn"}" id="kpi-plan-vs-cur">{_e(plan_vs_cur_str)}</span>',
        f'<span class="hpill {"ok" if gt.target_v5_delta_vs_feb <= 0 else "bad"}" id="kpi-plan-vs-feb">{_e(plan_vs_feb_str)}</span>',
        "</div>",
        "</div>",
        "</section>",
    ]

    if any_ok and gt.resource_count > 0:
        parts.append(_render_executive_brief(report, cur))

    # Streamlined interactive toolbar with collapsible advanced assumptions
    init_mode = report.policy.name
    init_src = report.cost_source
    lm_label = report.last_month_label
    cm_label = report.current_month_label
    checked_dealloc = " checked" if report.include_deallocated_cost else ""
    gen_chips_html = "".join(
        f'<label class="chip"><input type="checkbox" class="gen-mig-check" '
        f'data-gen="{_e(g)}" id="sim-mig-{_e(g)}" checked> {_e(g)} fleet</label>'
        for g in report.generations
    )
    parts += [
        f'<section class="panel" id="hike-simulator" data-symbol="{_e(sym)}" data-initial-mode="{_e(init_mode)}">',
        '<div class="toolbar">',
        '<div class="tgroup">',
        '<label class="ctrl"><strong>Target:</strong> '
        '<select id="sim-target-tier">'
        '<option value="v5-payg" selected>v5 Bridge (PAYG)</option>'
        '<option value="v6-payg">v6 / v7 Strategic (PAYG)</option>'
        '<option value="v5-ri">v5 Bridge + 3-Year RI/SP</option>'
        '<option value="v6-ri">v6 / v7 + 3-Year RI/SP</option>'
        "</select></label>",
        gen_chips_html,
        '<label class="chip"><input type="checkbox" id="sim-shut-idle"> Stop Advisor idle VMs</label>',
        "</div>",
        '<div class="tgroup">',
        '<button type="button" class="btn" data-mig-preset="all">All Legacy</button>',
        '<button type="button" class="btn" data-mig-preset="v1v2">v1 &amp; v2 Only (+25%)</button>',
        '<button type="button" class="btn" data-mig-preset="cheaper-feb">Savings Only</button>',
        '<button type="button" class="btn" data-mig-preset="none">None</button>',
        "</div>",
        "</div>",
        '<details class="adv">',
        "<summary>Assumptions, Cost Baseline &amp; Custom Hike Rules</summary>",
        '<div class="toolbar adv-body">',
        '<div class="tgroup">',
        '<label class="ctrl"><strong>Cost Baseline:</strong> '
        '<select id="sim-cost-source">'
        f'<option value="auto"{" selected" if init_src == "auto" else ""}>'
        f"Actual Billed ({_e(lm_label)} / {_e(cm_label)})</option>"
        f'<option value="last-month"{" selected" if init_src == "last-month" else ""}>'
        f"{_e(lm_label)} Actual Only</option>"
        f'<option value="mtd"{" selected" if init_src == "mtd" else ""}>'
        f"{_e(cm_label)} MTD Extrapolated</option>"
        '<option value="retail-scheduled">Retail \u00d7 Schedule Hrs</option>'
        f'<option value="retail"{" selected" if init_src == "retail" else ""}>'
        f"Retail 24\u00d77 ({report.hours_per_month:g}h)</option>"
        "</select></label>",
        f'<label class="chip"><input type="checkbox" id="sim-dealloc"{checked_dealloc}> +Deallocated (if 24\u00d77)</label>',
        "</div>",
        '<div class="tgroup">',
        '<span class="meta"><strong>Feb 2027 Hike:</strong></span>',
        f'<button type="button" class="btn" data-mode="service-health" '
        f'aria-pressed="{"true" if init_mode == POLICY_SERVICE_HEALTH else "false"}">'
        "Service Health (v1/v2 +25%, v3 Regional)</button>",
        f'<button type="button" class="btn" data-mode="legacy-25" '
        f'aria-pressed="{"true" if init_mode == "legacy-25" else "false"}">All +25%</button>',
        f'<button type="button" class="btn" data-mode="custom" '
        f'aria-pressed="{"true" if init_mode == "custom" else "false"}">Custom</button>',
        f'<label class="ctrl">v1% <input type="number" id="sim-v1" step="0.5" value="{report.policy.v1_hike_pct:g}"></label>',
        f'<label class="ctrl">v2% <input type="number" id="sim-v2" step="0.5" value="{report.policy.v2_hike_pct:g}"></label>',
        f'<label class="ctrl">v3% <input type="number" id="sim-v3" step="0.5" value="{report.policy.v3_hike_pct:g}"></label>',
        "</div>",
        "</div>",
        "</details>",
        "</section>",
    ]

    # Generation summary table (self-explanatory plain-English column headers, compact zero-scroll widths)
    parts += [
        '<section class="panel">',
        '<div class="bar"><h3>By VM Generation</h3></div>',
        '<div class="scroll">',
        "<table>",
        "<thead>",
        '<tr class="group-head">',
        '<th colspan="3">Fleet Footprint</th>',
        '<th class="num g-today">1. Today</th>',
        '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
        '<th colspan="3" class="num g-mig">3. Feb 2027: Migration Plan</th>',
        "</tr>",
        "<tr>",
        _th("Generation", sortable=False),
        _th("Instances (Run / Off)", numeric=True, sortable=False),
        _th("vCPUs", numeric=True, sortable=False),
        _th("Spend Today", numeric=True, sortable=False, title="Current monthly spend before February 2027 price hikes"),
        _th("Unmigrated Spend", numeric=True, sortable=False, title="Projected monthly spend in February 2027 if left on legacy SKUs"),
        _th("Hike Penalty", numeric=True, sortable=False, title="Extra monthly cost added in February 2027 by legacy/regional price hikes"),
        _th("Migrated Spend", numeric=True, sortable=False, title="Projected monthly spend under your selected migration plan above"),
        _th("Saving vs Do Nothing", numeric=True, sortable=False, title="Monthly difference between your Migration Plan and Unmigrated Feb 2027 spend"),
        _th("Migrated + 3Y RI", numeric=True, sortable=False, title="Monthly spend after migrating onto modern v5/v6 SKUs (which unlocks new 3-Year Reserved Instances)"),
        "</tr></thead><tbody>",
    ]
    retire_windows = {
        "v1": "Retires May/Nov 2028 \u00b7 RI Unavailable",
        "v2": "Retires May/Nov 2028 \u00b7 RI Unavailable",
        "v3": "Retires Nov 2029 \u00b7 RI Unavailable",
        "v4": "Regional hike only",
        "v5": "Current generation",
        "v6": "Current generation",
    }
    for gen in report.generations:
        s = by_gen[gen]
        parts.append(_render_gen_tr(gen, s, cur, any_ok, retire_windows.get(gen, ""), is_total=False))
    parts.append(
        _render_gen_tr(
            "Total",
            gt,
            cur,
            any_ok,
            "All selected generations",
            is_total=True,
        )
    )
    parts += ["</tbody></table></div></section>"]

    for index, tenant in enumerate(report.tenants):
        parts.append(_render_tenant_section(report, tenant, index))

    parts += [
        f"<footer>azure-legacy-vm-report {_e(report.version)} &middot; Read-only Azure inventory &amp; Retail Prices model</footer>",
        "</main>",
        f"<script>{SCRIPT}</script>",
        "</body>",
        "</html>",
    ]
    return "\n".join(parts) + "\n"


def _render_gen_tr(
    gen_key: str,
    s: GenerationSummary,
    cur: str,
    available: bool,
    retire_label: str,
    *,
    is_total: bool,
) -> str:
    row_cls = "gen-summary-row total-row" if is_total else "gen-summary-row"
    gen_badge = _badge(gen_key, f"gen-{gen_key}" if not is_total else "accent")
    gen_cell_html = f'<span class="gen-inline">{gen_badge}<span class="meta">{_e(retire_label)}</span></span>'
    if not available:
        cells = [_td("", cls="wrap", html=gen_cell_html)] + [_td("n/a", cls="num dim")] * 8
        return f'<tr class="{row_cls}" data-gen-summary="{_e(gen_key)}">' + "".join(cells) + "</tr>"
    inst_str = f"{s.instance_count} ({s.running_instances} / {s.deallocated_instances})"
    stay_vs_cur = _fmt_hike_cell(s.monthly_delta, s.effective_hike_pct, cur)
    mig_vs_feb = _fmt_net_vs_stay(s.target_v5_delta_vs_feb, s.target_v5_pct_vs_feb, cur)
    cells = [
        _td("", cls="wrap", html=gen_cell_html),
        _td(inst_str, cls="num"),
        _td(s.total_vcpus, cls="num"),
        _td(format_money(s.current_monthly, cur), cls="num c-today", col="cur"),
        _td(format_money(s.feb_monthly, cur), cls="num warn c-stay", col="feb"),
        _td(stay_vs_cur, cls="num bad" if s.monthly_delta > 0.005 else "num dim", col="delta"),
        _td(format_money(s.target_v5_monthly, cur), cls="num ok c-mig", col="v5"),
        _td(
            mig_vs_feb,
            cls="num ok" if s.target_v5_delta_vs_feb < -0.005 else ("num bad" if s.target_v5_delta_vs_feb > 0.005 else "num dim"),
            col="v5save",
        ),
        _td(format_money(s.target_v5_3yr_ri_monthly, cur), cls="num ok", col="v5ri"),
    ]
    return f'<tr class="{row_cls}" data-gen-summary="{_e(gen_key)}">' + "".join(cells) + "</tr>"


def _render_tenant_section(report: Report, tenant: TenantReport, index: int) -> str:
    cur = report.currency
    tid = tenant.tenant_id
    tgroup = f"t-{index}"
    lines = [
        '<section class="panel tenant">',
        '<div class="bar">',
        "<div>",
        f"<h2>{_e(tenant.display_name)}</h2>",
        '<div class="meta">',
        f"<code>{_e(tid)}</code>",
    ]
    if tenant.default_domain:
        lines.append(f" &middot; {_e(tenant.default_domain)}")
    if tenant.data.subscription_count is not None:
        lines.append(f" &middot; {_e(plural(tenant.data.subscription_count, 'subscription'))} visible")
    if tenant.fetched:
        lines.append(f" &middot; {tenant.data.total_resources_scanned} resources scanned")
        lines.append(f" &middot; {len(tenant.records)} legacy deployments")
    lines += ["</div></div>"]

    if tenant.fetched and tenant.records:
        mg_tab_btn = (
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="mgs" '
            f'aria-selected="false">By Management Group ({len(tenant.management_group_rows)})</button>'
            if tenant.management_group_rows
            else ""
        )
        lines += [
            '<div class="tabs">',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="subs" aria-selected="true">By Subscription ({len(tenant.subscription_rows)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="skus" aria-selected="false">By SKU ({len(tenant.sku_rows)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="waves" aria-selected="false">By Wave ({len(tenant.wave_rows)})</button>',
            mg_tab_btn,
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="vms" aria-selected="false">VM Inventory ({len(tenant.records)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="all" aria-selected="false">Show All</button>',
            "</div>",
        ]
    lines.append("</div>")

    if not tenant.fetched:
        lines.append('<p class="empty bad">VM inventory could not be retrieved for this tenant (see notes below).</p>')
    elif not tenant.records:
        lines.append('<p class="empty ok">No legacy v1, v2 or v3 VM SKUs are deployed in this tenant.</p>')
    else:
        # 1. Subscription breakdown table (default open tab — highest signal for owners)
        sub_table_id = f"subs-{index}"
        lines += [
            f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="subs">',
            '<div class="bar">',
            f"<h3>By Subscription ({len(tenant.subscription_rows)} subscriptions)</h3>",
            f'<input type="search" placeholder="Filter subscriptions\u2026" data-filter="{sub_table_id}">',
            "</div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{sub_table_id}">',
            "<thead>",
            '<tr class="group-head">',
            '<th colspan="3">Subscription &amp; Instances</th>',
            '<th class="num g-today">1. Today</th>',
            '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
            '<th colspan="2" class="num g-mig">3. Feb 2027: Migration Plan</th>',
            "</tr>",
            "<tr>",
            _th("Subscription"),
            _th("Instances (v1 / v2 / v3)", numeric=True),
            _th("vCPUs", numeric=True),
            _th("Spend Today / mo", numeric=True),
            _th("Unmigrated / mo", numeric=True),
            _th("Price Hike / mo", numeric=True),
            _th("Migrated / mo", numeric=True),
            _th("Saving vs Doing Nothing", numeric=True),
            "</tr></thead><tbody>",
        ]
        for sub_row in tenant.subscription_rows:
            sub_key = f"{tid}|{sub_row.subscription_id}"
            sub_hike_pct = round((sub_row.monthly_delta / sub_row.current_monthly) * 100.0, 2) if sub_row.current_monthly > 0 else 0.0
            sub_mig_feb = round(sub_row.target_v5_monthly - sub_row.feb_monthly, 2)
            sub_mig_feb_pct = round((sub_mig_feb / sub_row.feb_monthly) * 100.0, 2) if sub_row.feb_monthly > 0 else 0.0
            sub_cell_html = (
                f'<span class="cell-main">{_e(sub_row.subscription_name)}</span>'
                f'<span class="cell-sub">{_e(sub_row.management_group)}</span>'
            )
            inst_breakdown = f"{sub_row.total_instances} ({sub_row.v1_instances} / {sub_row.v2_instances} / {sub_row.v3_instances})"
            lines.append(
                f'<tr class="sub-summary-row" data-sub-key="{_e(sub_key)}">'
                + "".join([
                    _td("", cls="wrap", sort=sub_row.subscription_name, title=sub_row.subscription_id, html=sub_cell_html),
                    _td(inst_breakdown, cls="num", sort=sub_row.total_instances),
                    _td(sub_row.total_vcpus, cls="num", sort=sub_row.total_vcpus),
                    _td(format_money(sub_row.current_monthly, cur), cls="num c-today", sort=f"{sub_row.current_monthly:.2f}", col="cur"),
                    _td(format_money(sub_row.feb_monthly, cur), cls="num warn c-stay", sort=f"{sub_row.feb_monthly:.2f}", col="feb"),
                    _td(
                        _fmt_hike_cell(sub_row.monthly_delta, sub_hike_pct, cur),
                        cls="num bad" if sub_row.monthly_delta > 0.005 else "num dim",
                        sort=f"{sub_row.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td(
                        format_money(sub_row.target_v5_monthly, cur),
                        cls="num ok c-mig",
                        sort=f"{sub_row.target_v5_monthly:.2f}",
                        col="v5",
                    ),
                    _td(
                        _fmt_net_vs_stay(sub_mig_feb, sub_mig_feb_pct, cur),
                        cls="num ok" if sub_mig_feb < -0.005 else ("num bad" if sub_mig_feb > 0.005 else "num dim"),
                        sort=f"{sub_row.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # 2. SKU breakdown table (hidden until clicked, compact 10 columns)
        sku_table_id = f"skus-{index}"
        lines += [
            f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="skus" hidden>',
            '<div class="bar">',
            f"<h3>By Legacy SKU ({len(tenant.sku_rows)} SKUs \u2014 tick/untick to toggle migration)</h3>",
            f'<input type="search" placeholder="Filter SKUs\u2026" data-filter="{sku_table_id}">',
            "</div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{sku_table_id}">',
            "<thead>",
            '<tr class="group-head">',
            '<th colspan="4">Legacy SKU &amp; Footprint</th>',
            '<th class="num g-today">1. Today</th>',
            '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
            '<th colspan="3" class="num g-mig">3. Feb 2027: Migration Plan</th>',
            "</tr>",
            "<tr>",
            _th("Mig", sortable=False),
            _th("Legacy SKU"),
            _th("Inst (Act/Off)", numeric=True),
            _th("vCPUs", numeric=True),
            _th("Spend Today / mo", numeric=True),
            _th("Unmigrated / mo", numeric=True),
            _th("Price Hike / mo", numeric=True),
            _th("Target Modern SKU"),
            _th("Migrated / mo", numeric=True),
            _th("Saving vs Doing Nothing", numeric=True),
            "</tr></thead><tbody>",
        ]
        for srow in tenant.sku_rows:
            sku_key = f"{tid}|{srow.sku}"
            gen_badge = _badge(srow.generation, f"gen-{srow.generation}")
            stay_vs_cur_str = _fmt_hike_cell(srow.monthly_delta, srow.hike_pct, cur)
            mig_vs_feb_str = _fmt_net_vs_stay(srow.target_v5_delta_vs_feb, srow.target_v5_pct_vs_feb, cur)
            sku_cb_html = (
                f'<input type="checkbox" class="sku-mig-check" data-tenant="{_e(tid)}" '
                f'data-sku="{_e(srow.sku)}" checked title="Toggle migration for {_e(srow.sku)}">'
            )
            sku_cell_html = (
                f'<span class="cell-main">{_e(srow.sku)} {gen_badge}</span>'
                f'<span class="cell-sub">{_e(srow.series)} \u00b7 Retires {_e(srow.retirement_date)} \u00b7 {_e(", ".join(srow.regions))}</span>'
            )
            tgt_cell_html = (
                f'<span class="cell-main">{_e(srow.target_v5_sku or srow.recommended_v5)}</span>'
                f'<span class="cell-sub">v6: {_e(srow.target_current_sku or srow.recommended_current)}</span>'
            )
            vs_cur_sub = (
                f"vs Today: {format_money(srow.target_v5_delta_vs_current, cur, signed=True)}"
                if abs(srow.target_v5_delta_vs_current) > 0.005
                else ""
            )
            plan_cell_html = (
                f'<span class="cell-main">{_e(format_money(srow.target_v5_monthly, cur))}</span>'
                f'<span class="cell-sub" data-col="migsub">{_e(vs_cur_sub)}</span>'
            )
            lines.append(
                f'<tr class="sku-summary-row" data-sku-key="{_e(sku_key)}" data-gen="{_e(srow.generation)}">'
                + "".join([
                    _td("", html=sku_cb_html),
                    _td("", cls="wrap", sort=srow.sku, html=sku_cell_html),
                    _td(f"{srow.instance_count} ({srow.running_instances}/{srow.deallocated_instances})", cls="num", sort=srow.instance_count),
                    _td(srow.vcpus_per_instance * srow.instance_count, cls="num", sort=srow.vcpus_per_instance * srow.instance_count),
                    _td(format_money(srow.current_monthly, cur), cls="num c-today", sort=f"{srow.current_monthly:.2f}", col="cur"),
                    _td(format_money(srow.feb_monthly, cur), cls="num warn c-stay", sort=f"{srow.feb_monthly:.2f}", col="feb"),
                    _td(
                        stay_vs_cur_str,
                        cls="num bad" if srow.monthly_delta > 0.005 else "num dim",
                        sort=f"{srow.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td("", sort=srow.target_v5_sku, html=tgt_cell_html),
                    _td(
                        "",
                        cls="num ok c-mig",
                        sort=f"{srow.target_v5_monthly:.2f}",
                        col="v5",
                        html=plan_cell_html,
                    ),
                    _td(
                        mig_vs_feb_str,
                        cls="num ok" if srow.target_v5_delta_vs_feb < -0.005 else ("num bad" if srow.target_v5_delta_vs_feb > 0.005 else "num dim"),
                        sort=f"{srow.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # 3. Migration Wave breakdown table
        if tenant.wave_rows:
            lines += [
                f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="waves" hidden>',
                '<div class="bar"><h3>By Migration Wave</h3></div>',
                '<div class="scroll">',
                "<table>",
                "<thead>",
                '<tr class="group-head">',
                '<th colspan="3">Migration Wave</th>',
                '<th class="num g-today">1. Today</th>',
                '<th class="num g-stay">2. Do Nothing</th>',
                '<th colspan="3" class="num g-mig">3. Feb 2027: Migration Plan</th>',
                "</tr>",
                "<tr>",
                _th("Wave", sortable=False),
                _th("Instances", numeric=True, sortable=False),
                _th("vCPUs", numeric=True, sortable=False),
                _th("Spend Today / mo", numeric=True, sortable=False),
                _th("Unmigrated / mo", numeric=True, sortable=False),
                _th("Migrated / mo", numeric=True, sortable=False),
                _th("Saving vs Doing Nothing", numeric=True, sortable=False),
                _th("Migrated + 3Y RI / mo", numeric=True, sortable=False),
                "</tr></thead><tbody>",
            ]
            for wrow in tenant.wave_rows:
                wkey = f"{tid}|{wrow.wave}"
                w_m_feb = round(wrow.target_v5_monthly - wrow.feb_monthly, 2)
                w_p_feb = round((w_m_feb / wrow.feb_monthly) * 100.0, 2) if wrow.feb_monthly > 0 else 0.0
                lines.append(
                    f'<tr class="wave-summary-row" data-wave-key="{_e(wkey)}">'
                    + "".join([
                        _td(wrow.wave, cls="wrap"),
                        _td(wrow.instance_count, cls="num"),
                        _td(wrow.total_vcpus, cls="num"),
                        _td(format_money(wrow.current_monthly, cur), cls="num c-today", col="cur"),
                        _td(format_money(wrow.feb_monthly, cur), cls="num warn c-stay", col="feb"),
                        _td(format_money(wrow.target_v5_monthly, cur), cls="num ok c-mig", col="v5"),
                        _td(
                            _fmt_net_vs_stay(w_m_feb, w_p_feb, cur),
                            cls="num ok" if w_m_feb < -0.005 else ("num bad" if w_m_feb > 0.005 else "num dim"),
                            col="v5save",
                        ),
                        _td(format_money(wrow.target_v5_3yr_ri_monthly, cur), cls="num ok", col="v5ri"),
                    ])
                    + "</tr>"
                )
            lines += ["</tbody></table></div></div>"]

        # 4. Management Group breakdown table
        if tenant.management_group_rows:
            mg_table_id = f"mgs-{index}"
            lines += [
                f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="mgs" hidden>',
                '<div class="bar">',
                f"<h3>By Management Group ({len(tenant.management_group_rows)} groups)</h3>",
                f'<input type="search" placeholder="Filter management groups\u2026" data-filter="{mg_table_id}">',
                "</div>",
                '<div class="scroll">',
                f'<table class="sortable" id="{mg_table_id}">',
                "<thead>",
                '<tr class="group-head">',
                '<th colspan="4">Management Group &amp; Footprint</th>',
                '<th class="num g-today">1. Today</th>',
                '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
                '<th colspan="2" class="num g-mig">3. Feb 2027: Migration Plan</th>',
                "</tr>",
                "<tr>",
                _th("Management Group"),
                _th("Subscriptions", numeric=True),
                _th("Instances", numeric=True),
                _th("vCPUs", numeric=True),
                _th("Spend Today / mo", numeric=True),
                _th("Unmigrated / mo", numeric=True),
                _th("Price Hike / mo", numeric=True),
                _th("Migrated / mo", numeric=True),
                _th("Saving vs Doing Nothing", numeric=True),
                "</tr></thead><tbody>",
            ]
            for mg_row in tenant.management_group_rows:
                mg_key = f"{tid}|{mg_row.management_group}"
                mg_hike_pct = (
                    round((mg_row.monthly_delta / mg_row.current_monthly) * 100.0, 2)
                    if mg_row.current_monthly > 0
                    else 0.0
                )
                mg_mig_feb = round(mg_row.target_v5_monthly - mg_row.feb_monthly, 2)
                mg_mig_feb_pct = (
                    round((mg_mig_feb / mg_row.feb_monthly) * 100.0, 2)
                    if mg_row.feb_monthly > 0
                    else 0.0
                )
                lines.append(
                    f'<tr class="mg-summary-row" data-mg-key="{_e(mg_key)}">'
                    + "".join([
                        _td(mg_row.management_group, cls="wrap", sort=mg_row.management_group),
                        _td(mg_row.subscription_count, cls="num", sort=mg_row.subscription_count),
                        _td(mg_row.total_instances, cls="num", sort=mg_row.total_instances),
                        _td(mg_row.total_vcpus, cls="num", sort=mg_row.total_vcpus),
                        _td(
                            format_money(mg_row.current_monthly, cur),
                            cls="num c-today",
                            sort=f"{mg_row.current_monthly:.2f}",
                            col="cur",
                        ),
                        _td(
                            format_money(mg_row.feb_monthly, cur),
                            cls="num warn c-stay",
                            sort=f"{mg_row.feb_monthly:.2f}",
                            col="feb",
                        ),
                        _td(
                            _fmt_hike_cell(mg_row.monthly_delta, mg_hike_pct, cur),
                            cls="num bad" if mg_row.monthly_delta > 0.005 else "num dim",
                            sort=f"{mg_row.monthly_delta:.2f}",
                            col="delta",
                        ),
                        _td(
                            format_money(mg_row.target_v5_monthly, cur),
                            cls="num ok c-mig",
                            sort=f"{mg_row.target_v5_monthly:.2f}",
                            col="v5",
                        ),
                        _td(
                            _fmt_net_vs_stay(mg_mig_feb, mg_mig_feb_pct, cur),
                            cls="num ok" if mg_mig_feb < -0.005 else ("num bad" if mg_mig_feb > 0.005 else "num dim"),
                            sort=f"{mg_row.target_v5_savings_vs_feb:.2f}",
                            col="v5save",
                        ),
                    ])
                    + "</tr>"
                )
            lines += ["</tbody></table></div></div>"]

        # 5. VM inventory table (hidden until clicked, with 1-click Hiked & Active noise filters)
        vm_table_id = f"vms-{index}"
        gen_options_html = '<option value="">All generations</option>' + "".join(
            f'<option value="{_e(g)}">{_e(g)} only</option>' for g in report.generations
        )
        lines += [
            f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="vms" hidden>',
            '<div class="bar">',
            f'<h3>VM &amp; Scale Set Inventory (<span data-count-for="{vm_table_id}">{len(tenant.records)} items</span>)</h3>',
            '<div class="controls">',
            f'<label class="chip"><input type="checkbox" data-hiked-filter="{vm_table_id}"> Hiked (&gt;{_e(currency_symbol(cur))}0) only</label>',
            f'<label class="chip"><input type="checkbox" data-active-filter="{vm_table_id}"> Active only</label>',
            f'<select data-gen-filter="{vm_table_id}">{gen_options_html}</select>',
            f'<input type="search" placeholder="Search VM, SKU, subscription, RG\u2026" data-filter="{vm_table_id}">',
            "</div></div>",
            '<div class="scroll">',
            f'<table class="sortable vm-tbl" id="{vm_table_id}">',
            "<thead>",
            '<tr class="group-head">',
            '<th colspan="3">Resource &amp; Legacy Config</th>',
            '<th class="num g-today">1. Today</th>',
            '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
            '<th colspan="3" class="num g-mig">3. Feb 2027: Migration Plan</th>',
            '<th>Alerts</th>',
            "</tr>",
            "<tr>",
            _th("Mig", sortable=False),
            _th("Resource"),
            _th("Legacy SKU &amp; State"),
            _th("Spend Today", numeric=True),
            _th("Unmigrated", numeric=True),
            _th("Hike Penalty", numeric=True),
            _th("Target Modern SKU"),
            _th("Migrated", numeric=True),
            _th("Saving vs Do Nothing", numeric=True),
            _th("Signals"),
            "</tr></thead><tbody>",
        ]
        for rec in tenant.records:
            name_label = f"{rec.name} (\u00d7{rec.instance_count})" if rec.resource_type == TYPE_VMSS else rec.name
            gen_badge = _badge(rec.generation, f"gen-{rec.generation}")
            os_short = f"{rec.os_type} AHB" if rec.hybrid_benefit else rec.os_type
            state_badge = _badge(
                "Off" if rec.power_state == POWER_DEALLOCATED else "Run",
                "dim" if rec.power_state == POWER_DEALLOCATED else "ok",
            )
            hrs_str = ""
            if rec.actual_last_month_hours is not None and rec.actual_last_month_hours > 0:
                hrs_str = f"{rec.actual_last_month_hours:.0f}h"
            elif rec.actual_mtd_hours is not None and rec.actual_mtd_hours > 0:
                hrs_str = f"{rec.actual_mtd_hours:.0f}h MTD"
            elif rec.inferred_hours_per_month < rec.hours_per_month:
                hrs_str = f"~{rec.inferred_hours_per_month:.0f}h"
            sched_sort = (
                rec.actual_last_month_hours
                if rec.actual_last_month_hours is not None
                else rec.inferred_hours_per_month
            )

            billed_flag = "1" if rec.is_billed_now else "0"
            has_cm_flag = "1" if rec.actual_last_month_cost is not None else "0"
            lm_val = rec.actual_last_month_cost if rec.actual_last_month_cost is not None else 0.0
            mtd_ext_val = rec.actual_mtd_extrapolated_cost if rec.actual_mtd_extrapolated_cost is not None else 0.0
            v5_ratio = (rec.target_v5_hourly_rate / rec.hourly_rate) if rec.hourly_rate > 0 else 1.0
            v6_ratio = (rec.target_current_hourly_rate / rec.hourly_rate) if rec.hourly_rate > 0 else (v5_ratio * 1.04)
            reg_pct = REGIONAL_FEB_2027_HIKES.get(rec.region, 0.0)
            idle_flag = "1" if "shut down idle vm" in rec.advisor_recommendation.lower() else "0"

            res_cell_html = (
                f'<span class="cell-main">{_e(name_label)}</span>'
                f'<span class="cell-sub">{_e(rec.subscription_name)} \u00b7 {_e(rec.resource_group)} \u00b7 {_e(rec.region)}</span>'
            )
            sku_sub_parts = [f"{rec.total_vcpus} vCPU", _e(os_short), f"{_e(format_hourly(rec.hourly_rate, cur))}/hr"]
            if hrs_str:
                sku_sub_parts.append(_e(hrs_str))
            if rec.auto_shutdown_schedule:
                sku_sub_parts.append(_e(rec.auto_shutdown_schedule))
            sku_sub_joined = " \u00b7 ".join(sku_sub_parts)
            sku_cell_html = (
                f'<span class="cell-main">{_e(rec.sku)} {gen_badge} {state_badge}</span>'
                f'<span class="cell-sub">{sku_sub_joined}</span>'
            )
            wave_short = rec.migration_wave.split(":", 1)[0] if ":" in rec.migration_wave else rec.migration_wave
            tgt_cell_html = (
                f'<span class="cell-main" data-col="tgtsku">{_e(rec.target_v5_sku or rec.recommended_v5)}</span>'
                f'<span class="cell-sub">{_e(wave_short)} \u00b7 {_e(rec.deployment_kind)}</span>'
            )

            # Only show actionable exceptions — never clutter healthy rows with 'Quota OK' pills
            sig_badges = []
            if idle_flag == "1":
                sig_badges.append(_badge("Advisor: Idle", "warn"))
            elif rec.advisor_recommendation:
                sig_badges.append(_badge("Advisor: Right-size", "warn"))
            if "RI Covered" in rec.ri_status or "Partial RI" in rec.ri_status:
                sig_badges.append(_badge("RI Covered", "ok"))
            if "Increase Needed" in rec.quota_status or "Quota 0/" in rec.quota_status:
                sig_badges.append(_badge("Quota Uplift", "bad"))
            sig_html = " ".join(sig_badges) if sig_badges else '<span class="dim">\u2014</span>'

            stay_vs_cur_str = _fmt_hike_cell(rec.monthly_delta, rec.hike_pct, cur)
            rec_mig_vs_feb = _fmt_net_vs_stay(rec.target_v5_delta_vs_feb, rec.target_v5_pct_vs_feb, cur)
            vs_cur_sub = (
                f"vs Today: {format_money(rec.target_v5_delta_vs_current, cur, signed=True)}"
                if abs(rec.target_v5_delta_vs_current) > 0.005
                else ""
            )
            plan_cell_html = (
                f'<span class="cell-main">{_e(format_money(rec.target_v5_monthly, cur))}</span>'
                f'<span class="cell-sub" data-col="migsub">{_e(vs_cur_sub)}</span>'
            )
            vm_cb_html = '<input type="checkbox" class="vm-mig-check" checked title="Include this VM in migration">'
            sig_title_parts = [p for p in (rec.advisor_recommendation, rec.quota_status, rec.cost_breakdown_note) if p]

            lines.append(
                f'<tr class="vm-row" data-tenant="{_e(tid)}" data-sub="{_e(rec.subscription_id)}" '
                f'data-mg="{_e(rec.management_group)}" '
                f'data-sku="{_e(rec.sku)}" data-gen="{_e(rec.generation)}" '
                f'data-wave="{_e(rec.migration_wave)}" data-inst="{rec.instance_count}" '
                f'data-idle="{idle_flag}" data-live-delta="{rec.monthly_delta:.2f}" '
                f'data-v5-sku="{_e(rec.target_v5_sku or rec.recommended_v5)}" '
                f'data-v6-sku="{_e(rec.target_current_sku or rec.recommended_current)}" '
                f'data-prov-cur="{rec.provisioned_current_monthly:.2f}" '
                f'data-sched-cur="{rec.schedule_adjusted_monthly:.2f}" '
                f'data-has-cm="{has_cm_flag}" data-lm-cost="{lm_val:.2f}" data-mtd-ext="{mtd_ext_val:.2f}" '
                f'data-billed="{billed_flag}" data-sh-pct="{rec.service_health_hike_pct:.2f}" '
                f'data-reg-pct="{reg_pct:.2f}" '
                f'data-v5-ratio="{v5_ratio:.4f}" data-v6-ratio="{v6_ratio:.4f}" '
                f'data-v5-ri-24x7="{rec.target_v5_3yr_ri_24x7_monthly:.2f}" '
                f'data-v6-ri-24x7="{rec.target_current_3yr_ri_24x7_monthly:.2f}">'
                + "".join([
                    _td("", html=vm_cb_html),
                    _td("", cls="wrap", sort=rec.name, title=rec.resource_id, html=res_cell_html),
                    _td("", cls="wrap", sort=rec.sku, html=sku_cell_html),
                    _td(format_money(rec.current_monthly, cur), cls="num c-today", sort=f"{rec.current_monthly:.2f}", col="cur"),
                    _td(format_money(rec.feb_monthly, cur), cls="num warn c-stay", sort=f"{rec.feb_monthly:.2f}", col="feb"),
                    _td(
                        stay_vs_cur_str,
                        cls="num bad" if rec.monthly_delta > 0.005 else "num dim",
                        sort=f"{rec.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td("", cls="wrap", sort=rec.target_v5_sku, title=f"{rec.migration_cli_hint} ({rec.disk_controller_note})", html=tgt_cell_html),
                    _td(
                        "",
                        cls="num ok c-mig",
                        sort=f"{rec.target_v5_monthly:.2f}",
                        col="v5",
                        html=plan_cell_html,
                    ),
                    _td(
                        rec_mig_vs_feb,
                        cls="num ok" if rec.target_v5_delta_vs_feb < -0.005 else ("num bad" if rec.target_v5_delta_vs_feb > 0.005 else "num dim"),
                        sort=f"{rec.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                    _td("", cls="wrap", title=" | ".join(sig_title_parts), html=sig_html),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

    visible_issues = [iss for iss in tenant.issues if iss.feature != "negotiated-discount"]
    if visible_issues:
        lines.append('<div class="block"><h3>Notes</h3>')
        for issue in visible_issues:
            label, style = _LEVEL_LABELS.get(issue.level, ("Note", "dim"))
            lines.append(
                f'<div class="note">{_badge(label, style)} '
                f"<strong>[{_e(issue.feature)}]</strong> {_e(issue.message)}</div>"
            )
        lines.append("</div>")

    lines.append("</section>")
    return "\n".join(lines)
