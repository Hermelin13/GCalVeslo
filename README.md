# GCalVeslo – bezpečnější automatický import

Každých 14 dní načte závody ČVS z webu, vloží chybějící celodenní akce a odstraní prokazatelně zrušené závody, které dříve vložil program, z Google Kalendáře. Zpracuje pouze závody ode dne spuštění do stejného dne následujícího roku (koncový den není zahrnut). Zdrojem je oficiální stránka `https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1`.

- Českým závodům nastaví barvu z `DOMESTIC_COLOR_ID` (výchozí 9 – modrá).
- Mezinárodní závody rozpoznává z kurzívy v termínové listině a nastaví barvu 8 – Graphite (uhlíková/šedá).
- Neimportuje mistrovství světa ani Evropy v žádné veslařské disciplíně (včetně Indoor, Coastal Rowing, Beach Sprint, Masters, U23 a Junior Championships), světové/evropské poháry ani samostatně pojmenované Indoor Championships a Coastal Rowing Championships. **Tyto akce jsou vynechány**, nikoli zapsány jako šedé. Mistrovství ČR a běžné regaty zůstávají.
- Při shodě normalizovaného názvu a dne začátku se událost nevkládá podruhé, i když má jiné datum konce, jiné zdrojové XLSX nebo jde o časovanou událost v cílovém kalendáři. Duplicity kontroluje mezi staženými zdroji i vůči cílovému kalendáři; běžné duplicity existujících událostí nemaže.
- Zrušené závody (text „ZRUŠENO“/„cancelled“/„odvoláno“, žluté nebo červené označení v XLSX, přeškrtnutí) se neimportují. Pokud stejný závod se stejným datem začátku už zapsal tento program, smaže ho z cílového kalendáře; vlastní cizí události nemaže. Zrušení má přednost před aktivním záznamem ze starší/jiné tabulky.
- Hledá nové soubory na webu při každém spuštění; nepředpokládá, že budoucí soubor už existuje. Pokud nový zdroj chybí, importuje dostupné závody; **nikdy nemaže jen proto, že závod zmizel nebo zdroj nelze načíst**. Mazání vyžaduje explicitní informaci o zrušení.
- Pokud zdroje nelze přečíst, proces skončí chybou a GitHub Actions může zaslat e-mail přes SMTP.

## DŮLEŽITÉ: zabezpečení

Původní repozitář obsahoval *privátní klíč služby Google* a jeho historii `.git`. **Nejprve smažte/zneplatněte původní klíč v Google Cloud Console a vytvořte nový**. Nový klíč NIKDY necommitujte a neposílejte do veřejného repozitáře. Přehodnoťte i sdílení kalendáře a přístup účtu služby. Starý klíč může zůstávat v Git historii i po odstranění souboru; očistěte historii (např. `git filter-repo`) nebo založte nový čistý repozitář. Tento balíček je bez historie a bez klíče.

Na GitHubu v `Settings → Secrets and variables → Actions` nastavte:

| Typ | Název | Hodnota |
| --- | --- | --- |
| Secret | `GOOGLE_CREDENTIALS_B64` | Base64 nového JSON service-account klíče |
| Secret | `GOOGLE_CALENDAR_ID` | ID sdíleného cílového kalendáře |
| Variable | `DOMESTIC_COLOR_ID` | Číslo 1–11 pro české závody |
| Secret | `DISCORD_WEBHOOK_URL` | URL Discord webhooku pro oznámení o úspěchu i chybě |
| Secret | `ALERT_EMAIL` | Váš e-mail pro chyby (volitelné) |
| Secret | `SMTP_HOST` | Server odchozí pošty, např. `smtp.gmail.com` |
| Secret | `SMTP_PORT` | `587` (STARTTLS) |
| Secret | `SMTP_USER` | Odesílací e-mail |
| Secret | `SMTP_PASSWORD` | Aplikační heslo / SMTP token, nikoli běžné heslo účtu |

E-mail je volitelný: pokud chcete kromě Discordu i e-mail o chybě, **všechny SMTP položky jsou povinné**. Poštovní údaje se nikdy nedávají do Python souborů.

Base64 vytvoříte lokálně například přes `python -c "import base64;print(base64.b64encode(open('new-google-key.json','rb').read()).decode())"`. Výstup vložte pouze do GitHub Secret. U služby Google musí být kalendář sdílený s e-mailovou adresou service account s oprávněním pro úpravy.

## Discord oznámení

V Discordu otevřete nastavení konkrétního kanálu → **Integrace → Webhooky → Nový webhook** (je potřeba oprávnění „Spravovat webhooky“). Klikněte na **Kopírovat URL webhooku** a vložte ji jako GitHub Actions repository secret `DISCORD_WEBHOOK_URL` v **Settings → Secrets and variables → Actions**. Webhook je tajný přístupový údaj; **neposílejte jej nikomu a nedávejte jej do repozitáře**. Pokud unikne, smažte jej a vytvořte nový.

Po každém skutečném importu (včetně ručního spuštění) odešle workflow na Discord zprávu o úspěchu s počtem přidaných, přeskočených, zrušených ve zdrojích, **odstraněných z kalendáře** a všech načtených závodů i s odkazem na GitHub Actions. Při selhání některého kroku workflow odešle upozornění na chybu s odkazem na běh. V týdnu, kdy se pravidelný import neprovádí, žádné oznámení neposílá. Discord webhook posílá do **jednoho vybraného kanálu** a nepotřebuje bot token. Pokud `DISCORD_WEBHOOK_URL` není nastaven, Discord oznámení se přeskočí. Při výpadku Discordu může oznámení selhat, i když se závody úspěšně zapsaly; ověřujte stav běhu v GitHub Actions.

## Spouštění

Workflow `.github/workflows/sync.yml` má plán každé pondělí ráno v 09:17 času Prahy, ale vložení vykoná pouze v každém druhém týdnu (počínaje 19. 10. 2026). Ručně lze spustit v `Actions → Import rowing races → Run workflow`. GitHub může plánované spuštění zpozdit; v neaktivním veřejném repozitáři se automatika může vypnout.

Instalace lokálně: `pip install -r requirements.txt`. Příkaz `python gcalveslo.py --list-colors` vypíše barvy; `python gcalveslo.py --dry-run` ukáže nalezené závody bez přístupu ke Google. Pro ostrý import nastavte prostředí `GOOGLE_CREDENTIALS_B64`, `GOOGLE_CALENDAR_ID` a volitelně `DOMESTIC_COLOR_ID`, pak spusťte `python gcalveslo.py`.

**Omezení:** staré `.xls` nejsou podporovány (zapisují upozornění); pro import je nutný `.xlsx` s rozpoznatelnými názvy sloupců a listem pojmenovaným rokem. Barevné rozpoznávání používá běžné barvy buněk (RGB, indexované a barvy šablony Excel); **podmíněné formátování, které Excel vypočítává až při otevření, nelze pomocí openpyxl spolehlivě vyhodnotit**. Pokud zdroj používá takové zabarvení nebo pouze barevně označenou stránku PDF, je třeba doplnit speciální parser. Při změně struktury webu nebo souboru je potřeba parser přizpůsobit. Bez skutečného přístupu ke Google API nelze na této straně potvrdit zápis. Program nezajišťuje automatické úpravy již existujících závodů při změně termínu: nový termín může být vložen jako další akce.

## Bezpečné soubory v Gitu

`.gitignore` chrání lokální `.env` soubory, Google service-account klíče, tokeny,
certifikáty, exporty závodů, dočasné soubory a Python cache. Soubory `requirements.txt`,
`gcalveslo.py`, `notify_failure.py`, `notify_discord.py`, `.github/workflows/sync.yml` a testy se naopak
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

### Rozšířený filtr mistrovství

Import vynechává také zkratky **MS, ME, WRICH, WRCH, ERICH, ERCH, WRBSCH a WRC** a akce označené **Para Rowing / paraveslování**. České mistrovství ČR a běžné regaty zůstávají povolené. Filtr se uplatní jen na nové importy; již zapsané akce automaticky nemaže.

### Další vyloučené závody (podle zpětné vazby)

Import nadále **ponechává Kontrolní závody seniorů (včetně varianty A)**;
vynechává **World Rowing Beach Sprint Series**, **World Rowing Beach Sprint Finals**,
**YOG / Youth Olympic Games**, **Coupe de la Jeunesse** a **European Games**.
Platí to pro nové importy; již zapsané události se automaticky nemažou.


### Již existující duplicity v kalendáři

Při každém běhu program také vypíše varování `Already duplicated in target calendar`,
pokud najde dvě existující události se stejným názvem a datem začátku.
Další kopie nevytvoří, ale existující záznamy kvůli ochraně ostatních
událostí automaticky nemaže. Pokud události vidíš dvakrát v Google Calendar,
ověř, zda obě patří do stejného kalendáře (nejsou z překrývajících se kalendářů).


### Dvojitá kontrola filtru (oprava 2026-10-16)

Zakázané závody se nyní vynechávají při čtení XLSX **a znovu těsně před
`events().insert()`**. Tím se nepropíše ani World Rowing Beach Sprint Finals,
Beach Sprint Series, WRICH, mezinárodní PARA Rowing, YOG, European Games ani
Coupe de la Jeunesse, pokud by se do importu dostaly jinou cestou.
Povolené české závody (včetně Kontrolních závodů seniorů A) zůstávají.
Existující zakázané položky se automaticky nemažou (výjimkou je výslovně zrušený závod, který lze bezpečně přiřadit k tomuto programu).


## Zrušené závody – automatický úklid (2026-10-19)

Program rozpoznává zrušení na řádku termínovky XLSX v těchto případech:

- Text „ZRUŠENO“, „zrušené“, „cancelled“, „canceled“, „odvoláno“, „neuskuteční se“ v názvu, stavu nebo jiném poli řádku.
- Žluté či červené vybarvení buňky (i světlé odstíny), červený/žlutý text nebo přeškrtnuté písmo na řádku závodu. Funguje pro RGB, indexované i barvy šablony v `.xlsx`.

Pravidla synchronizace:

1. Takový závod se **nikdy nově nevloží**.
2. Pokud už v cílovém Google Kalendáři existuje **stejný normalizovaný název a počáteční den**, odstraní se pouze položky vytvořené GCalVeslo – poznají se podle interní značky `extendedProperties.private.gcalveslo=1` nebo podle odkazu `Zdroj: https://www.veslo.cz/...` ve starším záznamu.
3. Uživatelem ručně založené události bez značky či odkazu se **nemažou**, i kdyby měly stejný název a datum. Zrušení nemusí odstranit starší událost, pokud jí byl mezitím změněn název nebo datum.
4. Zrušení z jedné tabulky má přednost před duplicitním aktivním záznamem jiné tabulky. **Pouhé zmizení položky ze zdroje neznamená zrušení a neslouží jako důvod ke smazání.**
5. Při selhání volání Google Calendar API běh skončí chybou a GitHub Actions spustí Discord upozornění. Při úspěchu ukáže oznámení také počty zrušených a odstraněných událostí.

Pro rychlou kontrolu zdrojových tabulek bez Google účtu spusťte `python gcalveslo.py --dry-run`: zrušené závody se vypíšou se značkou `CANCELLED`, ale v tomto režimu není možné určit, kolik by se jich v Google Kalendáři skutečně smazalo. Test před ostrým nasazením proto doporučujeme na **testovacím kalendáři**. Google služba musí mít oprávnění k úpravám událostí. 
