"""
CAISO Local API Server
======================
Runs a small local web server that fetches CAISO data and serves it
to the dashboard HTML file.

Usage:
    python caiso_server.py
Then open caiso_dashboard.html in your browser.
"""

import io
import re
import json
import time
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

OASIS_URL = "https://oasis.caiso.com/oasisapi/SingleZip"
NODE      = "ELAP_PACE-APND"
MARKET    = "RTM"
QUERY     = "PRC_INTVL_LMP"
VERSION   = "1"
TZ_PT     = ZoneInfo("America/Los_Angeles")
TZ_UTC    = ZoneInfo("UTC")
PORT      = 8765


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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default logging

    def do_GET(self):
        if self.path == "/today":
            self.handle_today()
        else:
            self.send_response(404)
            self.end_headers()

    def handle_today(self):
        current_hr = datetime.now(tz=TZ_PT).hour
        all_rows   = []

        for hr in range(current_hr):
            try:
                rows = fetch_hour(hr)
                all_rows.extend(rows)
                print(f"  Hour {hr:02d}: {len(rows)} rows")
            except Exception as e:
                print(f"  Hour {hr:02d}: SKIPPED ({e})")
            time.sleep(5)  # pause to avoid rate limiting

        payload = json.dumps(all_rows).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type",  "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)


def main():
    print(f"CAISO Local Server running at http://localhost:{PORT}")
    print(f"Open caiso_dashboard.html in your browser.")
    print(f"Press Ctrl+C to stop.\n")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
