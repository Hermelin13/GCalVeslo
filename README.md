# GCalVeslo – bezpečnější automatický import

Každých 14 dní načte závody ČVS z webu a vloží chybějící celodenní akce do Google Kalendáře. Zpracuje pouze závody ode dne spuštění do stejného dne následujícího roku (koncový den není zahrnut). Zdrojem je oficiální stránka `https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1`.

- Českým závodům nastaví barvu z `DOMESTIC_COLOR_ID` (výchozí 9 – modrá).
- Mezinárodní závody rozpoznává z kurzívy v termínové listině a nastaví barvu 8 – Graphite (uhlíková/šedá).
- Neimportuje mistrovství světa, mistrovství Evropy ani světový pohár (včetně základních anglických názvů). **Tyto akce jsou vynechány**, nikoli zapsány jako šedé.
- Při shodě normalizovaného názvu, data začátku a data konce se událost nevkládá podruhé. Nikdy nemaže ani nemění stávající události, dokonce ani ty cizí.
- Hledá nové soubory na webu při každém spuštění; nepředpokládá, že budoucí soubor už existuje. Pokud není k dispozici, importuje dostupné závody; nic nemaže.
- Pokud zdroje nelze přečíst, proces skončí chybou a GitHub Actions může zaslat e-mail přes SMTP.

## DŮLEŽITÉ: zabezpečení

Původní repozitář obsahoval *privátní klíč služby Google* a jeho historii `.git`. **Nejprve smažte/zneplatněte původní klíč v Google Cloud Console a vytvořte nový**. Nový klíč NIKDY necommitujte a neposílejte do veřejného repozitáře. Přehodnoťte i sdílení kalendáře a přístup účtu služby. Starý klíč může zůstávat v Git historii i po odstranění souboru; očistěte historii (např. `git filter-repo`) nebo založte nový čistý repozitář. Tento balíček je bez historie a bez klíče.

Na GitHubu v `Settings → Secrets and variables → Actions` nastavte:

| Typ | Název | Hodnota |
| --- | --- | --- |
| Secret | `GOOGLE_CREDENTIALS_B64` | Base64 nového JSON service-account klíče |
| Secret | `GOOGLE_CALENDAR_ID` | ID sdíleného cílového kalendáře |
| Variable | `DOMESTIC_COLOR_ID` | Číslo 1–11 pro české závody |
| Secret | `ALERT_EMAIL` | Váš e-mail pro chyby |
| Secret | `SMTP_HOST` | Server odchozí pošty, např. `smtp.gmail.com` |
| Secret | `SMTP_PORT` | `587` (STARTTLS) |
| Secret | `SMTP_USER` | Odesílací e-mail |
| Secret | `SMTP_PASSWORD` | Aplikační heslo / SMTP token, nikoli běžné heslo účtu |

Pokud chcete e-mail o chybě, **všechny SMTP položky jsou povinné**. Poštovní údaje se nikdy nedávají do Python souborů.

Base64 vytvoříte lokálně například přes `python -c "import base64;print(base64.b64encode(open('new-google-key.json','rb').read()).decode())"`. Výstup vložte pouze do GitHub Secret. U služby Google musí být kalendář sdílený s e-mailovou adresou service account s oprávněním pro úpravy.

## Spouštění

Workflow `.github/workflows/sync.yml` má plán každé pondělí ráno v 09:17 času Prahy, ale vložení vykoná pouze v každém druhém týdnu (počínaje 19. 10. 2026). Ručně lze spustit v `Actions → Import rowing races → Run workflow`. GitHub může plánované spuštění zpozdit; v neaktivním veřejném repozitáři se automatika může vypnout.

Instalace lokálně: `pip install -r requirements.txt`. Příkaz `python gcalveslo.py --list-colors` vypíše barvy; `python gcalveslo.py --dry-run` ukáže nalezené závody bez přístupu ke Google. Pro ostrý import nastavte prostředí `GOOGLE_CREDENTIALS_B64`, `GOOGLE_CALENDAR_ID` a volitelně `DOMESTIC_COLOR_ID`, pak spusťte `python gcalveslo.py`.

**Omezení:** staré `.xls` nejsou podporovány (zapisují upozornění); pro import je nutný `.xlsx` s rozpoznatelnými názvy sloupců a listem pojmenovaným rokem. Při změně struktury webu nebo souboru je potřeba parser přizpůsobit. Bez skutečného přístupu ke Google API nelze na této straně potvrdit zápis. Program nezajišťuje automatické úpravy již existujících závodů při změně termínu: nový termín může být vložen jako další akce.

## Bezpečné soubory v Gitu

`.gitignore` chrání lokální `.env` soubory, Google service-account klíče, tokeny,
certifikáty, exporty závodů, dočasné soubory a Python cache. Soubory `requirements.txt`,
`gcalveslo.py`, `notify_failure.py`, `.github/workflows/sync.yml` a testy se naopak
verzují. Před prvním push zkontrolujte `git status --short` a `git ls-files`.

**Důležité:** `.gitignore` neodstraní soubory, které již byly commitnuté,
ani klíče z historie. Původní Google service-account klíč zneplatněte v Google Cloud,
vytvořte nový a vložte pouze do GitHub Secrets. Jestli je starý klíč stále sledovaný,
vyřaďte ho z indexu příkazem `git rm --cached <cesta-ke-klici>` (lokální soubor
zůstane zachovaný), a případně vyčistěte historii Git repozitáře.

### Barvy v novém Google Kalendáři (2026)

Současná verze programu používá starší API `colorId` (11 barev událostí).
Google v roce 2026 přidal **24 výchozích barev a až 200 vlastních barevných
štítků pro jednotlivý kalendář**. Jejich využití vyžaduje rozšíření integrace
o `eventLabelId` a `eventLabelVersion=1` a vytvoření příslušných štítků.
Nezaměňujte novější štítky s číselnými hodnotami `DOMESTIC_COLOR_ID=1..11`.
Dokud není vybrána nová barva a implementace štítků, program nadále používá
stávající barvy, včetně grafitové (8) pro mezinárodní závody.
