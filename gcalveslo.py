#!/usr/bin/env python3
"""Synchronize rowing events from ČVS workbooks into Google Calendar."""
import argparse
import base64
import io
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openpyxl import load_workbook

PAGE = 'https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1'
COLORS = {str(i): name for i, name in enumerate(['', 'Lavender', 'Sage', 'Grape', 'Flamingo', 'Banana', 'Tangerine', 'Peacock', 'Graphite', 'Blueberry', 'Basil', 'Tomato']) if i}
MONTHS = dict(zip(('leden únor březen duben květen červen červenec srpen září říjen listopad prosinec').split(), range(1,13)))
# Exclude world/European championship variants in every rowing discipline,
# plus Indoor and Coastal Rowing Championships even when the region is omitted.
# Keep domestic championships (e.g. Mistrovství ČR) and ordinary regattas.
EXCLUDED = re.compile(
    r"\b(?:"
    r"mistrovstv[ií]\s+(?:sv[eě]ta|evropy)"
    r"|(?:MS|ME)(?=\s|\b|[-–—])"
    r"|(?:WRICH|WRCH|ERICH|ERCH|WRBSCH|WRC)(?=\s|\b|[-–—])"
    r"|(?:para[ -]?rowing|paraveslov[aá]n[ií])\b"
    r"|sv[eě]tov[yý]\s+poh[aá]r"
    r"|(?:world|european)\s+cup"
    r"|(?:world|european)\s+(?:[\w-]+\s+){0,8}championships?\b"
    r"|(?:indoor|coastal(?:\s+rowing)?)\s+championships?\b"
    r"|(?:championships?\s+(?:of\s+the\s+)?(?:world|europe))\b"
    r"|(?:mistrovstv[ií]\s+(?:sv[eě]ta|evropy)\s+(?:v|ve)\s+[^,;]+)"
    r")",
    re.I,
)

LOG = logging.getLogger('gcalveslo')


def norm(s):
    return ' '.join(unicodedata.normalize('NFKC', str(s or '')).casefold().split())


def get(session, url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('Only HTTPS sources are allowed')
    for attempt in range(3):
        try:
            response = session.get(url, timeout=(10, 45))
            response.raise_for_status()
            if len(response.content) > 15_000_000:
                raise ValueError('Source too large')
            return response.content
        except (requests.RequestException,) as exc:
            if attempt == 2:
                raise RuntimeError(f'Download failed: {parsed.hostname}') from exc
            time.sleep(2 ** attempt)


def sources(session, page):
    soup = BeautifulSoup(get(session, page), 'html.parser')
    found = []
    for a in soup.find_all('a', href=True):
        href = urljoin(page, a['href'])
        path = urlparse(href).path.lower()
        label = a.get_text(' ', strip=True)
        if not path.endswith('.xlsx') and not path.endswith('.xls'):
            continue
        if 'term' not in norm(label) and 'termin' not in path:
            continue
        years = [int(y) for y in re.findall(r'20\d{2}', label + ' ' + path)]
        # Prefer explicit year-spanning sheets (e.g. 2026–2028), then latest files.
        priority = max(years, default=0)
        found.append((priority, href))
    return [url for _, url in sorted(set(found), reverse=True)]


def parse_day(value, year, month):
    if isinstance(value, (date, datetime)):
        d = value.date() if isinstance(value, datetime) else value
        return d, d
    s = str(value or '').strip().replace('–', '-').replace('—', '-')
    if not s or s.casefold() in MONTHS:
        return None
    m = re.fullmatch(r'(\d{1,2})\.\s*(\d{1,2})\.?(?:\s*-\s*(\d{1,2})\.\s*(\d{1,2})\.?)?', s)
    if m:
        d1, mon1, d2, mon2 = m.groups()
        return date(year, int(mon1), int(d1)), date(year, int(mon2), int(d2)) if d2 else date(year, int(mon1), int(d1))
    m = re.fullmatch(r'(\d{1,2})\.?\s*-\s*(\d{1,2})\.\s*(\d{1,2})\.?', s)
    if m:
        a,b,mo = map(int,m.groups())
        return date(year,mo,a),date(year,mo,b)
    m = re.fullmatch(r'(\d{1,2})\.?\s*-\s*(\d{1,2})\.?', s)
    if m and month:
        a,b = map(int,m.groups())
        return date(year,month,a),date(year,month,b)
    m = re.fullmatch(r'(\d{1,2})\.?\s*(\d{1,2})\.?',s)
    if m:
        a,mo = map(int,m.groups())
        return date(year,mo,a),date(year,mo,a)
    return None


def workbook_events(payload, desired_years, start_window, stop_window, source_url):
    wb = load_workbook(io.BytesIO(payload), read_only=False, data_only=True)
    result = []
    for ws in wb.worksheets:
        sheet_years = [int(y) for y in re.findall(r'20\d{2}', ws.title)]
        if len(sheet_years) == 2 and sheet_years[0] < sheet_years[1] and sheet_years[1] - sheet_years[0] <= 5:
            sheet_years = list(range(sheet_years[0], sheet_years[1]+1))
        # Single-year sheets must be identified; never apply an arbitrary year to an unknown sheet.
        if not sheet_years:
            continue
        if len(sheet_years) != 1:
            LOG.warning('Skipping ambiguous multi-year sheet: %s', ws.title)
            continue
        for year in desired_years:
            if year not in sheet_years:
                continue
            headers = None
            month = None
            for row in ws.iter_rows():
                values = [norm(cell.value) for cell in row]
                if 'datum' in values and ('nazev akce' in unaccent_list(values) or 'název akce' in values):
                    headers = {unaccent(v): i for i,v in enumerate(values)}
                    continue
                if not headers:
                    continue
                def cell(key):
                    i = headers.get(key)
                    return row[i] if i is not None and i < len(row) else None
                raw = cell('datum')
                if raw is None or raw.value is None:
                    continue
                raw_date = str(raw.value).strip()
                if norm(raw_date) in MONTHS:
                    month = MONTHS[norm(raw_date)]
                    continue
                # Historic Excel: yellow highlighted rows are administrative/non-race rows.
                flag_cell = row[2] if len(row) > 2 else raw
                fg = flag_cell.fill.fgColor if flag_cell.fill else None
                if fg and fg.type == 'rgb' and str(fg.rgb).upper().endswith('FFFF00'):
                    continue
                try:
                    parsed = parse_day(raw.value, year, month)
                except ValueError:
                    LOG.warning('Invalid date in sheet %s: %s', ws.title, raw_date)
                    continue
                if not parsed:
                    continue
                first,last = parsed
                if first > last or last < start_window or first >= stop_window:
                    continue
                title_cell = cell('nazev akce')
                name = str(title_cell.value or '').strip() if title_cell else ''
                if not name or name.casefold() == 'nan':
                    continue
                if EXCLUDED.search(name):
                    continue
                organizer = cell('poradatel')
                location = cell('misto')
                # Original ČVS workbooks distinguish foreign competitions by italic text.
                international = any(c.font and c.font.italic for c in row[:4])
                result.append(dict(summary=name, start=first, end=last+timedelta(days=1),
                                   description=str(organizer.value or '').strip() if organizer else '',
                                   location=str(location.value or '').strip() if location else '',
                                   international=international, source=source_url))
    return result


def unaccent(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def unaccent_list(items):
    return [unaccent(s) for s in items]


def load_events(session, page, today):
    end = today.replace(year=today.year+1) if not (today.month == 2 and today.day == 29) else today+timedelta(days=365)
    urls = sources(session, page)
    if not urls:
        raise RuntimeError('No term list spreadsheets found on the publisher page')
    events = {}
    successfully_read = 0
    for url in urls:
        if not urlparse(url).path.lower().endswith('.xlsx'):
            LOG.warning('Unsupported old Excel .xls source: %s', urlparse(url).path)
            continue
        try:
            items = workbook_events(get(session,url), {today.year,end.year},today,end,url)
            successfully_read += 1
        except Exception as exc:
            LOG.warning('Skipping unreadable workbook %s: %s',urlparse(url).path, type(exc).__name__)
            continue
        for ev in items:
            key = event_key(ev)
            events.setdefault(key, ev)
    if not successfully_read:
        raise RuntimeError('Could not parse any published term list. Calendar unchanged.')
    LOG.info('Read %d unique races from %d workbooks',len(events),successfully_read)
    return list(events.values()),end


def event_key(ev):
    # Same normalized title on the same starting calendar day is one race,
    # regardless of the reported end date or source workbook.
    return (norm(ev['summary']), str(ev['start']))


def credentials():
    value = os.environ.get('GOOGLE_CREDENTIALS_B64')
    if not value:
        raise RuntimeError('Set GOOGLE_CREDENTIALS_B64 to base64 encoded service account JSON')
    try:
        import json
        info = json.loads(base64.b64decode(value, validate=True))
        return service_account.Credentials.from_service_account_info(info, scopes=['https://www.googleapis.com/auth/calendar.events'])
    except Exception as exc:
        raise RuntimeError('Invalid Google credentials') from exc


def existing_events(service, calendar_id, start, end):
    current, token = [], None
    while True:
        response = service.events().list(calendarId=calendar_id, timeMin=start.isoformat()+'T00:00:00Z',
            timeMax=end.isoformat()+'T00:00:00Z',singleEvents=True,maxResults=2500,pageToken=token).execute()
        current.extend(response.get('items',[]))
        token = response.get('nextPageToken')
        if not token:
            return current


def sync(service, calendar_id, events, today, until, domestic_color, dry_run=False):
    existing = existing_events(service,calendar_id,today,until)
    keys = set()
    for ev in existing:
        if ev.get('status') == 'cancelled':
            continue
        start_info = ev.get('start', {})
        # Match both all-day and timed events already in the calendar.
        start = start_info.get('date') or start_info.get('dateTime', '')[:10]
        if start:
            keys.add((norm(ev.get('summary','')), start))
    added = skipped = 0
    for ev in sorted(events,key=lambda e:(e['start'],e['summary'])):
        key = tuple(map(str,event_key(ev)))
        if key in keys:
            skipped += 1
            continue
        body = {'summary':ev['summary'], 'description': ev['description']+'\nZdroj: '+ev['source'],
                'location':ev['location'], 'start':{'date':ev['start'].isoformat()},
                'end':{'date':ev['end'].isoformat()}, 'colorId':'8' if ev['international'] else domestic_color,
                'reminders':{'useDefault':False,'overrides':[]},
                'extendedProperties':{'private':{'gcalveslo':'1'}}}
        if not dry_run:
            service.events().insert(calendarId=calendar_id,body=body,sendUpdates='none').execute()
        keys.add(key)
        added += 1
    LOG.info('%s: %d, already present: %d, deleted: 0', 'Would add' if dry_run else 'Added',added,skipped)
    return added,skipped


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--page',default=PAGE)
    p.add_argument('--calendar',default=os.environ.get('GOOGLE_CALENDAR_ID'))
    p.add_argument('--domestic-color',default=os.environ.get('DOMESTIC_COLOR_ID','9'), choices=list(COLORS))
    p.add_argument('--dry-run',action='store_true',help='Preview without Google authentication or writes')
    p.add_argument('--list-colors',action='store_true')
    args=p.parse_args()
    if args.list_colors:
        for i,name in COLORS.items(): print(f'{i}: {name}')
        return
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    today=date.today()
    with requests.Session() as session:
        events,until=load_events(session,args.page,today)
    LOG.info('Date window: %s to %s (exclusive)',today,until)
    LOG.info('Domestic races: %s, foreign races: %s',sum(not x['international'] for x in events),sum(x['international'] for x in events))
    if args.dry_run:
        for e in events:
            print(f"{e['start']} | {'INT' if e['international'] else 'CZ '} | {e['summary']}")
        return
    if not args.calendar:
        raise RuntimeError('GOOGLE_CALENDAR_ID is required')
    service=build('calendar','v3',credentials=credentials(),cache_discovery=False)
    added,skipped=sync(service,args.calendar,events,today,until,args.domestic_color)
    # Only write this report after a fully successful import.
    report_path=os.environ.get('SYNC_REPORT_PATH')
    if report_path:
        import json
        from pathlib import Path
        Path(report_path).write_text(json.dumps({'added':added,'skipped':skipped,'loaded':len(events),
            'from':today.isoformat(),'until':until.isoformat()}),encoding='utf-8')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        logging.error('Sync failed: %s',exc)
        sys.exit(1)
