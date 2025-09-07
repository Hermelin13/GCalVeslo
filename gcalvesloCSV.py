#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import io
import re
from datetime import date
from urllib.parse import urljoin

import pandas as pd
import requests
from openpyxl.styles.colors import Color
from bs4 import BeautifulSoup
from openpyxl import load_workbook

GCAL_FIELDS = [
    "Subject","Start Date","Start Time","End Date","End Time",
    "All Day Event","Description","Location"
]

# Cross month or explicit month in both days: "29.5-1.6." or "10. - 11.5."
CROSS_MONTH = re.compile(r"(\d{1,2})\.?\s*-\s*(\d{1,2})\.(\d{1,2})")

# Same month ranges: "25.-26.1." or "13.-15. 6"
RANGE_SAME  = re.compile(r"(\d{1,2})\.?\s*-\s*(\d{1,2})\.?\s*(\d{1,2})")

# Single date: "11.1." or "6. 9."
SINGLE      = re.compile(r"(\d{1,2})\.?\s*(\d{1,2})\.?")

# Range without month: "1.-3." or "1 - 3"
RANGE_NO_MONTH = re.compile(r"^\s*(\d{1,2})\.?\s*-\s*(\d{1,2})\.?\s*$")

CZECH_MONTHS = {
    "leden": 1, "únor": 2, "březen": 3, "duben": 4,
    "květen": 5, "červen": 6, "červenec": 7, "srpen": 8,
    "září": 9, "říjen": 10, "listopad": 11, "prosinec": 12
}

BLUE_HEXES = {
    "FF0000FF",  # pure blue
    "FF00B0F0",  # azure / azurová
    "FF1F497D",  # darker accent blue
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
    if not s or s.lower().startswith((
        "leden","únor","březen","duben","květen","červen",
        "červenec","srpen","září","říjen","listopad","prosinec"
    )):
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
        # Skip the row if any of the first 4 columns is yellow 
        fcell = row[2]
        if fcell.fill.fgColor.rgb == "FFFFFF00": 
            row_inter[i-1] = "skip"
            continue

        # Check if any of the first 4 columns is italic
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
        # Month headers update state and are skipped
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
            "Subject": str(r.get("název akce", "")).strip(),
            "Start Date": start.strftime("%m/%d/%Y"),
            "Start Time": "",
            "End Date": end.strftime("%m/%d/%Y"),
            "End Time": "",
            "All Day Event": "True",
            "Description": str(r.get("pořadatel", "")).strip(),
            "Location": str(r.get("místo", "")).strip(),
        }
        events.append(ev)

    print(f"Parsed {len(events)} events (color={inter_filter}, months={months_filter or 'all'}).")
    print(f"Skipped {len(invalid)} rows.")
    if invalid:
        print("Examples of skipped rows:")
        for bad in invalid:
            print(f"Row {bad['row_index']} | {bad.get('datum')} | reason: {bad['reason']}")
    return events

def write_csv(events, out_path):
    pd.DataFrame(events, columns=GCAL_FIELDS).to_csv(out_path, index=False, encoding="utf-8")

def main():
    current_date = date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", required=True, help="URL of veslo.cz termínovky page")
    ap.add_argument("--out", default="terminovka_gcal.csv")
    ap.add_argument("--year", type=int, default=current_date.year)
    ap.add_argument("--months", nargs="*", type=int, help="List of months to include (1=Jan ... 12=Dec)")
    ap.add_argument("--inter", choices=["all", "true", "false"], default="all", help="Filter events by text color (text styling in Excel)")
    args = ap.parse_args()

    print("Looking for Excel file...")
    xls_url = fetch_xls_url(args.page)
    print(f"Found: {xls_url}")

    print("Downloading Excel...")
    xls_bytes = requests.get(xls_url).content

    print("Parsing events...")
    events = xls_to_events(xls_bytes, args.year, args.inter, args.months)

    print(f"Writing {len(events)} events to {args.out}")
    write_csv(events, args.out)

if __name__ == "__main__":
    main()
