@echo off
REM Compute the next 6 months from today, group by year and invoke gcalveslo.py per year
setlocal enabledelayedexpansion

REM Configure these once
set "PAGE=https://www.veslo.cz/zavody/terminovky-vypsani-a-rozlosovani?disciplineId=1"
set "CREDS=rowcalendar-c4af9fb74753.json"
set "CAL=family16658134994112439829@group.calendar.google.com"

set "BASE_CMD=python gcalveslo.py --inter false --calendar %CAL% --creds %CREDS% --page %PAGE%"

REM Build and run commands for the next 6 months (including current month)
REM Use PowerShell to produce a simple "year|months" list into a file in the script directory
set "TMPFILE=%~dp0gcal_months.txt"
echo [DEBUG] TMPFILE=%TMPFILE%
echo Generating year^|month list into %TMPFILE% using Python
python -c "import datetime; s=datetime.date.today(); lines=[str((s.month+i-1)//12 + s.year)+'|'+str(((s.month+i-1)%%12)+1) for i in range(0,7)]; print('\n'.join(lines))" > "%TMPFILE%"
echo [DEBUG] Python exit code=%ERRORLEVEL%
if exist "%TMPFILE%" (
	echo [DEBUG] Month pairs file contents:
	type "%TMPFILE%"
) else (
	echo [DEBUG] Month pairs file not created
)

rem Group months by year in batch variables
set "YEARS="
for /f "usebackq tokens=1,2 delims=|" %%A in ("%TMPFILE%") do (
	if not defined months%%A (
		set "months%%A=%%B"
		set "YEARS=!YEARS! %%A"
	) else (
		set "months%%A=!months%%A! %%B"
	)
)

for %%Y in (!YEARS!) do (
	set "M=!months%%Y!"
	echo Running: !BASE_CMD! --year %%Y --months !M!
	!BASE_CMD! --year %%Y --months !M!
)

del "%TMPFILE%"

pause