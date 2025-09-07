#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import io
import re
from datetime import date, timedelta
from urllib.parse import urljoin

import pandas as pd
import requests
from openpyxl import load_workbook
from bs4 import BeautifulSoup

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Event color IDs supported by Google Calendar (1–11)
DEFAULT_COLOR_ID = "8"  # gray

# Regex for parsing dates
CROSS_MONTH = re.compile(r"(\d{1,2})\.?\s*-\s*(\d{1,2})\.(\d{1,2})")
RANGE_SAME  = re.compile(r"(\d{1,2})\.?\s*-\s*(\d{1,2})\.?\s*(\d{1,2})")
SINGLE      = re.compile(r"(\d{1,2})\.?\s*(\d{1,2})\.?")
RANGE_NO_MONTH = re.compile(r"^\s*(\d{1,2})\.?\s*-\s*(\d{1,2})\.?\s*$")

CZECH_MONTHS = {
    "leden": 1, "únor": 2, "březen": 3, "duben": 4,
    "květen": 5, "červen": 6, "červenec": 7, "srpen": 8,
    "září": 9, "říjen": 10, "listopad": 11, "prosinec": 12
}

def fetch_xls_url(page_url: str) -> str:
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith((".xls",".xlsx")) and "terminova_listina" in href.lower():
            return urljoin(page_url, href)
    raise RuntimeError("No Excel (.xls/.xlsx) link found on the page.")

def parse_date(cell: str, year: int, current_month: int = None):
    s = str(cell).strip()
    if not s or s.lower().startswith(tuple(CZECH_MONTHS.keys())):
        return None, None

    m = CROSS_MONTH.match(s)
    if m:
        d1, d2, m2 = map(int, m.groups())
        return date(year, m2, d1), date(year, m2, d2)

    m = RANGE_SAME.match(s)
    if m:
        d1, d2, mth = map(int, m.groups())
        return date(year, mth, d1), date(year, mth, d2)

    m = SINGLE.match(s)
    if m:
        d, mth = map(int, m.groups())
        return date(year, mth, d), date(year, mth, d)

    m = RANGE_NO_MONTH.match(s)
    if m and current_month:
        d1, d2 = map(int, m.groups())
        return date(year, current_month, d1), date(year, current_month, d2)

    return None, None

def get_row_colors(xls_bytes):
    with io.BytesIO(xls_bytes) as fh:
        wb = load_workbook(fh, data_only=True)
    ws = wb.active

    row_inter = {}
    for i, row in enumerate(ws.iter_rows(min_row=3), start=0):
        fcell = row[2]
        if fcell.fill.fgColor.rgb == "FFFFFF00":
            row_inter[i-1] = "skip"
            continue
        italic_found = any(cell.font.i for cell in row[:4])
        row_inter[i-1] = "true" if italic_found else "false"
    return row_inter

def xls_to_events(xls_bytes, year, inter_filter="all", months_filter=None):
    with io.BytesIO(xls_bytes) as fh:
        df = pd.read_excel(fh, header=2)

    row_inters = get_row_colors(xls_bytes)
    events = []
    invalid = []
    current_month = None

    for idx, r in df.iterrows():
        raw_date = str(r.get("datum", "")).strip()
        if raw_date.lower() in CZECH_MONTHS:
            current_month = CZECH_MONTHS[raw_date.lower()]

        row_inter = row_inters.get(idx, "false")
        if inter_filter != "all" and row_inter != inter_filter:
            continue
        if row_inter == "skip":
            continue

        start, end = parse_date(raw_date, year, current_month)
        if not start:
            if raw_date.lower() not in CZECH_MONTHS:
                invalid.append({
                    **r.to_dict(),
                    "row_index": idx,
                    "reason": f"unrecognized date format: {raw_date}",
                    "color": row_inter
                })
            continue

        if months_filter and start.month not in months_filter:
            continue

        ev = {
            "summary": str(r.get("název akce", "")).strip(),
            "description": str(r.get("pořadatel", "")).strip(),
            "location": str(r.get("místo", "")).strip(),
            "start_date": start,
            "end_date": end,
        }
        events.append(ev)

    print(f"Parsed {len(events)} events (color={inter_filter}, months={months_filter or 'all'}).")
    print(f"Skipped {len(invalid)} rows.")
    if invalid:
        print("Examples of skipped rows:")
        for bad in invalid[:5]:
            print(f"Row {bad['row_index']} | {bad.get('datum')} | reason: {bad['reason']}")
    return events

def insert_events(service, calendar_id, events, color_id=DEFAULT_COLOR_ID):
    for ev in events:
        body = {
            "summary": ev["summary"],
            "description": ev["description"],
            "location": ev["location"],
            "start": {"date": ev["start_date"].isoformat()},
            "end": {"date": (ev["end_date"] + timedelta(days=1)).isoformat()},
            "colorId": str(color_id),
        }
        created = service.events().insert(calendarId=calendar_id, body=body).execute()
        print(f"Inserted: {created.get('summary')} ({created.get('id')})")

def main():
    current_date = date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True, help="URL of veslo.cz termínovky page")
    ap.add_argument("--year", type=int, default=current_date.year)
    ap.add_argument("--months", nargs="*", type=int)
    ap.add_argument("--inter", choices=["all", "true", "false"], default="all")
    ap.add_argument("--calendar", default="primary", help="Target Google Calendar ID")
    ap.add_argument("--creds", required=True, help="Path to service account JSON credentials")
    args = ap.parse_args()

    print("Looking for Excel file...")
    xls_url = fetch_xls_url(args.page)
    print(f"Found: {xls_url}")

    print("Downloading Excel...")
    xls_bytes = requests.get(xls_url).content

    print("Parsing events...")
    events = xls_to_events(xls_bytes, args.year, args.inter, args.months)

    print("Connecting to Google Calendar API...")
    creds = service_account.Credentials.from_service_account_file(
        args.creds,
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    service = build("calendar", "v3", credentials=creds)

    print(f"Inserting {len(events)} events into calendar {args.calendar}...")
    insert_events(service, args.calendar, events)

if __name__ == "__main__":
    main()