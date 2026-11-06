"""Self-contained interactive HTML report with CSP hashing, sorting, filtering and live February 2027 hike modelling."""

from __future__ import annotations

import base64
import hashlib
from html import escape
from typing import List, Optional

from .collect import LEVEL_ERROR, LEVEL_INFO, LEVEL_WARNING
from .dates import format_datetime
from .model import POWER_DEALLOCATED, TYPE_VMSS
from .pricing import POLICY_SERVICE_HEALTH
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
body{margin:0;min-height:100vh;color:var(--text);font:13.5px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:radial-gradient(1100px 620px at 12% -8%,rgba(180,85,255,.18),transparent 62%),radial-gradient(900px 560px at 108% 4%,rgba(255,79,209,.10),transparent 58%),linear-gradient(180deg,#0a0b16,#0c0d1d);background-attachment:fixed}
main{max-width:1440px;margin:0 auto;padding:16px 16px 28px;display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
h1{margin:0;font-size:20px;letter-spacing:.2px}
h1 span{background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin:0;font-size:16px}
h3{margin:0;font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
p{margin:0}
.sub{color:var(--muted);margin-top:3px;font-size:12.5px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.banner{border-color:rgba(255,180,84,.45);color:var(--warn);background:rgba(255,180,84,.07)}
.hero{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.hcard{padding:14px 16px;border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.025);display:flex;flex-direction:column;gap:6px}
.hcard.stay{border-color:rgba(255,92,122,.35);background:linear-gradient(180deg,rgba(255,92,122,.07),rgba(255,255,255,.02))}
.hcard.mig{border-color:rgba(61,220,151,.38);background:linear-gradient(180deg,rgba(61,220,151,.08),rgba(255,255,255,.02))}
.hcard .kicker{font-size:11.5px;font-weight:650;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.hcard .big{font-size:28px;font-weight:750;line-height:1.1;font-variant-numeric:tabular-nums}
.hcard .yr{font-size:12.5px;color:var(--muted);font-variant-numeric:tabular-nums}
.hpills{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.hpill{padding:4px 9px;border-radius:8px;font-size:12px;font-weight:600;background:rgba(255,255,255,.05);border:1px solid var(--line);font-variant-numeric:tabular-nums}
.hpill.bad{background:rgba(255,92,122,.13);border-color:rgba(255,92,122,.4);color:#ff8fa3}
.hpill.ok{background:rgba(61,220,151,.13);border-color:rgba(61,220,151,.4);color:#66e8b1}
.hpill.warn{background:rgba(255,180,84,.13);border-color:rgba(255,180,84,.4);color:#ffc97e}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px}
.tgroup{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.chip{display:inline-flex;align-items:center;gap:5px;padding:4px 9px;border-radius:8px;border:1px solid var(--line);background:rgba(255,255,255,.04);font-size:12px;cursor:pointer;user-select:none}
.chip:hover{border-color:var(--accent)}
.chip input{margin:0;accent-color:var(--accent)}
.btn{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);border-radius:7px;padding:4px 9px;font:12px/1.3 inherit;cursor:pointer}
.btn:hover{border-color:var(--accent)}
.btn[aria-pressed=true]{background:rgba(180,85,255,.2);border-color:var(--accent);color:#fff;font-weight:600}
label.ctrl{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:var(--muted)}
input[type=number],select{background:#14162b;border:1px solid var(--line);color:var(--text);border-radius:7px;padding:4px 7px;width:58px;font:12px inherit;font-variant-numeric:tabular-nums}
select{width:auto}
input[type=search]{background:#14162b;border:1px solid var(--line);color:var(--text);border-radius:8px;padding:5px 10px;min-width:210px;font:12.5px inherit}
input:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px}
.tenant{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.meta{color:var(--muted);font-size:12px}
.meta code{color:var(--text);background:rgba(255,255,255,.06);padding:1px 6px;border-radius:6px}
.block{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:rgba(255,255,255,.018)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;justify-content:space-between;margin-bottom:8px}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.tabs{display:flex;flex-wrap:wrap;gap:6px}
.tab-btn{background:rgba(255,255,255,.04);border:1px solid var(--line);color:var(--muted);border-radius:8px;padding:5px 12px;font:600 12px/1.3 inherit;cursor:pointer}
.tab-btn:hover{color:var(--text);border-color:var(--accent)}
.tab-btn[aria-selected=true]{background:rgba(180,85,255,.18);border-color:var(--accent);color:#fff}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th,td{padding:6px 8px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line);vertical-align:middle}
td.wrap{white-space:normal;min-width:140px}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
thead tr.group-head th{padding:4px 8px;font-size:10.5px;letter-spacing:.08em;border-bottom:1px solid rgba(255,255,255,.14)}
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
.cell-main{display:block;font-weight:600;color:var(--text)}
.cell-sub{display:block;font-size:11px;color:var(--muted);margin-top:1px}
.badge{display:inline-block;padding:0 7px;border-radius:999px;font-size:11px;border:1px solid currentColor;line-height:1.5}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.dim{color:var(--muted)}.accent{color:var(--accent)}
.gen-v1{color:var(--bad)}.gen-v2{color:var(--warn)}.gen-v3{color:var(--accent2)}
.note{padding:5px 0;border-bottom:1px solid var(--line);font-size:12px}
.note:last-child{border-bottom:0}
.empty{color:var(--muted);padding:6px 0}
footer{color:var(--muted);font-size:11.5px;text-align:center}
@media (max-width:960px){.hero{grid-template-columns:1fr}}
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
    });
  });

  function applyFilters(tableId) {
    var table = document.getElementById(tableId);
    if (!table) { return; }
    var searchInput = document.querySelector('input[data-filter="' + tableId + '"]');
    var genSelect = document.querySelector('select[data-gen-filter="' + tableId + '"]');
    var query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    var gen = genSelect ? genSelect.value : '';
    Array.prototype.forEach.call(table.tBodies[0].rows, function (row) {
      var rowGen = row.getAttribute('data-gen') || '';
      var matchGen = !gen || rowGen === gen;
      var matchText = !query || row.textContent.toLowerCase().indexOf(query) !== -1;
      row.hidden = !(matchGen && matchText);
    });
  }

  document.querySelectorAll('input[data-filter]').forEach(function (input) {
    var id = input.getAttribute('data-filter');
    input.addEventListener('input', function () { applyFilters(id); });
  });
  document.querySelectorAll('select[data-gen-filter]').forEach(function (sel) {
    var id = sel.getAttribute('data-gen-filter');
    sel.addEventListener('change', function () { applyFilters(id); });
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
  var migV1Check = document.getElementById('sim-mig-v1');
  var migV2Check = document.getElementById('sim-mig-v2');
  var migV3Check = document.getElementById('sim-mig-v3');
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
    var pct = base > 0 ? (delta / base) * 100 : 0;
    return fmtMoney(delta, true) + ' (' + fmtPct(pct) + ')';
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

  function resolveTargetRatio(row, tier) {
    if (tier === 'v6-payg') {
      return parseFloat(row.getAttribute('data-v6-ratio') || row.getAttribute('data-v5-ratio') || '1');
    }
    if (tier === 'v5-ri') {
      return parseFloat(row.getAttribute('data-v5-ri-ratio') || '0.55');
    }
    if (tier === 'v6-ri') {
      return parseFloat(row.getAttribute('data-v6-ri-ratio') || row.getAttribute('data-v5-ri-ratio') || '0.58');
    }
    return parseFloat(row.getAttribute('data-v5-ratio') || '1');
  }

  function resolveTargetSkuName(row, tier) {
    var v5Sku = row.getAttribute('data-v5-sku') || '';
    var v6Sku = row.getAttribute('data-v6-sku') || v5Sku;
    if (tier === 'v6-payg') { return v6Sku; }
    if (tier === 'v5-ri') { return v5Sku + ' (3Y RI)'; }
    if (tier === 'v6-ri') { return v6Sku + ' (3Y RI)'; }
    return v5Sku;
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
      v1: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 },
      v2: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 },
      v3: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 },
      v4: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 },
      v5: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 },
      v6: { cur: 0, feb: 0, v5: 0, v5ri: 0, blended: 0 }
    };
    var skuStats = {};
    var subStats = {};
    var waveStats = {};
    var totalCur = 0, totalFeb = 0, totalV5 = 0, totalV5Ri = 0, totalBlended = 0;
    var migratedCount = 0, stayedCount = 0, idleShutCount = 0;

    vmRows.forEach(function (row) {
      var gen = row.getAttribute('data-gen') || 'v3';
      var sku = row.getAttribute('data-sku') || '';
      var sub = row.getAttribute('data-sub') || '';
      var wave = row.getAttribute('data-wave') || '';
      var tenant = row.getAttribute('data-tenant') || '';
      var shPct = parseFloat(row.getAttribute('data-sh-pct') || '0');
      var instCount = parseInt(row.getAttribute('data-inst') || '1', 10) || 1;
      var isIdle = row.getAttribute('data-idle') === '1';
      var vmCheck = row.querySelector('input.vm-mig-check');
      var isMigrated = vmCheck ? vmCheck.checked : true;

      var cur = resolveBaseline(row, costSource, includeDealloc);
      var pct = 0;
      if (currentMode === 'service-health') {
        pct = shPct;
      } else {
        pct = gen === 'v1' ? v1Pct : (gen === 'v2' ? v2Pct : v3Pct);
      }
      var feb = cur * (1 + pct / 100);
      var delta = feb - cur;

      var tgtRatio = resolveTargetRatio(row, tier);
      var v5RiRatio = parseFloat(row.getAttribute('data-v5-ri-ratio') || '0.55');
      var tgtMo = cur * tgtRatio;
      var v5RiMo = cur * v5RiRatio;
      if (shutIdle && isIdle) {
        tgtMo = 0;
        v5RiMo = 0;
      }

      var deltaVsCur = tgtMo - cur;
      var pctVsCur = cur > 0 ? (deltaVsCur / cur) * 100 : ((tgtRatio - 1) * 100);
      var deltaVsFeb = tgtMo - feb;
      var pctVsFeb = feb > 0 ? (deltaVsFeb / feb) * 100 : 0;
      var saveVsFeb = feb - tgtMo;
      var chosenMo = (shutIdle && isIdle) ? 0 : (isMigrated ? tgtMo : feb);

      if (shutIdle && isIdle) {
        idleShutCount += instCount;
      } else if (isMigrated) {
        migratedCount += instCount;
      } else {
        stayedCount += instCount;
      }

      var tgtSkuLabel = resolveTargetSkuName(row, tier);
      var curCell = row.querySelector('[data-col="cur"]');
      var febCell = row.querySelector('[data-col="feb"]');
      var deltaCell = row.querySelector('[data-col="delta"]');
      var pctCell = row.querySelector('[data-col="pct"]');
      var tgtSkuCell = row.querySelector('[data-col="tgtsku"]');
      var v5Cell = row.querySelector('[data-col="v5"]');
      var migCurCell = row.querySelector('[data-col="migcur"]');
      var v5SaveCell = row.querySelector('[data-col="v5save"]');
      var breakdownCell = row.querySelector('[data-col="breakdown"]');

      if (curCell) { curCell.textContent = fmtMoney(cur, false); curCell.setAttribute('data-sort', cur.toFixed(2)); }
      if (febCell) { febCell.textContent = fmtMoney(feb, false); febCell.setAttribute('data-sort', feb.toFixed(2)); }
      if (deltaCell) { deltaCell.textContent = fmtMoney(delta, true); deltaCell.setAttribute('data-sort', delta.toFixed(2)); }
      if (pctCell) { pctCell.textContent = fmtPct(pct); pctCell.setAttribute('data-sort', pct.toFixed(2)); }
      if (tgtSkuCell) { tgtSkuCell.textContent = tgtSkuLabel; }
      if (v5Cell) { v5Cell.textContent = fmtMoney(tgtMo, false); v5Cell.setAttribute('data-sort', tgtMo.toFixed(2)); }
      if (migCurCell) {
        migCurCell.textContent = fmtDeltaAndPct(deltaVsCur, cur);
        migCurCell.setAttribute('data-sort', deltaVsCur.toFixed(2));
        migCurCell.className = 'num ' + (deltaVsCur < -0.01 ? 'ok' : (deltaVsCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5SaveCell) {
        v5SaveCell.textContent = fmtDeltaAndPct(deltaVsFeb, feb);
        v5SaveCell.setAttribute('data-sort', saveVsFeb.toFixed(2));
        v5SaveCell.className = 'num ' + (deltaVsFeb < -0.01 ? 'ok' : (deltaVsFeb > 0.01 ? 'bad' : 'dim'));
      }
      if (breakdownCell) {
        breakdownCell.textContent = buildPlainBreakdown(sku, tgtSkuLabel, pct, pctVsCur, pctVsFeb, deltaVsCur, deltaVsFeb);
      }

      if (genStats[gen]) {
        genStats[gen].cur += cur; genStats[gen].feb += feb;
        genStats[gen].v5 += tgtMo; genStats[gen].v5ri += v5RiMo;
        genStats[gen].blended += chosenMo;
      }
      totalCur += cur; totalFeb += feb; totalV5 += tgtMo; totalV5Ri += v5RiMo; totalBlended += chosenMo;

      var skuKey = tenant + '|' + sku;
      if (!skuStats[skuKey]) { skuStats[skuKey] = { cur: 0, feb: 0, v5: 0, pct: pct }; }
      skuStats[skuKey].cur += cur; skuStats[skuKey].feb += feb; skuStats[skuKey].v5 += tgtMo;

      var subKey = tenant + '|' + sub;
      if (!subStats[subKey]) { subStats[subKey] = { cur: 0, feb: 0, v5: 0 }; }
      subStats[subKey].cur += cur; subStats[subKey].feb += feb; subStats[subKey].v5 += tgtMo;

      var waveKey = tenant + '|' + wave;
      if (!waveStats[waveKey]) { waveStats[waveKey] = { cur: 0, feb: 0, v5: 0, v5ri: 0 }; }
      waveStats[waveKey].cur += cur; waveStats[waveKey].feb += feb;
      waveStats[waveKey].v5 += tgtMo; waveStats[waveKey].v5ri += v5RiMo;
    });

    var totalDelta = totalFeb - totalCur;
    var totalYrDelta = totalDelta * 12;
    var totalPct = totalCur > 0 ? (totalDelta / totalCur) * 100 : 0;
    var totalV5Save = totalFeb - totalV5;
    var totalV5RiSave = totalFeb - totalV5Ri;
    var totalMigVsCur = totalV5 - totalCur;
    var totalMigVsCurPct = totalCur > 0 ? (totalMigVsCur / totalCur) * 100 : 0;
    var totalMigVsFeb = totalV5 - totalFeb;
    var totalMigVsFebPct = totalFeb > 0 ? (totalMigVsFeb / totalFeb) * 100 : 0;
    var blendedVsCur = totalBlended - totalCur;
    var blendedVsCurPct = totalCur > 0 ? (blendedVsCur / totalCur) * 100 : 0;
    var blendedVsFeb = totalBlended - totalFeb;
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

    if (kpiPlanMo) { kpiPlanMo.textContent = fmtMoney(totalBlended, false) + ' / mo'; }
    if (kpiPlanYr) {
      var idleSuffix = idleShutCount > 0 ? (' · ' + idleShutCount + ' idle stopped') : '';
      kpiPlanYr.textContent = fmtMoney(totalBlended * 12, false) + ' / yr · ' + migratedCount + ' migrated, ' + stayedCount + ' staying' + idleSuffix;
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
      var st = g === 'Total' ? { cur: totalCur, feb: totalFeb, v5: totalV5, v5ri: totalV5Ri } : genStats[g];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mCur = st.v5 - st.cur;
      var mFeb = st.v5 - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      var v5riEl = row.querySelector('[data-col="v5ri"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); }
      if (dEl) { dEl.textContent = fmtDeltaAndPct(d, st.cur); }
      if (v5El) { v5El.textContent = fmtMoney(st.v5, false); }
      if (mCurEl) { mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur); }
      if (v5sEl) { v5sEl.textContent = fmtDeltaAndPct(mFeb, st.feb); }
      if (v5riEl) { v5riEl.textContent = fmtMoney(st.v5ri, false); }
    });

    document.querySelectorAll('tr.sku-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sku-key');
      var st = skuStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mCur = st.v5 - st.cur;
      var mFeb = st.v5 - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) { dEl.textContent = fmtDeltaAndPct(d, st.cur); dEl.setAttribute('data-sort', d.toFixed(2)); }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
      if (v5El) { v5El.textContent = fmtMoney(st.v5, false); v5El.setAttribute('data-sort', st.v5.toFixed(2)); }
      if (mCurEl) {
        mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur);
        mCurEl.setAttribute('data-sort', mCur.toFixed(2));
        mCurEl.className = 'num ' + (mCur < -0.01 ? 'ok' : (mCur > 0.01 ? 'warn' : 'dim'));
      }
      if (v5sEl) {
        v5sEl.textContent = fmtDeltaAndPct(mFeb, st.feb);
        v5sEl.setAttribute('data-sort', (-mFeb).toFixed(2));
        v5sEl.className = 'num ' + (mFeb < -0.01 ? 'ok' : (mFeb > 0.01 ? 'bad' : 'dim'));
      }
    });

    document.querySelectorAll('tr.sub-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sub-key');
      var st = subStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var mFeb = st.v5 - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) { dEl.textContent = fmtDeltaAndPct(d, st.cur); dEl.setAttribute('data-sort', d.toFixed(2)); }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
      if (v5El) { v5El.textContent = fmtMoney(st.v5, false); v5El.setAttribute('data-sort', st.v5.toFixed(2)); }
      if (v5sEl) { v5sEl.textContent = fmtDeltaAndPct(mFeb, st.feb); v5sEl.setAttribute('data-sort', (-mFeb).toFixed(2)); }
    });

    document.querySelectorAll('tr.wave-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-wave-key');
      var st = waveStats[key];
      if (!st) { return; }
      var mCur = st.v5 - st.cur;
      var mFeb = st.v5 - st.feb;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var v5El = row.querySelector('[data-col="v5"]');
      var mCurEl = row.querySelector('[data-col="migcur"]');
      var v5sEl = row.querySelector('[data-col="v5save"]');
      var v5riEl = row.querySelector('[data-col="v5ri"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); }
      if (v5El) { v5El.textContent = fmtMoney(st.v5, false); }
      if (mCurEl) { mCurEl.textContent = fmtDeltaAndPct(mCur, st.cur); }
      if (v5sEl) { v5sEl.textContent = fmtDeltaAndPct(mFeb, st.feb); }
      if (v5riEl) { v5riEl.textContent = fmtMoney(st.v5ri, false); }
    });
  }

  function syncGenChecksToRows(gen, checked) {
    document.querySelectorAll('tr.vm-row[data-gen="' + gen + '"] input.vm-mig-check').forEach(function (cb) {
      cb.checked = checked;
    });
    document.querySelectorAll('tr.sku-summary-row[data-gen="' + gen + '"] input.sku-mig-check').forEach(function (cb) {
      cb.checked = checked;
    });
    recalc();
  }

  if (migV1Check) { migV1Check.addEventListener('change', function () { syncGenChecksToRows('v1', migV1Check.checked); }); }
  if (migV2Check) { migV2Check.addEventListener('change', function () { syncGenChecksToRows('v2', migV2Check.checked); }); }
  if (migV3Check) { migV3Check.addEventListener('change', function () { syncGenChecksToRows('v3', migV3Check.checked); }); }
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
      recalc();
    });
  });

  document.querySelectorAll('input.vm-mig-check').forEach(function (vmCb) {
    vmCb.addEventListener('change', recalc);
  });

  presetButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var preset = btn.getAttribute('data-mig-preset');
      var tier = targetTierSelect ? targetTierSelect.value : 'v5-payg';
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
          var shPct = parseFloat(row.getAttribute('data-sh-pct') || '0');
          var pct = currentMode === 'service-health' ? shPct : (gen === 'v1' ? v1Pct : (gen === 'v2' ? v2Pct : v3Pct));
          var febMult = 1 + pct / 100;
          var tgtRatio = resolveTargetRatio(row, tier);
          cb.checked = (tgtRatio <= febMult + 0.0001);
        }
      });
      document.querySelectorAll('tr.sku-summary-row').forEach(function (srow) {
        var sCb = srow.querySelector('input.sku-mig-check');
        if (!sCb) { return; }
        var sGen = srow.getAttribute('data-gen') || 'v3';
        if (preset === 'all') { sCb.checked = true; }
        else if (preset === 'none') { sCb.checked = false; }
        else if (preset === 'v1v2') { sCb.checked = (sGen === 'v1' || sGen === 'v2'); }
        else { sCb.checked = true; }
      });
      if (migV1Check) { migV1Check.checked = (preset !== 'none'); }
      if (migV2Check) { migV2Check.checked = (preset !== 'none'); }
      if (migV3Check) { migV3Check.checked = (preset === 'all' || preset === 'cheaper-feb'); }
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


def _th(label: str, *, numeric: bool = False, sortable: bool = True) -> str:
    cls = ' class="num"' if numeric else ""
    inner = f'<button type="button">{_e(label)}</button>' if sortable else _e(label)
    return f"<th{cls}>{inner}</th>"


def _badge(text: str, style: Optional[str]) -> str:
    return f'<span class="badge {style or "dim"}">{_e(text)}</span>'


def _stat(value: object, label: str, *, value_id: str = "", cls: str = "") -> str:
    id_attr = f' id="{_e(value_id)}"' if value_id else ""
    cls_attr = f"n {cls}".strip()
    return f'<div class="stat"><span class="{cls_attr}"{id_attr}>{_e(value)}</span><span class="l">{_e(label)}</span></div>'


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

    # Compact 2-row interactive toolbar
    init_mode = report.policy.name
    init_src = report.cost_source
    lm_label = report.last_month_label
    cm_label = report.current_month_label
    checked_dealloc = " checked" if report.include_deallocated_cost else ""
    parts += [
        f'<section class="panel" id="hike-simulator" data-symbol="{_e(sym)}" data-initial-mode="{_e(init_mode)}">',
        '<div class="toolbar">',
        '<div class="tgroup">',
        '<label class="ctrl"><strong>Migrate to:</strong> '
        '<select id="sim-target-tier">'
        '<option value="v5-payg" selected>v5 Bridge (PAYG)</option>'
        '<option value="v6-payg">v6 / v7 Strategic (PAYG)</option>'
        '<option value="v5-ri">v5 Bridge + 3-Year RI/SP</option>'
        '<option value="v6-ri">v6 / v7 + 3-Year RI/SP</option>'
        "</select></label>",
        '<label class="chip"><input type="checkbox" id="sim-mig-v1" checked> v1 fleet</label>',
        '<label class="chip"><input type="checkbox" id="sim-mig-v2" checked> v2 fleet</label>',
        '<label class="chip"><input type="checkbox" id="sim-mig-v3" checked> v3 fleet</label>',
        '<label class="chip"><input type="checkbox" id="sim-shut-idle"> Stop Advisor idle VMs</label>',
        "</div>",
        '<div class="tgroup">',
        '<button type="button" class="btn" data-mig-preset="all">Migrate All</button>',
        '<button type="button" class="btn" data-mig-preset="v1v2">v1 &amp; v2 Only (+25%)</button>',
        '<button type="button" class="btn" data-mig-preset="cheaper-feb">Cheaper than Feb Only</button>',
        '<button type="button" class="btn" data-mig-preset="none">Do Nothing (None)</button>',
        "</div>",
        "</div>",
        '<div class="toolbar" style="border-top:1px solid var(--line);padding-top:8px;margin-top:8px">',
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
        "</section>",
    ]

    # Generation summary table with 3 colour-coded column groups
    parts += [
        '<section class="panel">',
        '<div class="bar"><h3>By VM Generation: Today vs Doing Nothing vs Migrating</h3></div>',
        '<div class="scroll">',
        "<table>",
        "<thead>",
        '<tr class="group-head">',
        '<th colspan="3">Fleet Footprint</th>',
        '<th class="num g-today">1. Today</th>',
        '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing (Stay)</th>',
        '<th colspan="4" class="num g-mig">3. Feb 2027: Migrate to Target SKU</th>',
        "</tr>",
        "<tr>",
        _th("Generation", sortable=False),
        _th("Instances (Active / Off)", numeric=True, sortable=False),
        _th("vCPUs", numeric=True, sortable=False),
        _th("Current / mo", numeric=True, sortable=False),
        _th("Do Nothing / mo", numeric=True, sortable=False),
        _th("vs Today (Hike)", numeric=True, sortable=False),
        _th("Migrated / mo", numeric=True, sortable=False),
        _th("vs Today (New SKU)", numeric=True, sortable=False),
        _th("vs Do Nothing (Saved)", numeric=True, sortable=False),
        _th("With 3Y RI / mo", numeric=True, sortable=False),
        "</tr></thead><tbody>",
    ]
    retire_windows = {
        "v1": "Retires May/Nov 2028",
        "v2": "Retires May/Nov 2028",
        "v3": "Retires Nov 2029 (RI blocked)",
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
    gen_cell_html = f'{gen_badge} <span class="meta">{_e(retire_label)}</span>'
    if not available:
        cells = [_td("", html=gen_cell_html)] + [_td("n/a", cls="num dim")] * 9
        return f'<tr class="{row_cls}" data-gen-summary="{_e(gen_key)}">' + "".join(cells) + "</tr>"
    inst_str = f"{s.instance_count} ({s.running_instances} / {s.deallocated_instances})"
    stay_vs_cur = f"{format_money(s.monthly_delta, cur, signed=True)} ({format_pct(s.effective_hike_pct, signed=True)})"
    mig_vs_cur = f"{format_money(s.target_v5_delta_vs_current, cur, signed=True)} ({format_pct(s.target_v5_pct_vs_current, signed=True)})"
    mig_vs_feb = f"{format_money(s.target_v5_delta_vs_feb, cur, signed=True)} ({format_pct(s.target_v5_pct_vs_feb, signed=True)})"
    cells = [
        _td("", html=gen_cell_html),
        _td(inst_str, cls="num"),
        _td(s.total_vcpus, cls="num"),
        _td(format_money(s.current_monthly, cur), cls="num c-today", col="cur"),
        _td(format_money(s.feb_monthly, cur), cls="num warn c-stay", col="feb"),
        _td(stay_vs_cur, cls="num bad" if s.monthly_delta > 0 else "num dim", col="delta"),
        _td(format_money(s.target_v5_monthly, cur), cls="num ok c-mig", col="v5"),
        _td(
            mig_vs_cur,
            cls="num ok" if s.target_v5_delta_vs_current < 0 else ("num warn" if s.target_v5_delta_vs_current > 0 else "num dim"),
            col="migcur",
        ),
        _td(
            mig_vs_feb,
            cls="num ok" if s.target_v5_delta_vs_feb < 0 else "num",
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
        lines += [
            '<div class="tabs">',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="all" aria-selected="true">Show All</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="skus" aria-selected="false">By SKU ({len(tenant.sku_rows)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="subs" aria-selected="false">By Subscription ({len(tenant.subscription_rows)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="waves" aria-selected="false">By Migration Wave ({len(tenant.wave_rows)})</button>',
            f'<button type="button" class="tab-btn" data-tab-group="{tgroup}" data-tab-target="vms" aria-selected="false">All VMs ({len(tenant.records)})</button>',
            "</div>",
        ]
    lines.append("</div>")

    if not tenant.fetched:
        lines.append('<p class="empty bad">VM inventory could not be retrieved for this tenant (see notes below).</p>')
    elif not tenant.records:
        lines.append('<p class="empty ok">No legacy v1, v2 or v3 VM SKUs are deployed in this tenant.</p>')
    else:
        # 1. SKU breakdown table (compact, grouped headers)
        sku_table_id = f"skus-{index}"
        lines += [
            f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="skus">',
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
            '<th colspan="4" class="num g-mig">3. Feb 2027: Migrate</th>',
            "</tr>",
            "<tr>",
            _th("Mig", sortable=False),
            _th("Legacy SKU"),
            _th("Inst (Act/Off)", numeric=True),
            _th("vCPUs", numeric=True),
            _th("Current / mo", numeric=True),
            _th("Do Nothing / mo", numeric=True),
            _th("vs Today (Hike)", numeric=True),
            _th("Target SKU"),
            _th("Migrated / mo", numeric=True),
            _th("vs Today (New SKU)", numeric=True),
            _th("vs Do Nothing (Saved)", numeric=True),
            "</tr></thead><tbody>",
        ]
        for srow in tenant.sku_rows:
            sku_key = f"{tid}|{srow.sku}"
            gen_badge = _badge(srow.generation, f"gen-{srow.generation}")
            stay_vs_cur_str = f"{format_money(srow.monthly_delta, cur, signed=True)} ({format_pct(srow.hike_pct, signed=True)})"
            mig_vs_cur_str = f"{format_money(srow.target_v5_delta_vs_current, cur, signed=True)} ({format_pct(srow.target_v5_pct_vs_current, signed=True)})"
            mig_vs_feb_str = f"{format_money(srow.target_v5_delta_vs_feb, cur, signed=True)} ({format_pct(srow.target_v5_pct_vs_feb, signed=True)})"
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
            lines.append(
                f'<tr class="sku-summary-row" data-sku-key="{_e(sku_key)}" data-gen="{_e(srow.generation)}">'
                + "".join([
                    _td("", html=sku_cb_html),
                    _td("", sort=srow.sku, html=sku_cell_html),
                    _td(f"{srow.instance_count} ({srow.running_instances}/{srow.deallocated_instances})", cls="num", sort=srow.instance_count),
                    _td(srow.vcpus_per_instance * srow.instance_count, cls="num", sort=srow.vcpus_per_instance * srow.instance_count),
                    _td(format_money(srow.current_monthly, cur), cls="num c-today", sort=f"{srow.current_monthly:.2f}", col="cur"),
                    _td(format_money(srow.feb_monthly, cur), cls="num warn c-stay", sort=f"{srow.feb_monthly:.2f}", col="feb"),
                    _td(
                        stay_vs_cur_str,
                        cls="num bad" if srow.monthly_delta > 0 else "num dim",
                        sort=f"{srow.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td("", sort=srow.target_v5_sku, html=tgt_cell_html),
                    _td(
                        format_money(srow.target_v5_monthly, cur),
                        cls="num ok c-mig",
                        sort=f"{srow.target_v5_monthly:.2f}",
                        col="v5",
                    ),
                    _td(
                        mig_vs_cur_str,
                        cls="num ok" if srow.target_v5_delta_vs_current < 0 else ("num warn" if srow.target_v5_delta_vs_current > 0 else "num dim"),
                        sort=f"{srow.target_v5_delta_vs_current:.2f}",
                        col="migcur",
                    ),
                    _td(
                        mig_vs_feb_str,
                        cls="num ok" if srow.target_v5_delta_vs_feb < 0 else ("num bad" if srow.target_v5_delta_vs_feb > 0 else "num dim"),
                        sort=f"{srow.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # 2. Subscription breakdown table
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
            '<th colspan="2" class="num g-mig">3. Feb 2027: Migrate</th>',
            "</tr>",
            "<tr>",
            _th("Subscription"),
            _th("Instances (v1 / v2 / v3)", numeric=True),
            _th("vCPUs", numeric=True),
            _th("Current / mo", numeric=True),
            _th("Do Nothing / mo", numeric=True),
            _th("vs Today (Hike)", numeric=True),
            _th("Migrated / mo", numeric=True),
            _th("vs Do Nothing (Saved)", numeric=True),
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
                    _td("", sort=sub_row.subscription_name, title=sub_row.subscription_id, html=sub_cell_html),
                    _td(inst_breakdown, cls="num", sort=sub_row.total_instances),
                    _td(sub_row.total_vcpus, cls="num", sort=sub_row.total_vcpus),
                    _td(format_money(sub_row.current_monthly, cur), cls="num c-today", sort=f"{sub_row.current_monthly:.2f}", col="cur"),
                    _td(format_money(sub_row.feb_monthly, cur), cls="num warn c-stay", sort=f"{sub_row.feb_monthly:.2f}", col="feb"),
                    _td(
                        f"{format_money(sub_row.monthly_delta, cur, signed=True)} ({format_pct(sub_hike_pct, signed=True)})",
                        cls="num bad" if sub_row.monthly_delta > 0 else "num dim",
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
                        f"{format_money(sub_mig_feb, cur, signed=True)} ({format_pct(sub_mig_feb_pct, signed=True)})",
                        cls="num ok" if sub_mig_feb < 0 else "num dim",
                        sort=f"{sub_row.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # 3. Migration Wave breakdown table
        if tenant.wave_rows:
            lines += [
                f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="waves">',
                '<div class="bar"><h3>By Migration Wave</h3></div>',
                '<div class="scroll">',
                "<table>",
                "<thead>",
                '<tr class="group-head">',
                '<th colspan="3">Migration Wave</th>',
                '<th class="num g-today">1. Today</th>',
                '<th class="num g-stay">2. Do Nothing</th>',
                '<th colspan="4" class="num g-mig">3. Migrate</th>',
                "</tr>",
                "<tr>",
                _th("Wave", sortable=False),
                _th("Instances", numeric=True, sortable=False),
                _th("vCPUs", numeric=True, sortable=False),
                _th("Current / mo", numeric=True, sortable=False),
                _th("Do Nothing / mo", numeric=True, sortable=False),
                _th("Migrated / mo", numeric=True, sortable=False),
                _th("vs Today (New SKU)", numeric=True, sortable=False),
                _th("vs Do Nothing (Saved)", numeric=True, sortable=False),
                _th("With 3Y RI / mo", numeric=True, sortable=False),
                "</tr></thead><tbody>",
            ]
            for wrow in tenant.wave_rows:
                wkey = f"{tid}|{wrow.wave}"
                w_m_cur = round(wrow.target_v5_monthly - wrow.current_monthly, 2)
                w_p_cur = round((w_m_cur / wrow.current_monthly) * 100.0, 2) if wrow.current_monthly > 0 else 0.0
                w_m_feb = round(wrow.target_v5_monthly - wrow.feb_monthly, 2)
                w_p_feb = round((w_m_feb / wrow.feb_monthly) * 100.0, 2) if wrow.feb_monthly > 0 else 0.0
                lines.append(
                    f'<tr class="wave-summary-row" data-wave-key="{_e(wkey)}">'
                    + "".join([
                        _td(wrow.wave),
                        _td(wrow.instance_count, cls="num"),
                        _td(wrow.total_vcpus, cls="num"),
                        _td(format_money(wrow.current_monthly, cur), cls="num c-today", col="cur"),
                        _td(format_money(wrow.feb_monthly, cur), cls="num warn c-stay", col="feb"),
                        _td(format_money(wrow.target_v5_monthly, cur), cls="num ok c-mig", col="v5"),
                        _td(
                            f"{format_money(w_m_cur, cur, signed=True)} ({format_pct(w_p_cur, signed=True)})",
                            cls="num ok" if w_m_cur < 0 else "num",
                            col="migcur",
                        ),
                        _td(
                            f"{format_money(w_m_feb, cur, signed=True)} ({format_pct(w_p_feb, signed=True)})",
                            cls="num ok" if w_m_feb < 0 else "num",
                            col="v5save",
                        ),
                        _td(format_money(wrow.target_v5_3yr_ri_monthly, cur), cls="num ok", col="v5ri"),
                    ])
                    + "</tr>"
                )
            lines += ["</tbody></table></div></div>"]

        # 4. VM inventory table (compact, scannable)
        vm_table_id = f"vms-{index}"
        lines += [
            f'<div class="block tab-pane" data-tab-group="{tgroup}" data-pane="vms">',
            '<div class="bar">',
            f"<h3>Deployed Legacy VMs &amp; Scale Sets ({len(tenant.records)})</h3>",
            '<div class="controls">',
            f'<select data-gen-filter="{vm_table_id}">'
            '<option value="">All generations</option>'
            '<option value="v1">v1 only</option>'
            '<option value="v2">v2 only</option>'
            '<option value="v3">v3 only</option>'
            "</select>",
            f'<input type="search" placeholder="Search VM, SKU, subscription, RG\u2026" data-filter="{vm_table_id}">',
            "</div></div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{vm_table_id}">',
            "<thead>",
            '<tr class="group-head">',
            '<th colspan="4">Resource &amp; Legacy Config</th>',
            '<th class="num g-today">1. Today</th>',
            '<th colspan="2" class="num g-stay">2. Feb 2027: Do Nothing</th>',
            '<th colspan="4" class="num g-mig">3. Feb 2027: Migrate</th>',
            '<th>Readiness</th>',
            "</tr>",
            "<tr>",
            _th("Mig", sortable=False),
            _th("Resource"),
            _th("Legacy SKU"),
            _th("State &amp; Hours"),
            _th("Current / mo", numeric=True),
            _th("Do Nothing / mo", numeric=True),
            _th("vs Today (Hike)", numeric=True),
            _th("Target SKU"),
            _th("Migrated / mo", numeric=True),
            _th("vs Today (New SKU)", numeric=True),
            _th("vs Do Nothing (Saved)", numeric=True),
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
            v5_ri_ratio = (
                (rec.target_v5_3yr_ri_monthly / rec.current_monthly)
                if rec.current_monthly > 0
                else (v5_ratio * 0.55)
            )
            v6_ri_ratio = (
                (rec.target_current_3yr_ri_monthly / rec.current_monthly)
                if rec.current_monthly > 0
                else (v6_ratio * 0.55)
            )
            idle_flag = "1" if "shut down idle vm" in rec.advisor_recommendation.lower() else "0"

            res_cell_html = (
                f'<span class="cell-main">{_e(name_label)}</span>'
                f'<span class="cell-sub">{_e(rec.subscription_name)} \u00b7 {_e(rec.resource_group)} \u00b7 {_e(rec.region)}</span>'
            )
            sku_cell_html = (
                f'<span class="cell-main">{_e(rec.sku)} {gen_badge}</span>'
                f'<span class="cell-sub">{rec.total_vcpus} vCPU \u00b7 {_e(os_short)} \u00b7 {_e(format_hourly(rec.hourly_rate, cur))}/hr</span>'
            )
            state_cell_html = (
                f'{state_badge} <span class="meta">{_e(hrs_str)}</span>'
                + (f'<span class="cell-sub">{_e(rec.auto_shutdown_schedule)}</span>' if rec.auto_shutdown_schedule else "")
            )
            wave_short = rec.migration_wave.split(":", 1)[0] if ":" in rec.migration_wave else rec.migration_wave
            tgt_cell_html = (
                f'<span class="cell-main" data-col="tgtsku">{_e(rec.target_v5_sku or rec.recommended_v5)}</span>'
                f'<span class="cell-sub">{_e(wave_short)} \u00b7 {_e(rec.deployment_kind)}</span>'
            )

            sig_badges = []
            if idle_flag == "1":
                sig_badges.append(_badge("Advisor: Idle", "warn"))
            elif rec.advisor_recommendation:
                sig_badges.append(_badge("Advisor: Right-size", "warn"))
            if "RI Covered" in rec.ri_status:
                sig_badges.append(_badge("RI Covered", "ok"))
            if "Increase Needed" in rec.quota_status:
                sig_badges.append(_badge("Quota Needed", "bad"))
            elif "Quota OK" in rec.quota_status:
                sig_badges.append(_badge("Quota OK", "dim"))
            sig_html = " ".join(sig_badges) if sig_badges else '<span class="dim">\u2014</span>'

            stay_vs_cur_str = f"{format_money(rec.monthly_delta, cur, signed=True)} ({format_pct(rec.hike_pct, signed=True)})"
            rec_mig_vs_cur = f"{format_money(rec.target_v5_delta_vs_current, cur, signed=True)} ({format_pct(rec.target_v5_pct_vs_current, signed=True)})"
            rec_mig_vs_feb = f"{format_money(rec.target_v5_delta_vs_feb, cur, signed=True)} ({format_pct(rec.target_v5_pct_vs_feb, signed=True)})"
            vm_cb_html = '<input type="checkbox" class="vm-mig-check" checked title="Include this VM in migration">'

            lines.append(
                f'<tr class="vm-row" data-tenant="{_e(tid)}" data-sub="{_e(rec.subscription_id)}" '
                f'data-sku="{_e(rec.sku)}" data-gen="{_e(rec.generation)}" '
                f'data-wave="{_e(rec.migration_wave)}" data-inst="{rec.instance_count}" '
                f'data-idle="{idle_flag}" '
                f'data-v5-sku="{_e(rec.target_v5_sku or rec.recommended_v5)}" '
                f'data-v6-sku="{_e(rec.target_current_sku or rec.recommended_current)}" '
                f'data-prov-cur="{rec.provisioned_current_monthly:.2f}" '
                f'data-sched-cur="{rec.schedule_adjusted_monthly:.2f}" '
                f'data-has-cm="{has_cm_flag}" data-lm-cost="{lm_val:.2f}" data-mtd-ext="{mtd_ext_val:.2f}" '
                f'data-billed="{billed_flag}" data-sh-pct="{rec.service_health_hike_pct:.2f}" '
                f'data-v5-ratio="{v5_ratio:.4f}" data-v6-ratio="{v6_ratio:.4f}" '
                f'data-v5-ri-ratio="{v5_ri_ratio:.4f}" data-v6-ri-ratio="{v6_ri_ratio:.4f}">'
                + "".join([
                    _td("", html=vm_cb_html),
                    _td("", sort=rec.name, title=rec.resource_id, html=res_cell_html),
                    _td("", sort=rec.sku, html=sku_cell_html),
                    _td("", sort=f"{sched_sort:.1f}", html=state_cell_html),
                    _td(format_money(rec.current_monthly, cur), cls="num c-today", sort=f"{rec.current_monthly:.2f}", col="cur"),
                    _td(format_money(rec.feb_monthly, cur), cls="num warn c-stay", sort=f"{rec.feb_monthly:.2f}", col="feb"),
                    _td(
                        stay_vs_cur_str,
                        cls="num bad" if rec.monthly_delta > 0 else "num dim",
                        sort=f"{rec.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td("", sort=rec.target_v5_sku, title=f"{rec.migration_cli_hint} ({rec.disk_controller_note})", html=tgt_cell_html),
                    _td(
                        format_money(rec.target_v5_monthly, cur),
                        cls="num ok c-mig",
                        sort=f"{rec.target_v5_monthly:.2f}",
                        col="v5",
                    ),
                    _td(
                        rec_mig_vs_cur,
                        cls="num ok" if rec.target_v5_delta_vs_current < 0 else ("num warn" if rec.target_v5_delta_vs_current > 0 else "num dim"),
                        sort=f"{rec.target_v5_delta_vs_current:.2f}",
                        col="migcur",
                    ),
                    _td(
                        rec_mig_vs_feb,
                        cls="num ok" if rec.target_v5_delta_vs_feb < 0 else ("num bad" if rec.target_v5_delta_vs_feb > 0 else "num dim"),
                        sort=f"{rec.target_v5_savings_vs_feb:.2f}",
                        col="v5save",
                    ),
                    _td("", title=rec.cost_breakdown_note, html=sig_html),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

    if tenant.issues:
        lines.append('<div class="block"><h3>Notes</h3>')
        for issue in tenant.issues:
            label, style = _LEVEL_LABELS.get(issue.level, ("Note", "dim"))
            lines.append(
                f'<div class="note">{_badge(label, style)} '
                f"<strong>[{_e(issue.feature)}]</strong> {_e(issue.message)}</div>"
            )
        lines.append("</div>")

    lines.append("</section>")
    return "\n".join(lines)
