# GCalVeslo

Tento projekt automatizuje přidávání veslařských závodů z veslo.cz do vašeho Google Kalendáře. Načítá oficiální termínové listiny ve formátu Excel a vytváří nebo aktualizuje události ve zvoleném Google Kalendáři.

## Funkce
- Stáhne nejnovější oficiální termínovou listinu z veslo.cz
- Zpracuje data o závodech (datum, název, místo, pořadatel)
- Přidá závody do vašeho Google Kalendáře
- Zajistí, že u importovaných událostí nejsou nastaveny žádné notifikace/připomínky

## Jak používat

### Prerequisites
- Python 3.7+
- Služební účet Google (JSON soubor s přihlašovacími údaji)
- Potřebné Python balíčky: `google-api-python-client`, `google-auth`, `google-auth-oauthlib`, `google-auth-httplib2`, `pandas`, `openpyxl`, `requests`, `beautifulsoup4`

### Instalace
1. Naklonujte tento repozitář.
2. Nainstalujte závislosti:

	```sh
	pip install -r requirements.txt
	```
3. Získejte JSON soubor s přihlašovacími údaji ke služebnímu účtu Google a sdílejte cílový Google Kalendář s tímto účtem.

### Použití

#### Pomocí dávkového souboru
- Spusťte `convertveslo.bat` pro spuštění hlavního skriptu s výchozími nebo přednastavenými argumenty.
- `.bat` soubor můžete upravit a nastavit si vlastní parametry.

#### Argumenty příkazové řádky
- `--page` (povinné): URL stránky s termínovkou na veslo.cz (např. `https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1`)
- `--year` (volitelné): Rok pro výběr listu v Excelu (výchozí: aktuální rok)
- `--months` (volitelné): Seznam měsíců (čísla) pro filtrování závodů
- `--inter` (volitelné): Filtrování podle typu závodu (`all`, `true`, `false`)
- `--calendar` (volitelné): ID cílového Google Kalendáře (výchozí: `primary`)
- `--creds` (povinné): Cesta k JSON souboru s přihlašovacími údaji

**Příklad:

**
```sh
python gcalveslo.py --page "https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1" --year 2025 --creds rowcalendar-c4af9fb74753.json
```

#### Co dělá dávkový soubor
- Dávkový soubor (`convertveslo.bat`)  je zástupce pro spuštění Python skriptu s vašimi preferovanými argumenty. Můžete jej upravit dle potřeby.

## Možná vylepšení
- Interaktivní výběr Excel souboru, pokud je jich více
- Možnost přidat vlastní připomínky/notifikace
- Lepší handling Zrušených zavodů (mazat už existující)
- Kriptograficky heslovane údaje
- Lepší rozhraní -> .exe
