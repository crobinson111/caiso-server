"""
CAISO Local API Server (Render-ready)
==============================================
Runs a small web server that fetches CAISO data and serves it
to the dashboard HTML file. Can be deployed to Render.com for free.

Requirements:
    pip install requests flask

Usage (local):
    python caiso_server.py
Usage (Render):
    Deploy this file to Render.com as a web service.
"""

import io
import re
import json
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
        time.sleep(5)

    resp = jsonify(all_rows)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@app.route("/")
def index():
    return "CAISO LMP Server is running."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8765)
