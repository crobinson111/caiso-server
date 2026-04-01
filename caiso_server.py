"""
CAISO LMP Server + Dashboard
=============================
Serves both the dashboard HTML and the CAISO data API.
Deploy to Render.com - no local files needed.

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
MARKET    = "RTM"
QUERY     = "PRC_INTVL_LMP"
VERSION   = "1"
TZ_PT     = ZoneInfo("America/Los_Angeles")
TZ_UTC    = ZoneInfo("UTC")

app = Flask(__name__)

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


def fetch_hour(hr: int) -> list:
    now_pt    = datetime.now(tz=TZ_PT)
    today_pt  = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    start_pt  = today_pt + timedelta(hours=hr)
    end_pt    = start_pt + timedelta(hours=1)
    start_utc = start_pt.astimezone(TZ_UTC)
    end_utc   = end_pt.astimezone(TZ_UTC)

    params = {
        "queryname":     QUERY,
        "market_run_id": MARKET,
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


@app.route("/today")
def today():
    current_hr = datetime.now(tz=TZ_PT).hour
    all_rows   = []

    for hr in range(current_hr):
        try:
            rows = fetch_hour(hr)
            all_rows.extend(rows)
            print(f"  Hour {hr:02d}: {len(rows)} rows")
        except Exception as e:
            print(f"  Hour {hr:02d}: SKIPPED ({e})")
        time.sleep(10)

    return jsonify(all_rows)


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
  header {
    background: #1F4E79; color: #fff; padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 18px; }
  header .meta { font-size: 12px; opacity: .75; text-align: right; }
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
  #countdown { font-size: 12px; opacity: .75; }
</style>
</head>
<body>
<header>
  <div>
    <h1>CAISO Real-Time LMP &nbsp;|&nbsp; ELAP_PACE-APND</h1>
    <div class="meta" id="lastRefreshed">Loading…</div>
  </div>
  <div style="text-align:right">
    <button onclick="refresh()" style="background:#fff;color:#1F4E79;border:none;padding:7px 14px;border-radius:6px;cursor:pointer;font-weight:bold;font-size:13px;">⟳ Refresh Now</button>
    <div id="countdown" style="margin-top:4px;"></div>
  </div>
</header>
<div class="cards">
  <div class="card"><div class="label">Latest LMP</div><div class="value" id="cLatest">—</div></div>
  <div class="card"><div class="label">Today's High</div><div class="value pos" id="cHigh">—</div></div>
  <div class="card"><div class="label">Today's Low</div><div class="value neg" id="cLow">—</div></div>
  <div class="card"><div class="label">Today's Avg</div><div class="value" id="cAvg">—</div></div>
  <div class="card"><div class="label">Hours Fetched</div><div class="value" id="cHours">—</div></div>
</div>
<div class="chart-wrap">
  <h2>5-Minute LMP ($/MWh) — Today So Far</h2>
  <canvas id="chart" height="220"></canvas>
</div>
<div class="table-wrap">
  <h2>Hourly Average LMP ($/MWh)</h2>
  <div id="tableContainer"><div class="status"><span class="spinner"></span> Fetching data…</div></div>
</div>
<script>
let chartInst = null;
let countdownTimer = null;
let nextRefreshAt = null;

function nowPT() {
  return new Date(new Date().toLocaleString("en-US", { timeZone: "America/Los_Angeles" }));
}

async function refresh() {
  document.getElementById("tableContainer").innerHTML =
    '<div class="status"><span class="spinner"></span> Fetching data…</div>';
  document.getElementById("lastRefreshed").textContent = "Refreshing…";

  let allRows = [];
  try {
    const resp = await fetch("/today");
    if (!resp.ok) throw new Error("Server error: " + resp.status);
    allRows = await resp.json();
  } catch(e) {
    document.getElementById("tableContainer").innerHTML =
      '<div class="status">⚠️ Could not load data: ' + e.message + '</div>';
    return;
  }

  if (!allRows.length) {
    document.getElementById("tableContainer").innerHTML =
      '<div class="status">No data available yet for today.</div>';
    return;
  }

  const rows = allRows.map(r => ({
    time: r["INTERVALSTARTTIME_GMT"],
    hr: parseFloat(r["OPR_HR"]),
    lmp: parseFloat(r["MW"]),
    timePT: (() => {
      const d = new Date(r["INTERVALSTARTTIME_GMT"]);
      return d.toLocaleTimeString("en-US", {hour:"2-digit", minute:"2-digit", timeZone:"America/Los_Angeles", hour12:false});
    })()
  })).sort((a,b) => a.time < b.time ? -1 : 1);

  const lmps   = rows.map(r => r.lmp);
  const latest = lmps[lmps.length - 1];
  const high   = Math.max(...lmps);
  const low    = Math.min(...lmps);
  const avg    = lmps.reduce((a,b) => a+b, 0) / lmps.length;

  const colorVal = (id, v) => {
    const el = document.getElementById(id);
    el.textContent = "$" + v.toFixed(2);
    el.className = "value " + (v >= 0 ? "pos" : "neg");
  };
  colorVal("cLatest", latest);
  colorVal("cHigh",   high);
  colorVal("cLow",    low);
  document.getElementById("cAvg").textContent   = "$" + avg.toFixed(2);
  document.getElementById("cHours").textContent = new Set(rows.map(r => r.hr)).size;

  if (chartInst) chartInst.destroy();
  const ctx    = document.getElementById("chart").getContext("2d");
  const colors = lmps.map(v => v >= 0 ? "rgba(26,107,47,0.8)" : "rgba(185,28,28,0.8)");

  if (!window.Chart) {
    await new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
      s.onload = res; s.onerror = rej;
      document.head.appendChild(s);
    });
  }

  chartInst = new Chart(ctx, {
    type: "bar",
    data: {
      labels: rows.map(r => r.timePT),
      datasets: [{ label: "LMP ($/MWh)", data: lmps, backgroundColor: colors, borderWidth: 0 }]
    },
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
  rows.forEach(r => {
    if (!byHr[r.hr]) byHr[r.hr] = [];
    byHr[r.hr].push(r.lmp);
  });
  const hrAvgs = Object.keys(byHr).sort((a,b) => +a - +b).map(h => ({
    hr: +h,
    avg: byHr[h].reduce((a,b) => a+b, 0) / byHr[h].length,
    min: Math.min(...byHr[h]),
    max: Math.max(...byHr[h]),
  }));

  let tbl = '<table><thead><tr><th>Oper Hour</th><th>Avg LMP ($/MWh)</th><th>Min</th><th>Max</th></tr></thead><tbody>';
  hrAvgs.forEach(r => {
    tbl += '<tr><td>' + r.hr + '</td><td class="' + (r.avg < 0 ? "neg" : "pos") + '">' + r.avg.toFixed(4) +
           '</td><td class="' + (r.min < 0 ? "neg" : "") + '">' + r.min.toFixed(4) +
           '</td><td class="' + (r.max < 0 ? "neg" : "pos") + '">' + r.max.toFixed(4) + '</td></tr>';
  });
  tbl += '</tbody></table>';
  document.getElementById("tableContainer").innerHTML = tbl;

  const now = nowPT();
  document.getElementById("lastRefreshed").textContent =
    "Last refreshed: " + now.toLocaleTimeString("en-US", {timeZone:"America/Los_Angeles"}) + " PT";

  scheduleNext();
}

function scheduleNext() {
  if (countdownTimer) clearInterval(countdownTimer);
  const now  = nowPT();
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours()+1, 0, 0);
  nextRefreshAt = next;
  setTimeout(refresh, next - now);

  countdownTimer = setInterval(() => {
    const diff = Math.max(0, nextRefreshAt - nowPT());
    const m = Math.floor(diff / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    document.getElementById("countdown").textContent =
      "Next refresh in " + m + "m " + String(s).padStart(2,"0") + "s";
  }, 1000);
}

refresh();
</script>
</body>
</html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
