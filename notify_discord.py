"""Post a safe sync summary/error alert to a Discord webhook (no secrets in body)."""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def build_message(status, report=None, run_url=''):
    if status == 'success':
        if report:
            desc = (f"Nově přidáno: **{report['added']}**\n"
                    f"Již existuje (přeskočeno): **{report['skipped']}**\n"
                    f"Načteno závodů: **{report['loaded']}**\n"
                    f"Období: {report['from']} až {report['until']} (konec nezahrnut)")
        else:
            desc = 'Synchronizace proběhla, ale souhrn nebyl vytvořen.'
        title = '✅ GCalVeslo: synchronizace dokončena'
        color = 0x2ECC71
    else:
        title = '🚨 GCalVeslo: chyba synchronizace'
        desc = 'Synchronizace selhala. Zkontroluj protokol běhu v GitHub Actions. (Podrobnosti chyby neodesíláme, aby neunikly přihlašovací údaje.)'
        color = 0xE74C3C
    if run_url.startswith('https://github.com/') or run_url.startswith('https://github.'):
        desc += '\n[Zobrazit běh GitHub Actions](' + run_url + ')'
    return {'username':'GCalVeslo', 'allowed_mentions':{'parse':[]},
            'embeds':[{'title':title, 'description':desc, 'color':color}]}


def main():
    status = sys.argv[1] if len(sys.argv) > 1 else ''
    if status not in ('success','failure'):
        raise SystemExit('Usage: python notify_discord.py success|failure')
    webhook = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook:
        raise SystemExit('Missing DISCORD_WEBHOOK_URL GitHub Secret')
    report = None
    if status == 'success':
        path = Path(os.environ.get('SYNC_REPORT_PATH', 'sync-report.json'))
        if path.exists():
            report = json.loads(path.read_text(encoding='utf-8'))
    body = json.dumps(build_message(status, report, os.environ.get('RUN_URL',''))).encode('utf-8')
    request = urllib.request.Request(webhook, body, {'Content-Type':'application/json', 'User-Agent':'GCalVeslo/1.0'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status not in (200, 204):
                raise RuntimeError(f'Discord returned HTTP {response.status}')
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Discord webhook returned HTTP {exc.code}') from None
    except urllib.error.URLError:
        raise RuntimeError('Discord webhook connection failed') from None


if __name__ == '__main__':
    main()
