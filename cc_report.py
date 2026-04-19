"""
cc_report.py
------------
Rebuilds CredInsights.html from the current transactions_master CSV.
CSS and JS are kept as separate raw strings (not inside the f-string)
to completely avoid {{ }} brace-escaping issues.
"""

import csv
import json
import logging
from collections import defaultdict
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  DATA LOADING + AGGREGATION
# ─────────────────────────────────────────────

def load_report_data(ledger_path: str) -> tuple:
    rows = []
    with open(ledger_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                amt = float(row.get("Amount (Rs.)", 0) or 0)
            except ValueError:
                continue
            if row.get("Is Credit") == "TRUE" or amt <= 0:
                continue
            rows.append({
                "year":       int(row.get("Year", 0) or 0),
                "month":      int(row.get("Month", 0) or 0),
                "day":        int(row.get("Day", 0) or 0),
                "date":       row.get("Date", ""),
                "cardholder": row.get("Cardholder", ""),
                "desc":       row.get("Transaction Description", ""),
                "cat":        row.get("Category", "Others"),
                "subcat":     row.get("SubCategory", "Others"),
                "pts":        int(row.get("Reward Points", 0) or 0),
                "amt":        amt,
                "pct":        float(row.get("% Reward", 0) or 0),
                "src":        row.get("Source PDF", ""),
                "bank":       row.get("Bank", "Unknown Bank"),
                "card":       row.get("Card", "Unknown Card"),
            })

    yoy       = defaultdict(lambda: {"amt": 0, "pts": 0, "txns": 0})
    mom       = defaultdict(lambda: {"amt": 0, "pts": 0, "txns": 0})
    by_cat    = defaultdict(lambda: {"amt": 0, "pts": 0, "txns": 0})
    by_subcat = defaultdict(lambda: {"amt": 0, "pts": 0, "txns": 0, "cat": "", "subcat": ""})

    for r in rows:
        yoy[str(r["year"])]["amt"]  += r["amt"]
        yoy[str(r["year"])]["pts"]  += r["pts"]
        yoy[str(r["year"])]["txns"] += 1
        mk = f"{r['year']}-{r['month']:02d}"
        mom[mk]["amt"]  += r["amt"]
        mom[mk]["pts"]  += r["pts"]
        mom[mk]["txns"] += 1
        by_cat[r["cat"]]["amt"]  += r["amt"]
        by_cat[r["cat"]]["pts"]  += r["pts"]
        by_cat[r["cat"]]["txns"] += 1
        sk = r["cat"] + "|||" + r["subcat"]
        by_subcat[sk]["amt"]    += r["amt"]
        by_subcat[sk]["pts"]    += r["pts"]
        by_subcat[sk]["txns"]   += 1
        by_subcat[sk]["cat"]    = r["cat"]
        by_subcat[sk]["subcat"] = r["subcat"]

    v_pts = defaultdict(lambda: {"amt": 0, "pts": 0, "count": 0, "cat": ""})
    for r in rows:
        if r["pts"] > 0:
            v_pts[r["desc"]]["amt"]   += r["amt"]
            v_pts[r["desc"]]["pts"]   += r["pts"]
            v_pts[r["desc"]]["count"] += 1
            v_pts[r["desc"]]["cat"]    = r["cat"]

    best_rates = []
    for desc, v in v_pts.items():
        if v["count"] >= 2 and v["amt"] > 1000:
            rate = (v["pts"] / v["amt"]) * 100
            best_rates.append({"desc": desc[:45], "rate": round(rate, 2),
                               "amt": round(v["amt"], 2), "pts": v["pts"],
                               "count": v["count"], "cat": v["cat"]})
    best_rates.sort(key=lambda x: (-x["rate"], -x["amt"]))

    v_all = defaultdict(lambda: {"amt": 0, "pts": 0, "count": 0, "cat": ""})
    for r in rows:
        v_all[r["desc"]]["amt"]   += r["amt"]
        v_all[r["desc"]]["pts"]   += r["pts"]
        v_all[r["desc"]]["count"] += 1
        v_all[r["desc"]]["cat"]    = r["cat"]

    worst_rates = []
    for desc, v in v_all.items():
        if v["count"] >= 2 and v["amt"] > 1000:
            rate = (v["pts"] / v["amt"]) * 100
            worst_rates.append({"desc": desc[:45], "rate": round(rate, 2),
                                "amt": round(v["amt"], 2), "pts": v["pts"],
                                "count": v["count"], "cat": v["cat"]})
    worst_rates.sort(key=lambda x: (x["rate"], -x["amt"]))

    precomputed = {
        "yoy":      {k: {"amt": round(v["amt"], 2), "pts": v["pts"], "txns": v["txns"]}
                     for k, v in sorted(yoy.items())},
        "mom":      {k: {"amt": round(v["amt"], 2), "pts": v["pts"], "txns": v["txns"]}
                     for k, v in sorted(mom.items())},
        "by_cat":   {k: {"amt": round(v["amt"], 2), "pts": v["pts"], "txns": v["txns"]}
                     for k, v in sorted(by_cat.items(), key=lambda x: -x[1]["amt"])},
        "by_subcat": [{"cat": v["cat"], "subcat": v["subcat"], "amt": round(v["amt"], 2),
                       "pts": v["pts"], "txns": v["txns"]}
                      for v in sorted(by_subcat.values(), key=lambda x: -x["amt"])],
        "best_rates":  best_rates[:20],
        "worst_rates": worst_rates[:20],
        "summary": {
            "total_txns":  len(rows),
            "total_spend": round(sum(r["amt"] for r in rows), 2),
            "total_pts":   sum(r["pts"] for r in rows),
            "years":       sorted(list(set(r["year"] for r in rows))),
        },
        "rows": rows,
    }
    return rows, precomputed


# ─────────────────────────────────────────────
#  CSS  (plain string — no f-string needed)
# ─────────────────────────────────────────────

REPORT_CSS = """
:root{--bg:#faf9f5;--bg2:#f3f1ea;--bg3:#e8e6dc;--border:#d8d5c8;--border2:#b0aea5;--dark:#141413;--text:#141413;--text2:#4a4840;--text3:#8a8880;--orange:#d97757;--blue:#6a9bcc;--green:#788c5d;--mid:#b0aea5;--orange-l:rgba(217,119,87,0.12);--blue-l:rgba(106,155,204,0.12);--green-l:rgba(120,140,93,0.12);}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Lora',Georgia,serif;font-size:14px;line-height:1.65;}
.header{background:var(--dark);padding:32px 48px;display:flex;align-items:center;justify-content:space-between;position:relative;overflow:hidden;}
.header::after{content:'';position:absolute;right:0;top:0;bottom:0;width:320px;background:linear-gradient(135deg,transparent 40%,rgba(217,119,87,0.15) 100%);pointer-events:none;}
.header-left h1{font-family:'Poppins',Arial,sans-serif;font-size:26px;font-weight:800;color:#faf9f5;letter-spacing:-0.5px;}
.header-left h1 span{color:var(--orange);}
.header-left .sub{font-family:'DM Mono',monospace;font-size:11px;color:var(--mid);margin-top:3px;}
.card-chip{display:inline-flex;align-items:center;gap:10px;background:rgba(250,249,245,0.07);border:1px solid rgba(250,249,245,0.12);border-radius:8px;padding:10px 16px;}
.chip-icon{width:28px;height:20px;background:linear-gradient(135deg,var(--orange),#e8956a);border-radius:4px;opacity:0.9;}
.card-num{font-family:'DM Mono',monospace;font-size:12px;color:#faf9f5;}
.card-sub{font-size:10px;color:var(--mid);margin-top:8px;font-family:'Poppins',sans-serif;}
.nav{background:#fff;border-bottom:2px solid var(--bg3);display:flex;overflow-x:auto;scrollbar-width:none;padding:0 48px;}
.nav::-webkit-scrollbar{display:none;}
.nav-btn{font-family:'Poppins',sans-serif;font-size:12px;font-weight:600;letter-spacing:0.3px;color:var(--text3);padding:16px 20px;border:none;background:none;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-2px;transition:color 0.2s,border-color 0.2s;white-space:nowrap;}
.nav-btn:hover{color:var(--text2);}
.nav-btn.active{color:var(--orange);border-bottom-color:var(--orange);}
.filters{background:#fff;border-bottom:1px solid var(--border);padding:12px 48px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;}
.filter-label{font-family:'Poppins',sans-serif;font-size:10px;font-weight:600;letter-spacing:0.8px;text-transform:uppercase;color:var(--text3);}
select{background:var(--bg);border:1.5px solid var(--border);color:var(--text);padding:6px 26px 6px 10px;border-radius:6px;font-size:12px;font-family:'Lora',serif;cursor:pointer;outline:none;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23b0aea5'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 8px center;background-size:10px;transition:border-color 0.2s;}
select:focus{border-color:var(--orange);}
.filter-btn{background:var(--bg3);border:1.5px solid var(--border);color:var(--text2);padding:6px 14px;border-radius:6px;font-size:12px;font-family:'Poppins',sans-serif;font-weight:500;cursor:pointer;transition:all 0.2s;}
.filter-btn:hover{background:var(--border);color:var(--text);}
.filter-sep{width:1px;height:20px;background:var(--border);}
.filter-count{font-family:'DM Mono',monospace;font-size:11px;color:var(--text3);}
.main{padding:36px 48px;max-width:1400px;margin:0 auto;}
.panel{display:none;}.panel.active{display:block;}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:32px;}
.kpi{background:#fff;border:1.5px solid var(--border);border-radius:12px;padding:22px 24px;position:relative;overflow:hidden;transition:box-shadow 0.2s,transform 0.2s;}
.kpi:hover{box-shadow:0 4px 24px rgba(20,20,19,0.06);transform:translateY(-1px);}
.kpi-accent{position:absolute;top:0;left:0;right:0;height:3px;border-radius:12px 12px 0 0;}
.kpi.orange .kpi-accent{background:var(--orange);}.kpi.blue .kpi-accent{background:var(--blue);}.kpi.green .kpi-accent{background:var(--green);}.kpi.mid .kpi-accent{background:var(--mid);}.kpi.dark .kpi-accent{background:var(--orange);}
.kpi-label{font-family:'Poppins',sans-serif;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.8px;color:var(--text3);margin-top:4px;}
.kpi-value{font-family:'Poppins',sans-serif;font-size:28px;font-weight:800;letter-spacing:-1px;margin:6px 0 2px;color:var(--dark);}
.kpi.orange .kpi-value{color:var(--orange);}.kpi.blue .kpi-value{color:var(--blue);}.kpi.green .kpi-value{color:var(--green);}.kpi.dark .kpi-value{color:var(--orange);}
.kpi-sub{font-size:11px;color:var(--text3);font-family:'Poppins',sans-serif;}
.section-title{font-family:'Poppins',sans-serif;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:var(--text3);margin-bottom:16px;display:flex;align-items:center;gap:12px;}
.section-title::after{content:'';flex:1;height:1px;background:var(--border);}
.chart-row{display:grid;gap:20px;margin-bottom:24px;}.chart-row.cols-2{grid-template-columns:1fr 1fr;}
.chart-card{background:#fff;border:1.5px solid var(--border);border-radius:12px;padding:26px 28px;transition:box-shadow 0.2s;}
.chart-card:hover{box-shadow:0 4px 20px rgba(20,20,19,0.05);}
.chart-title{font-family:'Poppins',sans-serif;font-size:14px;font-weight:700;color:var(--dark);margin-bottom:3px;}
.chart-sub{font-size:12px;color:var(--text3);font-family:'Poppins',sans-serif;margin-bottom:22px;}
.data-table{width:100%;border-collapse:collapse;}
.data-table th{font-family:'Poppins',sans-serif;font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:0.6px;color:var(--text3);padding:10px 14px;text-align:left;border-bottom:1.5px solid var(--bg3);background:var(--bg);white-space:nowrap;}
.data-table td{padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;color:var(--text);font-family:'Lora',serif;}
.data-table tr:last-child td{border-bottom:none;}.data-table tr:hover td{background:var(--bg);}
.data-table .num{font-family:'DM Mono',monospace;font-size:12px;}.data-table .or{color:var(--orange);font-weight:600;}.data-table .bl{color:var(--blue);}.data-table .gr{color:var(--green);}.data-table .dim{color:var(--text3);}
.bar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;}
.bar-label{font-family:'Poppins',sans-serif;font-size:11px;color:var(--text2);width:160px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:500;}
.bar-track{flex:1;height:7px;background:var(--bg3);border-radius:4px;overflow:hidden;}
.bar-fill{height:100%;border-radius:4px;transition:width 0.7s cubic-bezier(0.4,0,0.2,1);}
.bar-val{font-family:'DM Mono',monospace;font-size:11px;color:var(--text3);width:70px;text-align:right;flex-shrink:0;}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-family:'Poppins',sans-serif;font-weight:600;}
.badge-orange{background:var(--orange-l);color:var(--orange);}.badge-blue{background:var(--blue-l);color:var(--blue);}.badge-green{background:var(--green-l);color:var(--green);}.badge-mid{background:var(--bg3);color:var(--text3);}
.heatmap-grid{display:grid;grid-template-columns:48px repeat(12,1fr);gap:4px;}
.hm-label{font-family:'DM Mono',monospace;font-size:9px;color:var(--text3);display:flex;align-items:center;justify-content:flex-end;padding-right:6px;}
.hm-cell{aspect-ratio:1.4;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:8.5px;font-family:'DM Mono',monospace;cursor:pointer;transition:opacity 0.2s,transform 0.15s;border:1px solid transparent;}
.hm-cell:hover{opacity:0.75;transform:scale(1.08);}
.hm-header{font-family:'Poppins',sans-serif;font-size:9px;font-weight:600;color:var(--text3);text-align:center;padding-bottom:4px;}
.rate-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px;}
.rate-card{background:#fff;border:1.5px solid var(--border);border-radius:10px;overflow:hidden;transition:box-shadow 0.2s,transform 0.2s;}
.rate-card:hover{box-shadow:0 3px 16px rgba(20,20,19,0.07);transform:translateY(-1px);}
.rate-card-bar{height:3px;}.rate-card-body{padding:14px 16px;}
.rate-vendor{font-family:'Poppins',sans-serif;font-size:12px;font-weight:600;color:var(--dark);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:2px;}
.rate-cat{font-size:10px;color:var(--text3);font-family:'Poppins',sans-serif;margin-bottom:10px;}
.rate-bottom{display:flex;align-items:flex-end;justify-content:space-between;}
.rate-pts{font-family:'Poppins',sans-serif;font-size:22px;font-weight:800;letter-spacing:-0.5px;line-height:1;}
.rate-pts-unit{font-size:11px;font-weight:400;color:var(--text3);margin-left:2px;}
.rate-meta{font-family:'DM Mono',monospace;font-size:10px;color:var(--text3);text-align:right;line-height:1.6;}
.rate-rank{font-family:'DM Mono',monospace;font-size:9px;font-weight:500;width:20px;height:20px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;margin-right:6px;flex-shrink:0;}
.detail-wrap{max-height:580px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border) transparent;}
::-webkit-scrollbar{width:4px;height:4px;}::-webkit-scrollbar-track{background:transparent;}::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}
.footer{background:var(--dark);margin-top:60px;padding:20px 48px;display:flex;justify-content:space-between;align-items:center;font-size:11px;color:var(--mid);font-family:'DM Mono',monospace;}
.footer .logo{font-family:'Poppins',sans-serif;font-weight:700;color:#faf9f5;font-size:13px;}.footer .logo span{color:var(--orange);}
@keyframes slideUp{from{opacity:0;transform:translateY(12px);}to{opacity:1;transform:translateY(0);}}
.panel.active>*{animation:slideUp 0.3s ease both;}
.panel.active>*:nth-child(2){animation-delay:0.05s;}.panel.active>*:nth-child(3){animation-delay:0.10s;}.panel.active>*:nth-child(4){animation-delay:0.15s;}
@media(max-width:900px){.header{padding:20px;flex-direction:column;gap:16px;}.main{padding:20px;}.nav{padding:0 20px;}.filters{padding:10px 20px;}.chart-row.cols-2{grid-template-columns:1fr;}.footer{padding:16px 20px;flex-direction:column;gap:6px;text-align:center;}}
"""

# ─────────────────────────────────────────────
#  JAVASCRIPT  (raw string — no escaping at all)
# ─────────────────────────────────────────────

REPORT_JS_TEMPLATE = r"""
const RAW = DATA_JSON_PLACEHOLDER;
const CATS = Object.keys(RAW.by_cat);
const CAT_PALETTE = ['#d97757','#6a9bcc','#788c5d','#b0aea5','#c45a3a','#4a7bac','#5a7040','#9a8a7a','#e09070','#8abce0','#a0b080','#706050','#c87050'];
const CAT_COLOR = {};
CATS.forEach((c,i) => CAT_COLOR[c] = CAT_PALETTE[i % CAT_PALETTE.length]);
const MONTHS = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const CARD_COLORS = ['rgba(217,119,87,0.8)','rgba(106,155,204,0.8)','rgba(120,140,93,0.8)','rgba(176,174,165,0.8)','rgba(196,90,58,0.8)','rgba(200,112,80,0.6)'];

Chart.defaults.font.family = "'Poppins', Arial, sans-serif";
Chart.defaults.color = '#8a8880';

// Populate filter dropdowns
const catSel = document.getElementById('fCat');
CATS.forEach(c => { const o = document.createElement('option'); o.value = c; o.textContent = c; catSel.appendChild(o); });
[...new Set(RAW.rows.map(r => r.bank || 'Unknown'))].sort().forEach(b => {
  const o = document.createElement('option'); o.value = b; o.textContent = b;
  document.getElementById('fBank').appendChild(o);
});
[...new Set(RAW.rows.map(r => r.card || 'Unknown'))].sort().forEach(c => {
  const o = document.createElement('option'); o.value = c; o.textContent = c;
  document.getElementById('fCard').appendChild(o);
});

const fc = n => {
  if (n >= 10000000) return '₹' + (n/10000000).toFixed(2) + 'Cr';
  if (n >= 100000)   return '₹' + (n/100000).toFixed(2)   + 'L';
  if (n >= 1000)     return '₹' + (n/1000).toFixed(1)     + 'K';
  return '₹' + n.toFixed(0);
};
const fp = n => n >= 1000 ? (n/1000).toFixed(1) + 'K pts' : n + ' pts';

let filteredRows = RAW.rows;
const charts = {};

function applyFilters() {
  const fYear   = document.getElementById('fYear').value;
  const fMonth  = document.getElementById('fMonth').value;
  const fBank   = document.getElementById('fBank').value;
  const fCard   = document.getElementById('fCard').value;
  const fCat    = document.getElementById('fCat').value;
  const subcatSel = document.getElementById('fSubcat');
  const prev = subcatSel.value;
  subcatSel.innerHTML = '<option value="all">All Subcategories</option>';
  [...new Set(RAW.rows.filter(r => fCat === 'all' || r.cat === fCat).map(r => r.subcat))].sort()
    .forEach(s => { const o = document.createElement('option'); o.value = s; o.textContent = s; subcatSel.appendChild(o); });
  if (prev !== 'all') subcatSel.value = prev;
  const fSubcat = subcatSel.value;
  filteredRows = RAW.rows.filter(r =>
    (fYear   === 'all' || r.year  == fYear)   &&
    (fMonth  === 'all' || r.month == fMonth)  &&
    (fBank   === 'all' || (r.bank  || 'Unknown') === fBank)  &&
    (fCard   === 'all' || (r.card  || 'Unknown') === fCard)  &&
    (fCat    === 'all' || r.cat    === fCat)  &&
    (fSubcat === 'all' || r.subcat === fSubcat)
  );
  document.getElementById('filter-count').textContent = filteredRows.length + ' transactions';
  renderCurrent();
}

function resetFilters() {
  ['fYear','fMonth','fBank','fCard','fCat','fSubcat'].forEach(id => document.getElementById(id).value = 'all');
  applyFilters();
}

let currentPanel = 'overview';
document.querySelectorAll('.nav-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const p = btn.dataset.panel;
    document.querySelectorAll('.panel').forEach(el => el.classList.remove('active'));
    document.getElementById('panel-' + p).classList.add('active');
    currentPanel = p;
    renderCurrent();
  });
});

function renderCurrent() {
  if      (currentPanel === 'overview')   renderOverview();
  else if (currentPanel === 'yoy')        renderYOY();
  else if (currentPanel === 'mom')        renderMOM();
  else if (currentPanel === 'categories') renderCategories();
  else if (currentPanel === 'points')     renderPoints();
  else if (currentPanel === 'detail')     renderDetail();
}

function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }

function aggRows(rows) {
  const r = { amt:0, pts:0, txns:rows.length, bycat:{}, byyear:{}, bymonth:{}, bysubcat:{} };
  rows.forEach(row => {
    r.amt += row.amt; r.pts += row.pts;
    r.bycat[row.cat]   = (r.bycat[row.cat]   || 0) + row.amt;
    r.byyear[row.year] = (r.byyear[row.year] || 0) + row.amt;
    const mk = row.year + '-' + String(row.month).padStart(2,'0');
    r.bymonth[mk] = (r.bymonth[mk] || 0) + row.amt;
    const sk = row.cat + '|||' + row.subcat;
    if (!r.bysubcat[sk]) r.bysubcat[sk] = { amt:0, pts:0, txns:0, cat:row.cat, subcat:row.subcat };
    r.bysubcat[sk].amt += row.amt; r.bysubcat[sk].pts += row.pts; r.bysubcat[sk].txns++;
  });
  return r;
}

const gridOpts = { color: 'rgba(20,20,19,0.06)' };
const tickOpts = { color: '#8a8880', font: { size: 11 } };

function computeBestWorst(rows) {
  const vPts = {};
  rows.forEach(r => {
    if (r.pts > 0) {
      if (!vPts[r.desc]) vPts[r.desc] = { amt:0, pts:0, count:0, cat:r.cat };
      vPts[r.desc].amt += r.amt; vPts[r.desc].pts += r.pts; vPts[r.desc].count++;
    }
  });
  const best = [];
  Object.entries(vPts).forEach(([desc,v]) => {
    if (v.count >= 2 && v.amt > 1000) {
      best.push({ desc: desc.slice(0,45), rate: +((v.pts/v.amt)*100).toFixed(2), amt: +v.amt.toFixed(0), pts: v.pts, cat: v.cat });
    }
  });
  best.sort((a,b) => b.rate - a.rate || b.amt - a.amt);

  const vAll = {};
  rows.forEach(r => {
    if (!vAll[r.desc]) vAll[r.desc] = { amt:0, pts:0, count:0, cat:r.cat };
    vAll[r.desc].amt += r.amt; vAll[r.desc].pts += r.pts; vAll[r.desc].count++;
  });
  const worst = [];
  Object.entries(vAll).forEach(([desc,v]) => {
    if (v.count >= 2 && v.amt > 1000) {
      worst.push({ desc: desc.slice(0,45), rate: +((v.pts/v.amt)*100).toFixed(2), amt: +v.amt.toFixed(0), pts: v.pts, cat: v.cat });
    }
  });
  worst.sort((a,b) => a.rate - b.rate || b.amt - a.amt);
  return { best: best.slice(0,12), worst: worst.slice(0,12) };
}

function rateCard(v, mode, rank) {
  const isZero = v.rate === 0;
  const accentColor = mode === 'best'
    ? (v.rate >= 3.3 ? 'var(--green)' : v.rate >= 2.5 ? 'var(--blue)' : 'var(--mid)')
    : (isZero ? 'var(--orange)' : '#c87050');
  const barColor = mode === 'best' ? accentColor : (isZero ? 'rgba(217,119,87,0.8)' : 'rgba(200,112,80,0.6)');
  return `<div class="rate-card">
    <div class="rate-card-bar" style="background:${barColor};"></div>
    <div class="rate-card-body">
      <div style="display:flex;align-items:flex-start;gap:6px;margin-bottom:4px;">
        <span class="rate-rank" style="background:${barColor}22;color:${barColor};">#${rank}</span>
        <div style="min-width:0;">
          <div class="rate-vendor" title="${v.desc}">${v.desc}</div>
          <div class="rate-cat">${v.cat}${isZero ? ' · <strong style="color:var(--orange)">Zero earn</strong>' : ''}</div>
        </div>
      </div>
      <div class="rate-bottom">
        <div class="rate-pts" style="color:${accentColor}">${isZero ? '0' : v.rate.toFixed(2)}<span class="rate-pts-unit"> pts/₹100</span></div>
        <div class="rate-meta">${fp(v.pts)}<br>₹${v.amt.toLocaleString('en-IN')}</div>
      </div>
    </div>
  </div>`;
}

// ── OVERVIEW ──────────────────────────────────────────────────────────────────
function renderOverview() {
  const a = aggRows(filteredRows);
  const invAmt  = a.bycat['Investments & Assets'] || 0;
  const avgRate = a.amt > 0 ? (a.pts / a.amt * 100).toFixed(2) : 0;
  const months  = Object.keys(a.bymonth).length || 1;

  document.getElementById('kpi-grid').innerHTML = `
    <div class="kpi orange"><div class="kpi-accent"></div><div class="kpi-label">Total Spend</div><div class="kpi-value">${fc(a.amt)}</div><div class="kpi-sub">${a.txns} transactions</div></div>
    <div class="kpi blue"><div class="kpi-accent"></div><div class="kpi-label">Lifestyle Spend</div><div class="kpi-value">${fc(a.amt - invAmt)}</div><div class="kpi-sub">excl. investments &amp; assets</div></div>
    <div class="kpi green"><div class="kpi-accent"></div><div class="kpi-label">Points Earned</div><div class="kpi-value">${fp(a.pts)}</div><div class="kpi-sub">est. ₹${(a.pts*0.5).toLocaleString('en-IN')} @ 50p/pt</div></div>
    <div class="kpi mid"><div class="kpi-accent"></div><div class="kpi-label">Avg Reward Rate</div><div class="kpi-value">${avgRate}</div><div class="kpi-sub">points per ₹100 spent</div></div>
    <div class="kpi dark"><div class="kpi-accent"></div><div class="kpi-label">Avg Monthly</div><div class="kpi-value">${fc(a.amt / months)}</div><div class="kpi-sub">spend per active month</div></div>`;

  // Heatmap
  const allM = {};
  RAW.rows.forEach(r => { const k = r.year + '-' + String(r.month).padStart(2,'0'); allM[k] = (allM[k]||0) + r.amt; });
  const maxV = Math.max(...Object.values(allM));
  const allYears = [...new Set(RAW.rows.map(r => r.year))].sort();
  let hm = '<div class="heatmap-grid"><div></div>';
  for (let m = 1; m <= 12; m++) hm += `<div class="hm-header">${MONTHS[m]}</div>`;
  allYears.forEach(y => {
    hm += `<div class="hm-label">${y}</div>`;
    for (let m = 1; m <= 12; m++) {
      const k = y + '-' + String(m).padStart(2,'0');
      const v = allM[k] || 0;
      const t = v / maxV;
      const r2=Math.round(217*t+232*(1-t)), g2=Math.round(119*t+230*(1-t)), b2=Math.round(87*t+220*(1-t));
      const bg = v > 0 ? `rgb(${r2},${g2},${b2})` : '#f3f1ea';
      const tc = t > 0.55 ? '#fff' : '#4a4840';
      hm += `<div class="hm-cell" style="background:${bg};color:${tc};border-color:rgba(217,119,87,${(t*0.25).toFixed(2)});" title="${y} ${MONTHS[m]}: ${fc(v)}">${v > 0 ? fc(v) : ''}</div>`;
    }
  });
  hm += '</div>';
  document.getElementById('heatmap-container').innerHTML = hm;

  // Annual spend bar
  const yy = Object.keys(a.byyear).sort();
  destroyChart('yoyChart');
  charts['yoyChart'] = new Chart(document.getElementById('yoyChart'), {
    type:'bar', data:{ labels:yy, datasets:[{ label:'Annual Spend', data:yy.map(y=>a.byyear[y]), backgroundColor:'rgba(217,119,87,0.75)', borderRadius:6, borderSkipped:false }] },
    options:{ responsive:true, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>fc(c.raw)}} }, scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });

  // Category donut
  const topCats = Object.entries(a.bycat).sort((a,b)=>b[1]-a[1]).slice(0,9);
  destroyChart('catPie');
  charts['catPie'] = new Chart(document.getElementById('catPie'), {
    type:'doughnut', data:{ labels:topCats.map(([c])=>c), datasets:[{ data:topCats.map(([,v])=>v), backgroundColor:topCats.map(([c])=>CAT_COLOR[c]), borderWidth:2, borderColor:'#fff', hoverOffset:8 }] },
    options:{ responsive:true, plugins:{ legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:10}}, tooltip:{callbacks:{label:c=>c.label+': '+fc(c.raw)}} } }
  });

  // Top 10 category horizontal bars
  const catSorted = Object.entries(a.bycat).sort((a,b)=>b[1]-a[1]).slice(0,10);
  const catMax = catSorted[0]?.[1] || 1;
  document.getElementById('cat-bars').innerHTML = catSorted.map(([cat,amt]) =>
    `<div class="bar-row"><div class="bar-label" title="${cat}">${cat}</div><div class="bar-track"><div class="bar-fill" style="width:${(amt/catMax*100).toFixed(1)}%;background:${CAT_COLOR[cat]};"></div></div><div class="bar-val">${fc(amt)}</div></div>`
  ).join('');

  // Card split donut
  const cardSplit = {};
  filteredRows.forEach(r => { const k = r.card || 'Unknown'; cardSplit[k] = (cardSplit[k]||0) + r.amt; });
  const cardLabels = Object.keys(cardSplit);
  destroyChart('cardSplitChart');
  charts['cardSplitChart'] = new Chart(document.getElementById('cardSplitChart'), {
    type:'doughnut', data:{ labels:cardLabels, datasets:[{ data:Object.values(cardSplit), backgroundColor:CARD_COLORS.slice(0,cardLabels.length), borderWidth:2, borderColor:'#fff', hoverOffset:8 }] },
    options:{ responsive:true, plugins:{ legend:{position:'right',labels:{font:{size:11},boxWidth:12,padding:8}}, tooltip:{callbacks:{label:c=>c.label+': '+fc(c.raw)}} } }
  });

  // Cardholder split donut
  const holders = {};
  filteredRows.forEach(r => { holders[r.cardholder] = (holders[r.cardholder]||0) + r.amt; });
  destroyChart('holderChart');
  charts['holderChart'] = new Chart(document.getElementById('holderChart'), {
    type:'doughnut', data:{ labels:Object.keys(holders).map(h=>h.split(' ')[0]), datasets:[{ data:Object.values(holders), backgroundColor:['rgba(217,119,87,0.8)','rgba(106,155,204,0.8)'], borderWidth:2, borderColor:'#fff' }] },
    options:{ responsive:true, plugins:{ legend:{position:'bottom',labels:{font:{size:11}}}, tooltip:{callbacks:{label:c=>c.label+': '+fc(c.raw)}} } }
  });
}

// ── YOY ───────────────────────────────────────────────────────────────────────
function renderYOY() {
  const byYear = {};
  filteredRows.forEach(r => {
    if (!byYear[r.year]) byYear[r.year] = { amt:0, pts:0, txns:0, bycat:{} };
    byYear[r.year].amt += r.amt; byYear[r.year].pts += r.pts; byYear[r.year].txns++;
    byYear[r.year].bycat[r.cat] = (byYear[r.year].bycat[r.cat]||0) + r.amt;
  });
  const ay = Object.keys(byYear).sort();

  destroyChart('yoyBarChart');
  charts['yoyBarChart'] = new Chart(document.getElementById('yoyBarChart'), {
    type:'bar',
    data:{ labels:ay, datasets:[
      { label:'Spend', data:ay.map(y=>byYear[y].amt), backgroundColor:'rgba(217,119,87,0.75)', borderRadius:6, borderSkipped:false, yAxisID:'y' },
      { label:'Points', data:ay.map(y=>byYear[y].pts), type:'line', borderColor:'#788c5d', backgroundColor:'rgba(120,140,93,0.08)', borderWidth:2.5, pointRadius:5, pointBackgroundColor:'#788c5d', yAxisID:'y2', tension:0.3 }
    ] },
    options:{ responsive:true,
      plugins:{ legend:{labels:{font:{size:11}}}, tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.dataset.yAxisID==='y2'?fp(c.raw):fc(c.raw))}} },
      scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)},position:'left'}, y2:{grid:{display:false},ticks:{...tickOpts,color:'#788c5d'},position:'right'} }
    }
  });

  const topC = Object.entries(RAW.by_cat).sort((a,b)=>b[1].amt-a[1].amt).slice(0,10).map(([c])=>c);
  destroyChart('yoyCatStack');
  charts['yoyCatStack'] = new Chart(document.getElementById('yoyCatStack'), {
    type:'bar',
    data:{ labels:ay, datasets:topC.map((cat,i) => ({ label:cat, data:ay.map(y=>(byYear[y]?.bycat[cat])||0), backgroundColor:CAT_COLOR[cat]+'cc', borderRadius:i===0?6:0, stack:'s' })) },
    options:{ responsive:true, plugins:{ legend:{labels:{font:{size:10}}}, tooltip:{callbacks:{label:c=>c.dataset.label+': '+fc(c.raw)}} },
      scales:{ x:{stacked:true,grid:gridOpts,ticks:tickOpts}, y:{stacked:true,grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });

  document.getElementById('yoy-table').innerHTML =
    '<tr><th>Year</th><th style="text-align:right">Spend</th><th style="text-align:right">Txns</th><th style="text-align:right">Points</th><th style="text-align:right">Rate</th></tr>' +
    ay.map(y => {
      const rate = byYear[y].amt > 0 ? (byYear[y].pts/byYear[y].amt*100).toFixed(2) : '0';
      return `<tr><td><span class="badge badge-orange">${y}</span></td><td class="num or" style="text-align:right">${fc(byYear[y].amt)}</td><td class="num dim" style="text-align:right">${byYear[y].txns}</td><td class="num gr" style="text-align:right">${fp(byYear[y].pts)}</td><td class="num bl" style="text-align:right">${rate} /₹100</td></tr>`;
    }).join('');
}

// ── MOM ───────────────────────────────────────────────────────────────────────
function renderMOM() {
  const bm = {};
  filteredRows.forEach(r => {
    const k = r.year + '-' + String(r.month).padStart(2,'0');
    if (!bm[k]) bm[k] = { amt:0, pts:0, txns:0, label:MONTHS[r.month]+' '+r.year };
    bm[k].amt += r.amt; bm[k].pts += r.pts; bm[k].txns++;
  });
  const mk = Object.keys(bm).sort();

  destroyChart('momLineChart');
  charts['momLineChart'] = new Chart(document.getElementById('momLineChart'), {
    type:'line',
    data:{ labels:mk.map(k=>bm[k].label), datasets:[{ label:'Monthly Spend', data:mk.map(k=>bm[k].amt), borderColor:'#d97757', backgroundColor:'rgba(217,119,87,0.07)', borderWidth:2.5, pointRadius:3, pointBackgroundColor:'#d97757', fill:true, tension:0.4 }] },
    options:{ responsive:true, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>fc(c.raw)}} }, scales:{ x:{grid:gridOpts,ticks:{...tickOpts,maxTicksLimit:18}}, y:{grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });

  const seasonal = {};
  filteredRows.forEach(r => { seasonal[r.month] = (seasonal[r.month]||0) + r.amt; });
  const sData = Array.from({length:12}, (_,i) => {
    const m = i+1;
    const yrs = new Set(filteredRows.filter(r=>r.month===m).map(r=>r.year)).size;
    return yrs > 0 ? (seasonal[m]||0) / yrs : 0;
  });
  destroyChart('seasonalChart');
  charts['seasonalChart'] = new Chart(document.getElementById('seasonalChart'), {
    type:'bar',
    data:{ labels:MONTHS.slice(1), datasets:[{ label:'Avg Monthly Spend', data:sData, backgroundColor:'rgba(106,155,204,0.7)', borderRadius:5, borderSkipped:false }] },
    options:{ responsive:true, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>fc(c.raw)}} }, scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });

  const topM = Object.entries(bm).sort((a,b)=>b[1].amt-a[1].amt).slice(0,10);
  document.getElementById('top-months-table').innerHTML =
    '<tr><th>#</th><th>Month</th><th style="text-align:right">Spend</th><th style="text-align:right">Txns</th></tr>' +
    topM.map(([,v],i) => `<tr><td class="dim num">${i+1}</td><td>${v.label}</td><td class="num or" style="text-align:right">${fc(v.amt)}</td><td class="num dim" style="text-align:right">${v.txns}</td></tr>`).join('');

  // Category mix by month stacked
  const topCats10 = Object.entries(filteredRows.reduce((acc,r)=>{ acc[r.cat]=(acc[r.cat]||0)+r.amt; return acc; }, {}))
    .sort((a,b)=>b[1]-a[1]).slice(0,10).map(([c])=>c);
  const catByMonth = {};
  filteredRows.forEach(r => {
    const k = r.year + '-' + String(r.month).padStart(2,'0');
    if (!catByMonth[k]) catByMonth[k] = {};
    catByMonth[k][r.cat] = (catByMonth[k][r.cat]||0) + r.amt;
  });
  const allMK = Object.keys(catByMonth).sort();
  const allML = allMK.map(k => { const [y,m] = k.split('-'); return MONTHS[+m]+' '+y; });
  destroyChart('momCatStack');
  charts['momCatStack'] = new Chart(document.getElementById('momCatStack'), {
    type:'bar',
    data:{ labels:allML, datasets:topCats10.map((cat,i) => ({ label:cat, data:allMK.map(k=>(catByMonth[k]?.[cat])||0), backgroundColor:CAT_COLOR[cat]+'cc', borderRadius:i===0?4:0, stack:'s' })) },
    options:{ responsive:true, plugins:{ legend:{labels:{font:{size:10},boxWidth:12,padding:8}}, tooltip:{callbacks:{label:c=>c.dataset.label+': '+fc(c.raw)}} },
      scales:{ x:{stacked:true,grid:gridOpts,ticks:{...tickOpts,maxTicksLimit:24}}, y:{stacked:true,grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });
}

// ── CATEGORIES ────────────────────────────────────────────────────────────────
function renderCategories() {
  const bc = {}, bs = {};
  filteredRows.forEach(r => {
    if (!bc[r.cat]) bc[r.cat] = { amt:0, pts:0, txns:0 };
    bc[r.cat].amt += r.amt; bc[r.cat].pts += r.pts; bc[r.cat].txns++;
    const sk = r.cat+'|||'+r.subcat;
    if (!bs[sk]) bs[sk] = { amt:0, pts:0, txns:0, cat:r.cat, subcat:r.subcat };
    bs[sk].amt += r.amt; bs[sk].pts += r.pts; bs[sk].txns++;
  });

  const catSorted2 = Object.entries(bc).sort((a,b)=>b[1].amt-a[1].amt);
  const catMax2 = catSorted2[0]?.[1].amt || 1;
  document.getElementById('all-cat-bars').innerHTML = catSorted2.map(([cat,v]) =>
    `<div class="bar-row"><div class="bar-label" title="${cat}">${cat}</div><div class="bar-track"><div class="bar-fill" style="width:${(v.amt/catMax2*100).toFixed(1)}%;background:${CAT_COLOR[cat]};"></div></div><div class="bar-val">${fc(v.amt)}</div></div>`
  ).join('');

  const catYrs = Object.keys(filteredRows.reduce((a,r)=>{ a[r.year]=1; return a; }, {})).sort();
  const topC2 = catSorted2.slice(0,6).map(([c])=>c);
  const cby = {};
  filteredRows.forEach(r => { if (!cby[r.year]) cby[r.year]={}; cby[r.year][r.cat]=(cby[r.year][r.cat]||0)+r.amt; });
  destroyChart('catTrendChart');
  charts['catTrendChart'] = new Chart(document.getElementById('catTrendChart'), {
    type:'line',
    data:{ labels:catYrs, datasets:topC2.map(cat => ({ label:cat, data:catYrs.map(y=>(cby[y]?.[cat])||0), borderColor:CAT_COLOR[cat], backgroundColor:'transparent', borderWidth:2.5, pointRadius:4, pointBackgroundColor:CAT_COLOR[cat], tension:0.3 })) },
    options:{ responsive:true, plugins:{ legend:{labels:{font:{size:10}}}, tooltip:{callbacks:{label:c=>c.dataset.label+': '+fc(c.raw)}} }, scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:gridOpts,ticks:{...tickOpts,callback:v=>fc(v)}} } }
  });

  const scSorted = Object.values(bs).sort((a,b)=>b.amt-a.amt);
  const tAmt = scSorted.reduce((s,v)=>s+v.amt,0) || 1;
  document.getElementById('subcat-table').innerHTML =
    '<tr><th>Category</th><th>Subcategory</th><th style="text-align:right">Spend</th><th style="text-align:right">Share</th><th style="text-align:right">Txns</th><th style="text-align:right">Points</th></tr>' +
    scSorted.map(v =>
      `<tr><td><span class="badge" style="background:${CAT_COLOR[v.cat]}18;color:${CAT_COLOR[v.cat]}">${v.cat}</span></td><td style="color:var(--text2)">${v.subcat}</td><td class="num or" style="text-align:right">${fc(v.amt)}</td><td class="num dim" style="text-align:right">${(v.amt/tAmt*100).toFixed(1)}%</td><td class="num dim" style="text-align:right">${v.txns}</td><td class="num gr" style="text-align:right">${v.pts}</td></tr>`
    ).join('');
}

// ── POINTS ────────────────────────────────────────────────────────────────────
function renderPoints() {
  const tot     = filteredRows.reduce((s,r)=>s+r.amt,0);
  const pts     = filteredRows.reduce((s,r)=>s+r.pts,0);
  const rate    = tot > 0 ? (pts/tot*100).toFixed(2) : 0;
  const zero    = filteredRows.filter(r=>r.pts===0&&r.amt>0);
  const zeroAmt = zero.reduce((s,r)=>s+r.amt,0);

  document.getElementById('pts-kpi-grid').innerHTML = `
    <div class="kpi green"><div class="kpi-accent"></div><div class="kpi-label">Total Points</div><div class="kpi-value">${fp(pts)}</div><div class="kpi-sub">est. ₹${(pts*0.5).toLocaleString('en-IN')} value</div></div>
    <div class="kpi orange"><div class="kpi-accent"></div><div class="kpi-label">Avg Reward Rate</div><div class="kpi-value">${rate}</div><div class="kpi-sub">points per ₹100 spent</div></div>
    <div class="kpi blue"><div class="kpi-accent"></div><div class="kpi-label">Zero-Earn Spend</div><div class="kpi-value">${fc(zeroAmt)}</div><div class="kpi-sub">${zero.length} txns · ${tot>0?(zeroAmt/tot*100).toFixed(1):0}% of total</div></div>
    <div class="kpi mid"><div class="kpi-accent"></div><div class="kpi-label">Missed Points</div><div class="kpi-value">${fp(Math.round(zeroAmt*3.33/100))}</div><div class="kpi-sub">potential @ 3.33/₹100</div></div>`;

  const pby = {};
  filteredRows.forEach(r => { pby[r.year] = (pby[r.year]||0) + r.pts; });
  const py = Object.keys(pby).sort();
  destroyChart('ptsYoyChart');
  charts['ptsYoyChart'] = new Chart(document.getElementById('ptsYoyChart'), {
    type:'bar', data:{ labels:py, datasets:[{ label:'Points Earned', data:py.map(y=>pby[y]), backgroundColor:'rgba(120,140,93,0.75)', borderRadius:6, borderSkipped:false }] },
    options:{ responsive:true, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>fp(c.raw)}} }, scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:gridOpts,ticks:tickOpts} } }
  });

  const cr = {};
  filteredRows.forEach(r => { if (!cr[r.cat]) cr[r.cat]={amt:0,pts:0}; cr[r.cat].amt+=r.amt; cr[r.cat].pts+=r.pts; });
  const crs = Object.entries(cr).filter(([,v])=>v.amt>0).map(([c,v])=>[c,v.pts/v.amt*100]).sort((a,b)=>b[1]-a[1]);
  destroyChart('ptsRateChart');
  charts['ptsRateChart'] = new Chart(document.getElementById('ptsRateChart'), {
    type:'bar', data:{ labels:crs.map(([c])=>c), datasets:[{ label:'Pts/₹100', data:crs.map(([,r])=>+r.toFixed(2)), backgroundColor:crs.map(([c])=>CAT_COLOR[c]+'cc'), borderRadius:4, borderSkipped:false }] },
    options:{ indexAxis:'y', responsive:true, plugins:{ legend:{display:false}, tooltip:{callbacks:{label:c=>c.raw+' pts/₹100'}} }, scales:{ x:{grid:gridOpts,ticks:tickOpts}, y:{grid:{display:false},ticks:{...tickOpts,font:{size:10}}} } }
  });

  const { best, worst } = computeBestWorst(filteredRows);
  document.getElementById('best-rates').innerHTML  = best.map((v,i)  => rateCard(v,'best',i+1)).join('');
  document.getElementById('worst-rates').innerHTML = worst.map((v,i) => rateCard(v,'worst',i+1)).join('');
}

// ── DETAIL ────────────────────────────────────────────────────────────────────
function renderDetail() {
  const disp = filteredRows.slice().sort((a,b) => {
    if (b.year  !== a.year)  return b.year  - a.year;
    if (b.month !== a.month) return b.month - a.month;
    return b.day - a.day;
  }).slice(0,500);
  document.getElementById('detail-title').textContent = `Transactions — showing ${Math.min(filteredRows.length,500)} of ${filteredRows.length}`;
  document.getElementById('detail-sub').textContent   = filteredRows.length > 500 ? 'Showing most recent 500. Use filters to narrow.' : '';
  document.getElementById('detail-tbody').innerHTML = disp.map(r =>
    `<tr>
      <td class="num dim">${r.date}</td>
      <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${r.desc}">${r.desc}</td>
      <td style="font-size:10px;color:var(--text3);font-family:'Poppins',sans-serif;white-space:nowrap;">${r.card||''}</td>
      <td><span class="badge" style="background:${CAT_COLOR[r.cat]}18;color:${CAT_COLOR[r.cat]};font-size:9px;">${r.cat}</span></td>
      <td class="dim" style="font-size:11px;font-family:'Poppins',sans-serif;">${r.subcat}</td>
      <td class="num or" style="text-align:right">${fc(r.amt)}</td>
      <td class="num gr" style="text-align:right">${r.pts||'—'}</td>
      <td class="num" style="text-align:right;color:${r.pct>3?'var(--green)':r.pct>0?'var(--text3)':'var(--orange)'}">${r.pct>0?r.pct.toFixed(2)+' /₹100':'—'}</td>
    </tr>`
  ).join('');
}

// Boot
applyFilters();
renderOverview();
"""


# ─────────────────────────────────────────────
#  HTML ASSEMBLY
# ─────────────────────────────────────────────

def build_report_html(precomputed: dict, config: dict, today_str: str) -> str:
    card_name  = config.get("card", {}).get("name", "Credit Card")
    cardholder = config.get("cardholders", {}).get("primary", "Cardholder")
    years      = precomputed["summary"]["years"]
    date_range = f"{years[0]} \u2013 {years[-1]}" if years else "All time"

    year_opts = "\n".join(
        f'    <option value="{y}">{y}</option>' for y in sorted(years)
    )

    # Inject data into JS — simple string replacement, not f-string
    data_json = json.dumps(precomputed)
    js = REPORT_JS_TEMPLATE.replace("DATA_JSON_PLACEHOLDER", data_json)

    # HTML shell uses f-string only for simple string variables (card_name etc.)
    # CSS and JS are injected via .format() with no {} in their content
    html = (
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "<meta charset=\"UTF-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
        f"<title>CredInsights \u00b7 {card_name}</title>\n"
        "<link rel=\"preconnect\" href=\"https://fonts.googleapis.com\">\n"
        "<link href=\"https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700;800&family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&display=swap\" rel=\"stylesheet\">\n"
        "<script src=\"https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js\"></script>\n"
        "<style>" + REPORT_CSS + "</style>\n"
        "</head>\n"
        "<body>\n\n"

        "<div class=\"header\">\n"
        "  <div class=\"header-left\">\n"
        "    <h1>Cred<span>Insights</span></h1>\n"
        f"    <div class=\"sub\">{card_name} \u00b7 {cardholder} \u00b7 {date_range}</div>\n"
        "  </div>\n"
        "  <div class=\"header-right\">\n"
        "    <div class=\"card-chip\"><div class=\"chip-icon\"></div><span class=\"card-num\">\u00b7\u00b7\u00b7\u00b7 \u00b7\u00b7\u00b7\u00b7 \u00b7\u00b7\u00b7\u00b7 \u00b7\u00b7\u00b7\u00b7</span></div>\n"
        f"    <div class=\"card-sub\">{card_name} \u00b7 Auto-generated</div>\n"
        "  </div>\n"
        "</div>\n\n"

        "<nav class=\"nav\">\n"
        "  <button class=\"nav-btn active\" data-panel=\"overview\">Overview</button>\n"
        "  <button class=\"nav-btn\" data-panel=\"yoy\">Year on Year</button>\n"
        "  <button class=\"nav-btn\" data-panel=\"mom\">Month on Month</button>\n"
        "  <button class=\"nav-btn\" data-panel=\"categories\">Categories</button>\n"
        "  <button class=\"nav-btn\" data-panel=\"points\">Points Analysis</button>\n"
        "  <button class=\"nav-btn\" data-panel=\"detail\">Transactions</button>\n"
        "</nav>\n\n"

        "<div class=\"filters\">\n"
        "  <span class=\"filter-label\">Filter by</span>\n"
        "  <select id=\"fYear\" onchange=\"applyFilters()\">\n"
        "    <option value=\"all\">All Years</option>\n"
        + year_opts + "\n"
        "  </select>\n"
        "  <select id=\"fMonth\" onchange=\"applyFilters()\">\n"
        "    <option value=\"all\">All Months</option>\n"
        "    <option value=\"1\">January</option><option value=\"2\">February</option><option value=\"3\">March</option>\n"
        "    <option value=\"4\">April</option><option value=\"5\">May</option><option value=\"6\">June</option>\n"
        "    <option value=\"7\">July</option><option value=\"8\">August</option><option value=\"9\">September</option>\n"
        "    <option value=\"10\">October</option><option value=\"11\">November</option><option value=\"12\">December</option>\n"
        "  </select>\n"
        "  <select id=\"fBank\" onchange=\"applyFilters()\"><option value=\"all\">All Banks</option></select>\n"
        "  <select id=\"fCard\" onchange=\"applyFilters()\"><option value=\"all\">All Cards</option></select>\n"
        "  <select id=\"fCat\" onchange=\"applyFilters()\"><option value=\"all\">All Categories</option></select>\n"
        "  <select id=\"fSubcat\" onchange=\"applyFilters()\"><option value=\"all\">All Subcategories</option></select>\n"
        "  <div class=\"filter-sep\"></div>\n"
        "  <button class=\"filter-btn\" onclick=\"resetFilters()\">&#8634; Reset</button>\n"
        "  <span class=\"filter-count\" id=\"filter-count\"></span>\n"
        "</div>\n\n"

        "<div class=\"main\">\n\n"

        "<div class=\"panel active\" id=\"panel-overview\">\n"
        "  <div class=\"kpi-grid\" id=\"kpi-grid\"></div>\n"
        "  <div class=\"section-title\">Monthly Spend Heatmap</div>\n"
        "  <div class=\"chart-card\" style=\"margin-bottom:24px;\">\n"
        "    <div class=\"chart-title\">Spend Intensity by Month &amp; Year</div>\n"
        "    <div class=\"chart-sub\">Hover cells for amount &middot; deeper colour = higher spend</div>\n"
        "    <div id=\"heatmap-container\" style=\"margin-top:16px;\"></div>\n"
        "  </div>\n"
        "  <div class=\"chart-row cols-2\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Annual Spend Trend</div><div class=\"chart-sub\">Total debit spend by calendar year</div><canvas id=\"yoyChart\" height=\"200\"></canvas></div>\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Category Breakdown</div><div class=\"chart-sub\">Share of total spend</div><canvas id=\"catPie\" height=\"200\"></canvas></div>\n"
        "  </div>\n"
        "  <div class=\"chart-row cols-2\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Top 10 Categories by Spend</div><div class=\"chart-sub\">All-time totals</div><div id=\"cat-bars\"></div></div>\n"
        "    <div class=\"chart-card\">\n"
        "      <div class=\"chart-title\">Spend by Card</div><div class=\"chart-sub\">Split across all cards</div>\n"
        "      <canvas id=\"cardSplitChart\" height=\"160\"></canvas>\n"
        "      <div style=\"margin-top:20px;border-top:1px solid var(--border);padding-top:16px;\">\n"
        "        <div class=\"chart-title\" style=\"font-size:12px;\">By Cardholder</div>\n"
        "        <div class=\"chart-sub\" style=\"margin-bottom:12px;\">Primary vs Add-on</div>\n"
        "        <canvas id=\"holderChart\" height=\"130\"></canvas>\n"
        "      </div>\n"
        "    </div>\n"
        "  </div>\n"
        "</div>\n\n"

        "<div class=\"panel\" id=\"panel-yoy\">\n"
        "  <div class=\"section-title\">Year on Year Comparison</div>\n"
        "  <div class=\"chart-card\" style=\"margin-bottom:24px;\"><div class=\"chart-title\">Annual Spend &amp; Reward Points</div><div class=\"chart-sub\">Bars = spend &middot; Line = points</div><canvas id=\"yoyBarChart\" height=\"110\"></canvas></div>\n"
        "  <div class=\"chart-row cols-2\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Category Mix by Year</div><div class=\"chart-sub\">Stacked spend &mdash; top 10 categories</div><canvas id=\"yoyCatStack\" height=\"220\"></canvas></div>\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Annual Summary</div><div class=\"chart-sub\">Spend, transactions, points &amp; rate</div><table class=\"data-table\" id=\"yoy-table\"></table></div>\n"
        "  </div>\n"
        "</div>\n\n"

        "<div class=\"panel\" id=\"panel-mom\">\n"
        "  <div class=\"section-title\">Month on Month Trend</div>\n"
        "  <div class=\"chart-card\" style=\"margin-bottom:24px;\"><div class=\"chart-title\">Monthly Spend Timeline</div><div class=\"chart-sub\">All months &middot; use Year filter to zoom in</div><canvas id=\"momLineChart\" height=\"110\"></canvas></div>\n"
        "  <div class=\"chart-row cols-2\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Seasonal Spending Pattern</div><div class=\"chart-sub\">Average spend per calendar month</div><canvas id=\"seasonalChart\" height=\"220\"></canvas></div>\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Top 10 Months Ever</div><div class=\"chart-sub\">Highest single-month spend</div><table class=\"data-table\" id=\"top-months-table\"></table></div>\n"
        "  </div>\n"
        "  <div class=\"chart-card\" style=\"margin-bottom:24px;\"><div class=\"chart-title\">Category Mix by Month</div><div class=\"chart-sub\">Stacked spend &mdash; top 10 categories &middot; use Year filter to zoom in</div><canvas id=\"momCatStack\" height=\"130\"></canvas></div>\n"
        "</div>\n\n"

        "<div class=\"panel\" id=\"panel-categories\">\n"
        "  <div class=\"section-title\">Category &amp; Subcategory Breakdown</div>\n"
        "  <div class=\"chart-row cols-2\" style=\"margin-bottom:24px;\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Spend by Category</div><div class=\"chart-sub\">Sorted by total spend</div><div id=\"all-cat-bars\"></div></div>\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Category Trends by Year</div><div class=\"chart-sub\">Top 6 categories over time</div><canvas id=\"catTrendChart\" height=\"250\"></canvas></div>\n"
        "  </div>\n"
        "  <div class=\"section-title\">Subcategory Detail</div>\n"
        "  <div class=\"chart-card\"><div class=\"chart-title\">All Subcategories</div><div class=\"chart-sub\">Use Category filter to drill in</div>\n"
        "    <div class=\"detail-wrap\" style=\"margin-top:16px;\"><table class=\"data-table\" id=\"subcat-table\"></table></div>\n"
        "  </div>\n"
        "</div>\n\n"

        "<div class=\"panel\" id=\"panel-points\">\n"
        "  <div class=\"section-title\">Reward Points Analysis</div>\n"
        "  <div class=\"kpi-grid\" id=\"pts-kpi-grid\"></div>\n"
        "  <div class=\"chart-row cols-2\" style=\"margin-bottom:24px;\">\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Points Earned by Year</div><div class=\"chart-sub\">Cumulative reward points per year</div><canvas id=\"ptsYoyChart\" height=\"200\"></canvas></div>\n"
        "    <div class=\"chart-card\"><div class=\"chart-title\">Reward Rate by Category</div><div class=\"chart-sub\">Points per &#8377;100 spent</div><canvas id=\"ptsRateChart\" height=\"200\"></canvas></div>\n"
        "  </div>\n"
        "  <div class=\"chart-row cols-2\">\n"
        "    <div>\n"
        "      <div class=\"section-title\">&#127942; Best Point Returns <span style=\"font-size:10px;font-weight:400;color:var(--text3);text-transform:none;letter-spacing:0\">pts/&#8377;100 &darr; then spend &darr;</span></div>\n"
        "      <div class=\"rate-grid\" id=\"best-rates\"></div>\n"
        "    </div>\n"
        "    <div>\n"
        "      <div class=\"section-title\">&#128201; Worst Point Returns <span style=\"font-size:10px;font-weight:400;color:var(--text3);text-transform:none;letter-spacing:0\">incl. zero-earn &middot; pts/&#8377;100 &uarr; then spend &darr;</span></div>\n"
        "      <div class=\"rate-grid\" id=\"worst-rates\"></div>\n"
        "    </div>\n"
        "  </div>\n"
        "</div>\n\n"

        "<div class=\"panel\" id=\"panel-detail\">\n"
        "  <div class=\"section-title\">Transaction Detail</div>\n"
        "  <div class=\"chart-card\">\n"
        "    <div class=\"chart-title\" id=\"detail-title\">All Transactions</div>\n"
        "    <div class=\"chart-sub\" id=\"detail-sub\">Most recent 500 &middot; use filters to narrow</div>\n"
        "    <div class=\"detail-wrap\" style=\"margin-top:16px;\">\n"
        "      <table class=\"data-table\">\n"
        "        <thead><tr><th>Date</th><th>Description</th><th>Card</th><th>Category</th><th>Subcategory</th><th style=\"text-align:right\">Amount</th><th style=\"text-align:right\">Points</th><th style=\"text-align:right\">Rate</th></tr></thead>\n"
        "        <tbody id=\"detail-tbody\"></tbody>\n"
        "      </table>\n"
        "    </div>\n"
        "  </div>\n"
        "</div>\n\n"

        "</div>\n\n"

        "<div class=\"footer\">\n"
        "  <div class=\"logo\">Cred<span>Insights</span></div>\n"
        f"  <span>{card_name}</span>\n"
        f"  <span>Generated {today_str} &middot; {date_range}</span>\n"
        "</div>\n\n"

        "<script>" + js + "</script>\n"
        "</body>\n"
        "</html>\n"
    )
    return html


def regenerate_report(ledger_path: str, config: dict, output_path: str) -> str:
    logger.info(f"Regenerating report from {ledger_path}")
    _, precomputed = load_report_data(ledger_path)
    today_str = date.today().strftime("%d %b %Y")
    html = build_report_html(precomputed, config, today_str)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Report written: {output_path}  ({len(html):,} chars)")
    return output_path
