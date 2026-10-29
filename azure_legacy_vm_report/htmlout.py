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
body{margin:0;min-height:100vh;color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:radial-gradient(1100px 620px at 12% -8%,rgba(180,85,255,.20),transparent 62%),radial-gradient(900px 560px at 108% 4%,rgba(255,79,209,.12),transparent 58%),linear-gradient(180deg,#0a0b16,#0c0d1d);background-attachment:fixed}
main{max-width:1380px;margin:0 auto;padding:18px 16px 28px;display:grid;grid-template-columns:minmax(0,1fr);gap:12px}
h1{margin:0;font-size:22px;letter-spacing:.2px}
h1 span{background:linear-gradient(90deg,var(--accent),var(--accent2));-webkit-background-clip:text;background-clip:text;color:transparent}
h2{margin:0;font-size:17px}
h3{margin:0 0 8px;font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
p{margin:0}
.sub{color:var(--muted);margin-top:4px;font-size:13px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.banner{border-color:rgba(255,180,84,.45);color:var(--warn);background:rgba(255,180,84,.07)}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}
.stat{padding:9px 11px;border:1px solid var(--line);border-radius:10px;background:rgba(255,255,255,.02)}
.stat .n{display:block;font-size:22px;font-weight:650;line-height:1.15;font-variant-numeric:tabular-nums}
.stat .l{display:block;color:var(--muted);font-size:11.5px;margin-top:3px}
.tenant{display:grid;grid-template-columns:minmax(0,1fr);gap:10px}
.meta{color:var(--muted);font-size:12.5px}
.meta code{color:var(--text);background:rgba(255,255,255,.06);padding:1px 6px;border-radius:6px}
.block{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:rgba(255,255,255,.02)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;justify-content:space-between;margin-bottom:8px}
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.btn{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:5px 11px;font:12.5px/1.3 inherit;cursor:pointer}
.btn:hover{border-color:var(--accent)}
.btn[aria-pressed=true]{background:rgba(180,85,255,.18);border-color:var(--accent);color:#fff;font-weight:600}
label.ctrl{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--muted)}
input[type=number],select{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);border-radius:7px;padding:4px 7px;width:68px;font:inherit;font-variant-numeric:tabular-nums}
select{width:auto}
input[type=search]{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);border-radius:8px;padding:6px 10px;min-width:220px;font:inherit}
input:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:6px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
td.wrap{white-space:normal;min-width:170px}
th.num,td.num{text-align:right;font-variant-numeric:tabular-nums}
th{color:var(--muted);font-weight:600;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em}
th button{all:unset;cursor:pointer;color:inherit;font:inherit;text-transform:inherit;letter-spacing:inherit}
th button:hover,th button:focus-visible{color:var(--text);text-decoration:underline}
th[aria-sort=ascending] button::after{content:" \\25B2";color:var(--accent)}
th[aria-sort=descending] button::after{content:" \\25BC";color:var(--accent)}
tbody tr:hover td{background:rgba(180,85,255,.07)}
tr.total-row td{font-weight:650;border-top:2px solid var(--line)}
.badge{display:inline-block;padding:0 8px;border-radius:999px;font-size:11.5px;border:1px solid currentColor;line-height:1.55}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}.dim{color:var(--muted)}.accent{color:var(--accent)}
.gen-v1{color:var(--bad)}.gen-v2{color:var(--warn)}.gen-v3{color:var(--accent2)}
.note{padding:6px 0;border-bottom:1px solid var(--line)}
.note:last-child{border-bottom:0}
.empty{color:var(--muted);padding:6px 0}
footer{color:var(--muted);font-size:12px;text-align:center}
@media (max-width:900px){.stats{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){main{padding:10px 8px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}input[type=search]{min-width:0;width:100%}}
"""

SCRIPT = """
(function () {
  function cellValue(cell) {
    var sort = cell.getAttribute('data-sort');
    return (sort !== null ? sort : cell.textContent).trim().toLowerCase();
  }
  document.querySelectorAll('table.sortable').forEach(function (table) {
    var heads = table.querySelectorAll('thead th');
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
  var modeButtons = simPanel.querySelectorAll('button[data-mode]');
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

  function resolveBaseline(row, source, includeDealloc) {
    var provCur = parseFloat(row.getAttribute('data-prov-cur') || '0');
    var billedNow = row.getAttribute('data-billed') === '1';
    var retailCur = (billedNow || includeDealloc) ? provCur : 0;
    var hasCm = row.getAttribute('data-has-cm') === '1';
    if (!hasCm || source === 'retail') {
      return retailCur;
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

  function recalc() {
    var v1Pct = parseFloat(v1Input.value) || 0;
    var v2Pct = parseFloat(v2Input.value) || 0;
    var v3Pct = parseFloat(v3Input.value) || 0;
    var costSource = costSourceSelect ? costSourceSelect.value : 'auto';
    var includeDealloc = deallocCheck && deallocCheck.checked;

    var vmRows = document.querySelectorAll('tr.vm-row');
    if (!vmRows.length) { return; }

    var genStats = { v1: { cur: 0, feb: 0 }, v2: { cur: 0, feb: 0 }, v3: { cur: 0, feb: 0 } };
    var skuStats = {};
    var subStats = {};
    var totalCur = 0, totalFeb = 0;

    vmRows.forEach(function (row) {
      var gen = row.getAttribute('data-gen') || 'v3';
      var sku = row.getAttribute('data-sku') || '';
      var sub = row.getAttribute('data-sub') || '';
      var tenant = row.getAttribute('data-tenant') || '';
      var shPct = parseFloat(row.getAttribute('data-sh-pct') || '0');

      var cur = resolveBaseline(row, costSource, includeDealloc);
      var pct = 0;
      if (currentMode === 'service-health') {
        pct = shPct;
      } else {
        pct = gen === 'v1' ? v1Pct : (gen === 'v2' ? v2Pct : v3Pct);
      }
      var feb = cur * (1 + pct / 100);
      var delta = feb - cur;

      var curCell = row.querySelector('[data-col="cur"]');
      var febCell = row.querySelector('[data-col="feb"]');
      var deltaCell = row.querySelector('[data-col="delta"]');
      var pctCell = row.querySelector('[data-col="pct"]');
      if (curCell) { curCell.textContent = fmtMoney(cur, false); curCell.setAttribute('data-sort', cur.toFixed(2)); }
      if (febCell) { febCell.textContent = fmtMoney(feb, false); febCell.setAttribute('data-sort', feb.toFixed(2)); }
      if (deltaCell) { deltaCell.textContent = fmtMoney(delta, true); deltaCell.setAttribute('data-sort', delta.toFixed(2)); }
      if (pctCell) { pctCell.textContent = fmtPct(pct); pctCell.setAttribute('data-sort', pct.toFixed(2)); }

      if (genStats[gen]) { genStats[gen].cur += cur; genStats[gen].feb += feb; }
      totalCur += cur; totalFeb += feb;

      var skuKey = tenant + '|' + sku;
      if (!skuStats[skuKey]) { skuStats[skuKey] = { cur: 0, feb: 0, pct: pct }; }
      skuStats[skuKey].cur += cur; skuStats[skuKey].feb += feb;

      var subKey = tenant + '|' + sub;
      if (!subStats[subKey]) { subStats[subKey] = { cur: 0, feb: 0 }; }
      subStats[subKey].cur += cur; subStats[subKey].feb += feb;
    });

    var totalDelta = totalFeb - totalCur;
    var totalYrDelta = totalDelta * 12;
    var totalPct = totalCur > 0 ? (totalDelta / totalCur) * 100 : 0;

    var kpiCur = document.getElementById('kpi-current-mo');
    var kpiFeb = document.getElementById('kpi-feb-mo');
    var kpiDelta = document.getElementById('kpi-delta-mo');
    var kpiYr = document.getElementById('kpi-delta-yr');
    if (kpiCur) { kpiCur.textContent = fmtMoney(totalCur, false); }
    if (kpiFeb) { kpiFeb.textContent = fmtMoney(totalFeb, false); }
    if (kpiDelta) { kpiDelta.textContent = fmtMoney(totalDelta, true) + ' (' + fmtPct(totalPct) + ')'; }
    if (kpiYr) { kpiYr.textContent = fmtMoney(totalYrDelta, true); }

    document.querySelectorAll('tr.gen-summary-row').forEach(function (row) {
      var g = row.getAttribute('data-gen-summary');
      var st = g === 'Total' ? { cur: totalCur, feb: totalFeb } : genStats[g];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var p = st.cur > 0 ? (d / st.cur) * 100 : 0;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      var pEl = row.querySelector('[data-col="pct"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); }
      if (dEl) { dEl.textContent = fmtMoney(d, true); }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); }
      if (pEl) { pEl.textContent = fmtPct(p); }
    });

    document.querySelectorAll('tr.sku-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sku-key');
      var st = skuStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) { dEl.textContent = fmtMoney(d, true); dEl.setAttribute('data-sort', d.toFixed(2)); }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
    });

    document.querySelectorAll('tr.sub-summary-row').forEach(function (row) {
      var key = row.getAttribute('data-sub-key');
      var st = subStats[key];
      if (!st) { return; }
      var d = st.feb - st.cur;
      var cEl = row.querySelector('[data-col="cur"]');
      var fEl = row.querySelector('[data-col="feb"]');
      var dEl = row.querySelector('[data-col="delta"]');
      var yEl = row.querySelector('[data-col="yr"]');
      if (cEl) { cEl.textContent = fmtMoney(st.cur, false); cEl.setAttribute('data-sort', st.cur.toFixed(2)); }
      if (fEl) { fEl.textContent = fmtMoney(st.feb, false); fEl.setAttribute('data-sort', st.feb.toFixed(2)); }
      if (dEl) { dEl.textContent = fmtMoney(d, true); dEl.setAttribute('data-sort', d.toFixed(2)); }
      if (yEl) { yEl.textContent = fmtMoney(d * 12, true); yEl.setAttribute('data-sort', (d * 12).toFixed(2)); }
    });
  }

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
        '<h1>Azure Legacy VM SKU (<span>v1, v2 &amp; v3</span>) Cost &amp; February 2027 Hike Report</h1>',
        f'<p class="sub">Generated {_e(format_datetime(report.generated_at, tz))} ({_e(report.tz_name)}) '
        f"&middot; {_e(report.policy.label)} &middot; {_e(report.cost_basis_description)}</p>",
    ]
    for note in report.notes:
        parts.append(f'<p class="sub warn">{_e(note)}</p>')
    parts.append("</header>")

    # KPI cards
    delta_label = (
        f"{format_money(gt.monthly_delta, cur, signed=True)} ({format_pct(gt.effective_hike_pct, signed=True)})"
        if any_ok
        else "n/a"
    )
    parts += [
        '<section class="panel">',
        "<h3>Portfolio overview</h3>",
        '<div class="stats">',
        _stat(
            f"{gt.instance_count} ({gt.running_instances} active)" if any_ok else "n/a",
            "Legacy VM instances (v1-v3)",
        ),
        _stat(str(gt.total_vcpus) if any_ok else "n/a", "Total legacy vCPUs"),
        _stat(
            format_money(gt.current_monthly, cur) if any_ok else "n/a",
            "Current monthly cost",
            value_id="kpi-current-mo",
        ),
        _stat(
            format_money(gt.feb_monthly, cur) if any_ok else "n/a",
            "February 2027 monthly cost",
            value_id="kpi-feb-mo",
            cls="warn",
        ),
        _stat(
            delta_label,
            "Monthly price-hike impact (from 01/02/2027)",
            value_id="kpi-delta-mo",
            cls="bad" if any_ok and gt.monthly_delta > 0 else "ok",
        ),
        _stat(
            format_money(gt.annual_delta, cur, signed=True) if any_ok else "n/a",
            "Annualised price-hike impact (/yr)",
            value_id="kpi-delta-yr",
            cls="bad" if any_ok and gt.annual_delta > 0 else "ok",
        ),
        "</div>",
        "</section>",
    ]

    # Interactive scenario switcher
    init_mode = report.policy.name
    init_src = report.cost_source
    lm_label = report.last_month_label
    cm_label = report.current_month_label
    checked_dealloc = " checked" if report.include_deallocated_cost else ""
    parts += [
        f'<section class="panel" id="hike-simulator" data-symbol="{_e(sym)}" data-initial-mode="{_e(init_mode)}">',
        '<div class="bar">',
        "<div>",
        "<h3>February 2027 price-hike &amp; cost-baseline modeller</h3>",
        '<p class="sub">Switch between actual billed Cost Management spend (which already reflects auto-shutdown '
        "schedules, real hours run and negotiated rates) and 730h/mo Retail API rates, or compare hike rules.</p>",
        "</div>",
        '<div class="controls">',
        '<label class="ctrl">Baseline '
        '<select id="sim-cost-source">'
        f'<option value="auto"{" selected" if init_src == "auto" else ""}>'
        f"Auto: Actual Billed ({_e(lm_label)} / {_e(cm_label)} fallback)</option>"
        f'<option value="last-month"{" selected" if init_src == "last-month" else ""}>'
        f"{_e(lm_label)} Actual Cost Only</option>"
        f'<option value="mtd"{" selected" if init_src == "mtd" else ""}>'
        f"{_e(cm_label)} MTD Extrapolated</option>"
        f'<option value="retail"{" selected" if init_src == "retail" else ""}>'
        f"Retail List Price ({report.hours_per_month:g}h/mo Snapshot)</option>"
        "</select></label>",
        f'<button type="button" class="btn" data-mode="service-health" '
        f'aria-pressed="{"true" if init_mode == POLICY_SERVICE_HEALTH else "false"}">'
        "Service Health Strict (v1/v2 +25%, v3 Regional)</button>",
        f'<button type="button" class="btn" data-mode="legacy-25" '
        f'aria-pressed="{"true" if init_mode == "legacy-25" else "false"}">All v1/v2/v3 (+25%)</button>',
        f'<button type="button" class="btn" data-mode="custom" '
        f'aria-pressed="{"true" if init_mode == "custom" else "false"}">Custom %</button>',
        f'<label class="ctrl">v1 % <input type="number" id="sim-v1" step="0.5" value="{report.policy.v1_hike_pct:g}"></label>',
        f'<label class="ctrl">v2 % <input type="number" id="sim-v2" step="0.5" value="{report.policy.v2_hike_pct:g}"></label>',
        f'<label class="ctrl">v3 % <input type="number" id="sim-v3" step="0.5" value="{report.policy.v3_hike_pct:g}"></label>',
        f'<label class="ctrl"><input type="checkbox" id="sim-dealloc"{checked_dealloc}> '
        "Include deallocated VMs (if started 24x7)</label>",
        "</div>",
        "</div>",
        "</section>",
    ]

    # Generation summary table
    parts += [
        '<section class="panel">',
        "<h3>Summary by VM generation (v1, v2, v3)</h3>",
        '<div class="scroll">',
        "<table>",
        "<thead><tr>",
        _th("Generation", sortable=False),
        _th("Resources", numeric=True, sortable=False),
        _th("Instances (Active / Dealloc)", numeric=True, sortable=False),
        _th("vCPUs", numeric=True, sortable=False),
        _th("Current / mo", numeric=True, sortable=False),
        _th("Feb 2027 / mo", numeric=True, sortable=False),
        _th("Increase / mo", numeric=True, sortable=False),
        _th("Increase / yr", numeric=True, sortable=False),
        _th("Effective Hike", numeric=True, sortable=False),
        _th("Primary Retirement Window", sortable=False),
        "</tr></thead><tbody>",
    ]
    retire_windows = {
        "v1": "01/05/2028 (D/Ds/Ls) &middot; 15/11/2028 (Bv1/F/Fs/G/Gs)",
        "v2": "01/05/2028 (Dv2/Dsv2) &middot; 15/11/2028 (Av2/Fsv2/Lsv2)",
        "v3": "15/11/2029 (Dv3/Dsv3/Ev3/Esv3) &middot; RIs ended 01/07/2026",
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
            "01/02/2027 price hikes &amp; final RI exchange deadline",
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
    retire_html: str,
    *,
    is_total: bool,
) -> str:
    row_cls = "gen-summary-row total-row" if is_total else "gen-summary-row"
    gen_badge = _badge(gen_key, f"gen-{gen_key}" if not is_total else "accent")
    if not available:
        cells = [_td("", html=gen_badge)] + [_td("n/a", cls="num dim")] * 8 + [_td("", html=retire_html)]
        return f'<tr class="{row_cls}" data-gen-summary="{_e(gen_key)}">' + "".join(cells) + "</tr>"
    inst_str = f"{s.instance_count} ({s.running_instances} / {s.deallocated_instances})"
    cells = [
        _td("", html=gen_badge),
        _td(s.resource_count, cls="num"),
        _td(inst_str, cls="num"),
        _td(s.total_vcpus, cls="num"),
        _td(format_money(s.current_monthly, cur), cls="num", col="cur"),
        _td(format_money(s.feb_monthly, cur), cls="num warn", col="feb"),
        _td(format_money(s.monthly_delta, cur, signed=True), cls="num bad" if s.monthly_delta > 0 else "num", col="delta"),
        _td(format_money(s.annual_delta, cur, signed=True), cls="num bad" if s.annual_delta > 0 else "num", col="yr"),
        _td(format_pct(s.effective_hike_pct, signed=True), cls="num", col="pct"),
        _td("", cls="wrap dim", html=retire_html),
    ]
    return f'<tr class="{row_cls}" data-gen-summary="{_e(gen_key)}">' + "".join(cells) + "</tr>"


def _render_tenant_section(report: Report, tenant: TenantReport, index: int) -> str:
    cur = report.currency
    tid = tenant.tenant_id
    lines = [
        '<section class="panel tenant">',
        '<div class="bar">',
        f"<h2>{_e(tenant.display_name)}</h2>",
        '<div class="meta">',
        f"<code>{_e(tid)}</code>",
    ]
    if tenant.default_domain:
        lines.append(f" &middot; {_e(tenant.default_domain)}")
    if tenant.data.subscription_count is not None:
        lines.append(f" &middot; {_e(plural(tenant.data.subscription_count, 'subscription'))} visible")
    if tenant.fetched:
        lines.append(f" &middot; {tenant.data.total_resources_scanned} compute resources scanned")
        lines.append(f" &middot; {len(tenant.records)} legacy (v1-v3) deployments")
    lines += ["</div></div>"]

    if not tenant.fetched:
        lines.append('<p class="empty bad">VM inventory could not be retrieved for this tenant (see notes below).</p>')
    elif not tenant.records:
        lines.append('<p class="empty ok">No legacy v1, v2 or v3 VM SKUs are deployed in this tenant.</p>')
    else:
        # SKU breakdown table
        sku_table_id = f"skus-{index}"
        lines += [
            '<div class="block">',
            '<div class="bar">',
            f"<h3>By legacy SKU ({len(tenant.sku_rows)} distinct SKUs)</h3>",
            f'<input type="search" placeholder="Filter SKUs\u2026" data-filter="{sku_table_id}">',
            "</div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{sku_table_id}">',
            "<thead><tr>",
            _th("SKU"),
            _th("Gen"),
            _th("Series"),
            _th("vCPUs", numeric=True),
            _th("Instances", numeric=True),
            _th("Active / Dealloc", numeric=True),
            _th("OS Split (Lin / Win / AHB)"),
            _th("Regions"),
            _th("Current / mo", numeric=True),
            _th("Feb 2027 / mo", numeric=True),
            _th("Increase / mo", numeric=True),
            _th("Increase / yr", numeric=True),
            _th("Retires"),
            _th("Recommended v5 (bridge) -> v6/v7 (Current)"),
            "</tr></thead><tbody>",
        ]
        for srow in tenant.sku_rows:
            sku_key = f"{tid}|{srow.sku}"
            gen_badge = _badge(srow.generation, f"gen-{srow.generation}")
            os_split = f"{srow.linux_instances}L / {srow.windows_instances}W ({srow.ahb_instances} AHB)"
            lines.append(
                f'<tr class="sku-summary-row" data-sku-key="{_e(sku_key)}" data-gen="{_e(srow.generation)}">'
                + "".join([
                    _td(srow.sku),
                    _td("", sort=srow.generation, html=gen_badge),
                    _td(srow.series),
                    _td(srow.vcpus_per_instance, cls="num", sort=srow.vcpus_per_instance),
                    _td(srow.instance_count, cls="num", sort=srow.instance_count),
                    _td(f"{srow.running_instances} / {srow.deallocated_instances}", cls="num", sort=srow.running_instances),
                    _td(os_split, cls="dim"),
                    _td(", ".join(srow.regions)),
                    _td(format_money(srow.current_monthly, cur), cls="num", sort=f"{srow.current_monthly:.2f}", col="cur"),
                    _td(format_money(srow.feb_monthly, cur), cls="num warn", sort=f"{srow.feb_monthly:.2f}", col="feb"),
                    _td(
                        format_money(srow.monthly_delta, cur, signed=True),
                        cls="num bad" if srow.monthly_delta > 0 else "num",
                        sort=f"{srow.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td(
                        format_money(srow.annual_delta, cur, signed=True),
                        cls="num bad" if srow.annual_delta > 0 else "num",
                        sort=f"{srow.annual_delta:.2f}",
                        col="yr",
                    ),
                    _td(srow.retirement_date),
                    _td(f"{srow.recommended_v5} \u2192 {srow.recommended_current}", cls="wrap dim"),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # Subscription breakdown table
        sub_table_id = f"subs-{index}"
        lines += [
            '<div class="block">',
            '<div class="bar">',
            f"<h3>By subscription ({len(tenant.subscription_rows)} subscriptions with legacy VMs)</h3>",
            f'<input type="search" placeholder="Filter subscriptions\u2026" data-filter="{sub_table_id}">',
            "</div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{sub_table_id}">',
            "<thead><tr>",
            _th("Subscription"),
            _th("v1 Inst", numeric=True),
            _th("v2 Inst", numeric=True),
            _th("v3 Inst", numeric=True),
            _th("Total Inst", numeric=True),
            _th("Total vCPUs", numeric=True),
            _th("Current / mo", numeric=True),
            _th("Feb 2027 / mo", numeric=True),
            _th("Increase / mo", numeric=True),
            _th("Increase / yr", numeric=True),
            "</tr></thead><tbody>",
        ]
        for sub_row in tenant.subscription_rows:
            sub_key = f"{tid}|{sub_row.subscription_id}"
            lines.append(
                f'<tr class="sub-summary-row" data-sub-key="{_e(sub_key)}">'
                + "".join([
                    _td(sub_row.subscription_name, title=sub_row.subscription_id),
                    _td(sub_row.v1_instances, cls="num", sort=sub_row.v1_instances),
                    _td(sub_row.v2_instances, cls="num", sort=sub_row.v2_instances),
                    _td(sub_row.v3_instances, cls="num", sort=sub_row.v3_instances),
                    _td(sub_row.total_instances, cls="num", sort=sub_row.total_instances),
                    _td(sub_row.total_vcpus, cls="num", sort=sub_row.total_vcpus),
                    _td(format_money(sub_row.current_monthly, cur), cls="num", sort=f"{sub_row.current_monthly:.2f}", col="cur"),
                    _td(format_money(sub_row.feb_monthly, cur), cls="num warn", sort=f"{sub_row.feb_monthly:.2f}", col="feb"),
                    _td(
                        format_money(sub_row.monthly_delta, cur, signed=True),
                        cls="num bad" if sub_row.monthly_delta > 0 else "num",
                        sort=f"{sub_row.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td(
                        format_money(sub_row.annual_delta, cur, signed=True),
                        cls="num bad" if sub_row.annual_delta > 0 else "num",
                        sort=f"{sub_row.annual_delta:.2f}",
                        col="yr",
                    ),
                ])
                + "</tr>"
            )
        lines += ["</tbody></table></div></div>"]

        # VM inventory table
        vm_table_id = f"vms-{index}"
        lines += [
            '<div class="block">',
            '<div class="bar">',
            f"<h3>Deployed legacy VMs &amp; scale sets ({len(tenant.records)})</h3>",
            '<div class="controls">',
            f'<select data-gen-filter="{vm_table_id}">'
            '<option value="">All generations (v1-v3)</option>'
            '<option value="v1">v1 only</option>'
            '<option value="v2">v2 only</option>'
            '<option value="v3">v3 only</option>'
            "</select>",
            f'<input type="search" placeholder="Search VM, SKU, subscription, RG\u2026" data-filter="{vm_table_id}">',
            "</div></div>",
            '<div class="scroll">',
            f'<table class="sortable" id="{vm_table_id}">',
            "<thead><tr>",
            _th("Name"),
            _th("Subscription"),
            _th("Resource Group"),
            _th("Region"),
            _th("SKU"),
            _th("Gen"),
            _th("vCPUs", numeric=True),
            _th("OS / Licensing"),
            _th("Power State"),
            _th("Schedule / Billed Hrs"),
            _th("Rate / hr", numeric=True),
            _th("Current / mo", numeric=True),
            _th("Feb 2027 / mo", numeric=True),
            _th("Increase / mo", numeric=True),
            _th("Hike %", numeric=True),
            _th("Migration Target &amp; Controller Notes"),
            "</tr></thead><tbody>",
        ]
        for rec in tenant.records:
            name_label = f"{rec.name} (VMSS \u00d7{rec.instance_count})" if rec.resource_type == TYPE_VMSS else rec.name
            gen_badge = _badge(rec.generation, f"gen-{rec.generation}")
            os_badge = _badge(
                f"{rec.os_type} (AHB)" if rec.hybrid_benefit else rec.os_type,
                "ok" if rec.hybrid_benefit else "dim",
            )
            state_badge = _badge(
                rec.power_state,
                "dim" if rec.power_state == POWER_DEALLOCATED else "ok",
            )
            sched_bits = []
            if rec.actual_last_month_hours is not None and rec.actual_last_month_hours > 0:
                sched_bits.append(f"{rec.actual_last_month_hours:.0f}h last mo")
            elif rec.actual_mtd_hours is not None and rec.actual_mtd_hours > 0:
                sched_bits.append(f"{rec.actual_mtd_hours:.0f}h MTD")
            if rec.auto_shutdown_schedule:
                sched_bits.append(f"Auto-off: {rec.auto_shutdown_schedule}")
            sched_text = " \u00b7 ".join(sched_bits) if sched_bits else "\u2014"
            sched_sort = rec.actual_last_month_hours if rec.actual_last_month_hours is not None else -1.0

            billed_flag = "1" if rec.is_billed_now else "0"
            has_cm_flag = "1" if rec.actual_last_month_cost is not None else "0"
            lm_val = rec.actual_last_month_cost if rec.actual_last_month_cost is not None else 0.0
            mtd_ext_val = rec.actual_mtd_extrapolated_cost if rec.actual_mtd_extrapolated_cost is not None else 0.0

            lines.append(
                f'<tr class="vm-row" data-tenant="{_e(tid)}" data-sub="{_e(rec.subscription_id)}" '
                f'data-sku="{_e(rec.sku)}" data-gen="{_e(rec.generation)}" '
                f'data-prov-cur="{rec.provisioned_current_monthly:.2f}" '
                f'data-has-cm="{has_cm_flag}" data-lm-cost="{lm_val:.2f}" data-mtd-ext="{mtd_ext_val:.2f}" '
                f'data-billed="{billed_flag}" data-sh-pct="{rec.service_health_hike_pct:.2f}">'
                + "".join([
                    _td(name_label, title=rec.resource_id),
                    _td(rec.subscription_name, title=rec.subscription_id),
                    _td(rec.resource_group),
                    _td(rec.region),
                    _td(rec.sku),
                    _td("", sort=rec.generation, html=gen_badge),
                    _td(rec.total_vcpus, cls="num", sort=rec.total_vcpus),
                    _td("", sort=rec.pricing_model, html=os_badge),
                    _td("", sort=rec.power_state, html=state_badge),
                    _td(sched_text, cls="dim", sort=f"{sched_sort:.1f}"),
                    _td(format_hourly(rec.hourly_rate, cur), cls="num dim", sort=f"{rec.hourly_rate:.4f}"),
                    _td(format_money(rec.current_monthly, cur), cls="num", sort=f"{rec.current_monthly:.2f}", col="cur"),
                    _td(format_money(rec.feb_monthly, cur), cls="num warn", sort=f"{rec.feb_monthly:.2f}", col="feb"),
                    _td(
                        format_money(rec.monthly_delta, cur, signed=True),
                        cls="num bad" if rec.monthly_delta > 0 else "num",
                        sort=f"{rec.monthly_delta:.2f}",
                        col="delta",
                    ),
                    _td(
                        format_pct(rec.hike_pct, signed=True),
                        cls="num",
                        sort=f"{rec.hike_pct:.2f}",
                        col="pct",
                    ),
                    _td(
                        f"{rec.recommended_v5} \u2192 {rec.recommended_current} ({rec.disk_controller_note})",
                        cls="wrap dim",
                    ),
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
