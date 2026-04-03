"""
CAISO LMP Server + Dashboard (RTM + HASP)
==========================================
Serves RTM 5-min and HASP 15-min dashboards on one page.
Deploy to Render.com.

Requirements: requests, flask, gunicorn
"""

import io
import re
import time
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify

OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"
NODE      = "ELAP_PACE-APND"
VERSION   = "1"
TZ_PT     = ZoneInfo("America/Los_Angeles")
TZ_UTC    = ZoneInfo("UTC")

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def fetch_hour(hr, market, query):
    now_pt   = datetime.now(tz=TZ_PT)
    today_pt = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    start_pt  = today_pt + timedelta(hours=hr)
    end_pt    = start_pt + timedelta(hours=1)
    start_utc = start_pt.astimezone(TZ_UTC)
    end_utc   = end_pt.astimezone(TZ_UTC)

    params = {
        "queryname":     query,
        "market_run_id": market,
        "grp_type":      "ALL_APNODES",
        "node":          NODE,
        "startdatetime": start_utc.strftime("%Y%m%dT%H:%M-0000"),
        "enddatetime":   end_utc.strftime("%Y%m%dT%H:%M-0000"),
        "version":       VERSION,
        "resultformat":  "6",
    }

    resp = requests.get(OASIS_URL, params=params, timeout=60)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for name in zf.namelist():
            with zf.open(name) as f:
                raw = f.read()
            if raw.strip().startswith(b"<"):
                text = raw.decode("utf-8", errors="replace")
                err  = re.search(r"<m:ERR_DESC>(.*?)</m:ERR_DESC>", text)
                raise ValueError(err.group(1) if err else "CAISO XML error")
            lines = raw.decode("utf-8").strip().split("\n")
            hdr   = [h.strip().strip('"') for h in lines[0].split(",")]
            rows  = []
            for line in lines[1:]:
                vals = line.split(",")
                obj  = {hdr[i]: vals[i].strip().strip('"') for i in range(len(hdr))}
                if obj.get("NODE") == NODE and obj.get("LMP_TYPE") == "LMP":
                    rows.append(obj)
            return rows
    return []


def fetch_all(market, query):
    current_hr = datetime.now(tz=TZ_PT).hour
    all_rows   = []
    for hr in range(current_hr):
        try:
            rows = fetch_hour(hr, market, query)
            all_rows.extend(rows)
            print(f"  [{market}] Hour {hr:02d}: {len(rows)} rows")
        except Exception as e:
            print(f"  [{market}] Hour {hr:02d}: SKIPPED ({e})")
        time.sleep(10)
    return all_rows


@app.route("/today/rtm")
def today_rtm():
    return jsonify(fetch_all("RTM", "PRC_INTVL_LMP"))


@app.route("/today/hasp")
def today_hasp():
    return jsonify(fetch_all("HASP", "PRC_HASP_LMP"))


@app.route("/")
def dashboard():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CAISO LMP Dashboard – ELAP_PACE-APND</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; background: #f0f4f8; color: #222; }
  .section-header {
    background: #1F4E79; color: #fff; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 24px;
  }
  .section-header:first-of-type { margin-top: 0; }
  .section-header h1 { font-size: 18px; }
  .section-header .meta { font-size: 12px; opacity: .75; text-align: right; }
  .cards { display: flex; gap: 16px; padding: 20px 24px 0; flex-wrap: wrap; }
  .card { background: #fff; border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 140px; box-shadow: 0 1px 4px rgba(0,0,0,.1); }
  .card .label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: .5px; }
  .card .value { font-size: 26px; font-weight: bold; margin-top: 4px; }
  .card .value.pos { color: #1a6b2f; }
  .card .value.neg { color: #b91c1c; }
  .chart-wrap { padding: 20px 24px 0; }
  .chart-wrap h2 { font-size: 13px; color: #444; margin-bottom: 8px; }
  canvas { background: #fff; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.1); width: 100% !important; }
  .table-wrap { padding: 20px 24px 24px; overflow-x: auto; }
  .table-wrap h2 { font-size: 13px; color: #444; margin-bottom: 8px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.1); font-size: 13px; }
  thead tr { background: #1F4E79; color: #fff; }
  th, td { padding: 8px 14px; text-align: center; border-bottom: 1px solid #e5e7eb; }
  tbody tr:nth-child(even) { background: #D6E4F0; }
  tbody tr:hover { background: #bfd5ec; }
  td.neg { color: #b91c1c; font-weight: bold; }
  td.pos { color: #1a6b2f; }
  .status { text-align: center; padding: 40px; color: #666; font-size: 14px; }
  .spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid #ccc; border-top-color: #1F4E79; border-radius: 50%; animation: spin .8s linear infinite; margin-right: 8px; vertical-align: middle; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .divider { height: 4px; background: #1F4E79; opacity: 0.2; margin-top: 24px; }
</style>
</head>
<body>

<!-- RTM Section -->
<div class="section-header">
  <div>
    <h1>Real-Time Market (RTM) 5-Min LMP &nbsp;|&nbsp; ELAP_PACE-APND</h1>
    <div class="meta" id="rtmRefreshed">Loading…</div>
  </div>
  <div style="text-align:right">
    <button onclick="loadMarket('rtm')" style="background:#fff;color:#1F4E79;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-weight:bold;font-size:13px;">⟳ Refresh</button>
  </div>
</div>
<div class="cards">
  <div class="card"><div class="label">Latest LMP</div><div class="value" id="rtm-cLatest">—</div></div>
  <div class="card"><div class="label">Today's High</div><div class="value pos" id="rtm-cHigh">—</div></div>
  <div class="card"><div class="label">Today's Low</div><div class="value neg" id="rtm-cLow">—</div></div>
  <div class="card"><div class="label">Today's Avg</div><div class="value" id="rtm-cAvg">—</div></div>
  <div class="card"><div class="label">Hours Fetched</div><div class="value" id="rtm-cHours">—</div></div>
</div>
<div class="chart-wrap">
  <h2>5-Minute LMP ($/MWh) — Today So Far</h2>
  <canvas id="rtm-chart" height="220"></canvas>
</div>
<div class="table-wrap">
  <h2>Hourly Average LMP ($/MWh)</h2>
  <div id="rtm-table"><div class="status"><span class="spinner"></span> Fetching data…</div></div>
</div>

<div class="divider"></div>

<!-- HASP Section -->
<div class="section-header">
  <div>
    <h1>Hour-Ahead Scheduling Process (HASP) 15-Min LMP &nbsp;|&nbsp; ELAP_PACE-APND</h1>
    <div class="meta" id="haspRefreshed">Loading…</div>
  </div>
  <div style="text-align:right">
    <button onclick="loadMarket('hasp')" style="background:#fff;color:#1F4E79;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-weight:bold;font-size:13px;">⟳ Refresh</button>
  </div>
</div>
<div class="cards">
  <div class="card"><div class="label">Latest LMP</div><div class="value" id="hasp-cLatest">—</div></div>
  <div class="card"><div class="label">Today's High</div><div class="value pos" id="hasp-cHigh">—</div></div>
  <div class="card"><div class="label">Today's Low</div><div class="value neg" id="hasp-cLow">—</div></div>
  <div class="card"><div class="label">Today's Avg</div><div class="value" id="hasp-cAvg">—</div></div>
  <div class="card"><div class="label">Hours Fetched</div><div class="value" id="hasp-cHours">—</div></div>
</div>
<div class="chart-wrap">
  <h2>15-Minute LMP ($/MWh) — Today So Far</h2>
  <canvas id="hasp-chart" height="220"></canvas>
</div>
<div class="table-wrap">
  <h2>Hourly Average LMP ($/MWh)</h2>
  <div id="hasp-table"><div class="status"><span class="spinner"></span> Fetching data…</div></div>
</div>

<script>
let charts = {};

function nowPT() {
  return new Date(new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" }));
}

async function ensureChart() {
  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }
}

async function loadMarket(market) {
  document.getElementById(market + "-table").innerHTML =
    '<div class="status"><span class="spinner"></span> Fetching data…</div>';
  document.getElementById(market + "Refreshed").textContent = "Refreshing…";

  let allRows = [];
  try {
    const resp = await fetch("/today/" + market);
    if (!resp.ok) throw new Error("Server error: " + resp.status);
    allRows = await resp.json();
  } catch(e) {
    document.getElementById(market + "-table").innerHTML =
      '<div class="status">⚠️ Could not load data: ' + e.message + '</div>';
    return;
  }

  if (!allRows.length) {
    document.getElementById(market + "-table").innerHTML =
      '<div class="status">No data available yet for today.</div>';
    return;
  }

  const rows = allRows.map(r => ({
    time: r["INTERVALSTARTTIME_GMT"], hr: parseFloat(r["OPR_HR"]), lmp: parseFloat(r["MW"]),
    timePT: new Date(r["INTERVALSTARTTIME_GMT"]).toLocaleTimeString("en-US",
      {hour:"2-digit", minute:"2-digit", timeZone:"America/Los_Angeles", hour12:false})
  })).sort((a,b) => a.time < b.time ? -1 : 1);

  const lmps = rows.map(r => r.lmp);
  const colorVal = (id, v) => {
    const el = document.getElementById(id);
    el.textContent = "$" + v.toFixed(2);
    el.className = "value " + (v >= 0 ? "pos" : "neg");
  };
  colorVal(market + "-cLatest", lmps[lmps.length-1]);
  colorVal(market + "-cHigh",   Math.max(...lmps));
  colorVal(market + "-cLow",    Math.min(...lmps));
  document.getElementById(market + "-cAvg").textContent = "$" + (lmps.reduce((a,b)=>a+b,0)/lmps.length).toFixed(2);
  document.getElementById(market + "-cHours").textContent = new Set(rows.map(r=>r.hr)).size;

  await ensureChart();
  if (charts[market]) charts[market].destroy();
  const colors = lmps.map(v => v >= 0 ? "rgba(26,107,47,0.8)" : "rgba(185,28,28,0.8)");
  charts[market] = new Chart(document.getElementById(market + "-chart").getContext("2d"), {
    type: "bar",
    data: { labels: rows.map(r=>r.timePT), datasets: [{ label: "LMP ($/MWh)", data: lmps, backgroundColor: colors, borderWidth: 0 }] },
    options: {
      responsive: true,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: c => " $" + c.parsed.y.toFixed(4) + "/MWh" } } },
      scales: {
        x: { ticks: { maxTicksLimit: 12, font: { size: 10 } } },
        y: { ticks: { callback: v => "$" + v }, grid: { color: "#e5e7eb" } }
      }
    }
  });

  const byHr = {};
  rows.forEach(r => { if (!byHr[r.hr]) byHr[r.hr]=[]; byHr[r.hr].push(r.lmp); });
  let tbl = '<table><thead><tr><th>Oper Hour</th><th>Avg LMP ($/MWh)</th><th>Min</th><th>Max</th></tr></thead><tbody>';
  Object.keys(byHr).sort((a,b)=>+a-+b).forEach(h => {
    const vals = byHr[h];
    const avg  = vals.reduce((a,b)=>a+b,0)/vals.length;
    const min  = Math.min(...vals), max = Math.max(...vals);
    tbl += '<tr><td>'+h+'</td><td class="'+(avg<0?"neg":"pos")+'">'+avg.toFixed(4)+
           '</td><td class="'+(min<0?"neg":"")+'">'+min.toFixed(4)+
           '</td><td class="'+(max<0?"neg":"pos")+'">'+max.toFixed(4)+'</td></tr>';
  });
  tbl += '</tbody></table>';
  document.getElementById(market + "-table").innerHTML = tbl;
  document.getElementById(market + "Refreshed").textContent =
    "Last refreshed: " + nowPT().toLocaleTimeString("en-US",{timeZone:"America/Los_Angeles"}) + " PT";
}

function scheduleNext() {
  const now  = nowPT();
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours()+1, 0, 0);
  setTimeout(async () => { await loadAll(); scheduleNext(); }, next - now);
}

async function loadAll() {
  await loadMarket('rtm');
  await loadMarket('hasp');
}

loadAll();
scheduleNext();
</script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
