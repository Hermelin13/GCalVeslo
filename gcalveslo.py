#!/usr/bin/env python3
"""Synchronize rowing events from ČVS workbooks into Google Calendar."""
import argparse
import base64
import colorsys
import io
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from openpyxl.styles.colors import COLOR_INDEX

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
    r"|(?:para[ -]?rowing|para[ -]?veslov[aá]n[ií])\b"
    r"|sv[eě]tov[yý]\s+poh[aá]r"
    r"|(?:world|european)(?:\s+rowing)?\s+cup"
    r"|(?:world|european)\s+(?:[\w-]+\s+){0,8}championships?\b"
    r"|(?:indoor|coastal(?:\s+rowing)?)\s+championships?\b"
    r"|(?:championships?\s+(?:of\s+the\s+)?(?:world|europe))\b"
    r"|(?:world\s+rowing\s+)?beach\s+sprint\s+(?:series|finals?)\b"
    r"|(?:yog(?:\s+|[-–—])|youth\s+olympic\s+games\b)"
    r"|coupe\s+de\s+la\s+jeunesse\b"
    r"|(?:\d+(?:st|nd|rd|th)\s+)?european\s+games\b"
    r"|(?:mistrovstv[ií]\s+(?:sv[eě]ta|evropy)\s+(?:v|ve)\s+[^,;]+)"
    r")",
    re.I,
)

LOG = logging.getLogger('gcalveslo')

# Cancellations must survive parsing so they can also remove previously imported races.
CANCEL_WORDS = re.compile(
    r'\b(?:zrušen\w*|zrusen\w*|'
    r'cancelled|canceled|odvoláno|odvolano|neuskuteční se|neuskutecni se)\b', re.I)
LEGACY_SOURCE = re.compile(r'(?im)^\s*Zdroj:\s*https://(?:www\.)?veslo\.cz(?:/|$)')


def clean_cancelled_title(title):
    """Remove status banners so 'ZRUŠENO !!! Regata' matches 'Regata'."""
    cleaned = CANCEL_WORDS.sub('', str(title or ''))
    return re.sub(r'^[\s!.,:;()\[\]-]+|[\s!.,:;()\[\]-]+$', '', cleaned).strip()


def workbook_theme_colors(workbook):
    """Resolve Excel theme colors, which may be used for cancellation highlights."""
    if not workbook.loaded_theme:
        return {}
    try:
        root = ElementTree.fromstring(workbook.loaded_theme)
        ns = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
        scheme = root.find('.//' + ns + 'clrScheme')
        if scheme is None:
            return {}
        theme_names = ('lt1', 'dk1', 'lt2', 'dk2', 'accent1', 'accent2',
                       'accent3', 'accent4', 'accent5', 'accent6', 'hlink', 'folHlink')
        result = {}
        for idx, name in enumerate(theme_names):
            entry = scheme.find(ns + name)
            if entry is not None and len(entry):
                value = entry[0].get('lastClr') or entry[0].get('val')
                if value and re.fullmatch(r'[0-9a-fA-F]{6}', value):
                    result[idx] = value
        return result
    except (ElementTree.ParseError, ValueError):
        return {}


def color_rgb(color, theme_colors=None):
    """Read Excel RGB, indexed and workbook-theme colors."""
    if color is None:
        return None
    kind = getattr(color, 'type', None)
    if kind == 'rgb':
        value = getattr(color, 'rgb', None)
    elif kind == 'indexed':
        index = getattr(color, 'indexed', None)
        if not isinstance(index, int) or index >= len(COLOR_INDEX):
            return None
        value = COLOR_INDEX[index]
    elif kind == 'theme':
        index = getattr(color, 'theme', None)
        value = (theme_colors or {}).get(index)
    else:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{6}|[0-9a-fA-F]{8}', value):
        return None
    value = value[-6:]
    rgb = tuple(int(value[i:i+2], 16) for i in (0, 2, 4))
    # Excel's theme tint increases/decreases perceived lightness.
    tint = getattr(color, 'tint', 0) or 0
    if kind == 'theme' and tint:
        hue, lightness, saturation = colorsys.rgb_to_hls(*(x / 255 for x in rgb))
        lightness = lightness * (1 + tint) if tint < 0 else lightness + (1 - lightness) * tint
        rgb = tuple(round(x * 255) for x in colorsys.hls_to_rgb(hue, max(0, min(1, lightness)), saturation))
    return rgb


def is_alert_color(color, theme_colors=None):
    """Recognize red or yellow, including common pastel Excel warning fills."""
    rgb = color_rgb(color, theme_colors)
    if rgb is None:
        return False
    hue, saturation, value = colorsys.rgb_to_hsv(*(x / 255 for x in rgb))
    hue *= 360
    return (saturation >= 0.15 and
            (((hue <= 16 or hue >= 344) and value >= 0.30) or
             (37 <= hue <= 68 and value >= 0.50)))


def cancelled_row(row, title_cell, theme_colors=None):
    """A race is cancelled when explicitly marked in text or Excel styling."""
    if any(CANCEL_WORDS.search(str(c.value)) for c in row if c.value is not None):
        return 'status text'
    # Only inspect real race rows (their dates have already been parsed).
    # Formatting can cover the whole row or just the name/status cell.
    for c in row:
        if c.font and c.font.strike:
            return 'strikethrough'
        if c.fill and c.fill.patternType == 'solid' and is_alert_color(c.fill.fgColor, theme_colors):
            return 'yellow/red highlight'
        if c.font and is_alert_color(c.font.color, theme_colors):
            return 'red/yellow text'
    return None


def is_managed_event(event):
    """Never delete someone's own calendar events, even with same name/date."""
    private = event.get('extendedProperties', {}).get('private', {})
    if str(private.get('gcalveslo', '')) == '1':
        return True
    # Backwards compatibility for our earlier imports without private marker.
    return bool(LEGACY_SOURCE.search(str(event.get('description', ''))))



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
    theme_colors = workbook_theme_colors(wb)
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
                reason = cancelled_row(row, title_cell, theme_colors)
                # Keep excluded races out of import, but retain cancellations:
                # an older version may have already written the event.
                if is_excluded(name) and not reason:
                    LOG.info('Excluded from source: %s', name)
                    continue
                organizer = cell('poradatel')
                location = cell('misto')
                # Original ČVS workbooks distinguish foreign competitions by italic text.
                international = any(c.font and c.font.italic for c in row[:4])
                result.append(dict(summary=name, start=first, end=last+timedelta(days=1),
                                   description=str(organizer.value or '').strip() if organizer else '',
                                   location=str(location.value or '').strip() if location else '',
                                   international=international, source=source_url,
                                   cancelled=bool(reason), cancel_reason=reason))
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
            # Cancellation takes precedence across all workbooks, even if a
            # different edition still contains this race as active.
            if key not in events or (ev['cancelled'] and not events[key]['cancelled']):
                events[key] = ev
    if not successfully_read:
        raise RuntimeError('Could not parse any published term list. Calendar unchanged.')
    LOG.info('Read %d unique races (%d cancelled) from %d workbooks',len(events),
             sum(e['cancelled'] for e in events.values()),successfully_read)
    # Keep positively cancelled rows for deletion; never import excluded races.
    return [ev for ev in events.values() if ev['cancelled'] or not is_excluded(ev['summary'])],end


def is_excluded(title):
    """One shared exclusion policy, checked at extraction AND insertion."""
    return bool(EXCLUDED.search(str(title or '')))


def canonical_title(title):
    # ČVS sometimes publishes the same senior control races with and without
    # a trailing A. Restrict this alias to this event, not other race classes.
    title = norm(clean_cancelled_title(title))
    if title in ('kontrolní závody seniorů', 'kontrolní závody seniorů a'):
        return 'kontrolní závody seniorů'
    return title


def event_key(ev):
    # Same canonical title and start date: one race, even across workbooks.
    return (canonical_title(ev['summary']), str(ev['start']))


def credentials():
    value = os.environ.get('GOOGLE_CREDENTIALS_B64')
    if not value:
        raise RuntimeError('Set GOOGLE_CREDENTIALS_B64 to base64 encoded service account JSON')
    try:
        import json
        from google.oauth2 import service_account
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
    existing = existing_events(service, calendar_id, today, until)
    keys = set()
    by_key = {}
    repeated = {}
    for ev in existing:
        if ev.get('status') == 'cancelled':
            continue
        start_info = ev.get('start', {})
        start = start_info.get('date') or start_info.get('dateTime', '')[:10]
        if start:
            key = (canonical_title(ev.get('summary', '')), start)
            by_key.setdefault(key, []).append(ev)
            if key in keys:
                repeated[key] = repeated.get(key, 1) + 1
            keys.add(key)
    for (name, day), count in sorted(repeated.items()):
        LOG.warning('Already duplicated in target calendar: %s | %s | %d occurrences', day, name, count)

    added = skipped = deleted = 0
    # Process explicit cancellations first, including races which would otherwise
    # be filtered out. Never delete because an event simply vanished from XLSX.
    cancelled_keys = {tuple(map(str, event_key(ev))) for ev in events if ev.get('cancelled')}
    for key in sorted(cancelled_keys):
        matches = by_key.get(key, [])
        for old in matches:
            if not is_managed_event(old):
                LOG.warning('Cancelled race exists but is not owned by GCalVeslo: %s | %s (left unchanged)', key[1], key[0])
                continue
            if not old.get('id'):
                LOG.warning('Cancelled race has no event ID: %s | %s (left unchanged)', key[1], key[0])
                continue
            if not dry_run:
                # API errors bubble up so GitHub Actions and Discord report failure.
                service.events().delete(calendarId=calendar_id, eventId=old['id'],
                                        sendUpdates='none').execute()
            deleted += 1
            LOG.info('%s cancelled race: %s | %s', 'Would delete' if dry_run else 'Deleted', key[1], old.get('summary'))
        keys.add(key)

    for ev in sorted(events, key=lambda e: (e['start'], e['summary'])):
        key = tuple(map(str, event_key(ev)))
        if ev.get('cancelled'):
            LOG.info('Cancelled in source (%s): %s', ev.get('cancel_reason', 'marked'), ev['summary'])
            skipped += 1
            continue
        if is_excluded(ev['summary']):
            LOG.info('Excluded before calendar insert: %s', ev['summary'])
            skipped += 1
            continue
        # Protect against unmerged duplicates supplied directly to sync().
        if key in keys or key in cancelled_keys:
            skipped += 1
            continue
        body = {'summary': ev['summary'], 'description': ev['description']+'\nZdroj: '+ev['source'],
                'location': ev['location'], 'start': {'date': ev['start'].isoformat()},
                'end': {'date': ev['end'].isoformat()}, 'colorId': '8' if ev['international'] else domestic_color,
                'reminders': {'useDefault': False, 'overrides': []},
                'extendedProperties': {'private': {'gcalveslo': '1'}}}
        if not dry_run:
            service.events().insert(calendarId=calendar_id, body=body, sendUpdates='none').execute()
        keys.add(key)
        added += 1
    LOG.info('%s: %d, skipped: %d, %s cancelled events: %d',
             'Would add' if dry_run else 'Added', added, skipped,
             'would delete' if dry_run else 'deleted', deleted)
    return added, skipped, deleted


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
    LOG.info('Domestic races: %s, foreign races: %s, cancelled: %s',
             sum(not x['international'] and not x.get('cancelled') for x in events),
             sum(x['international'] and not x.get('cancelled') for x in events),
             sum(x.get('cancelled', False) for x in events))
    if args.dry_run:
        for e in events:
            print(f"{e['start']} | {'CANCELLED' if e.get('cancelled') else ('INT' if e['international'] else 'CZ ')} | {e['summary']}")
        return
    if not args.calendar:
        raise RuntimeError('GOOGLE_CALENDAR_ID is required')
    from googleapiclient.discovery import build
    service=build('calendar','v3',credentials=credentials(),cache_discovery=False)
    added,skipped,deleted=sync(service,args.calendar,events,today,until,args.domestic_color)
    # Only write this report after a fully successful import.
    report_path=os.environ.get('SYNC_REPORT_PATH')
    if report_path:
        import json
        from pathlib import Path
        Path(report_path).write_text(json.dumps({'added':added,'skipped':skipped,'deleted':deleted,
            'cancelled':sum(e.get('cancelled', False) for e in events),'loaded':len(events),
            'from':today.isoformat(),'until':until.isoformat()}),encoding='utf-8')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        logging.error('Sync failed: %s',exc)
        sys.exit(1)
