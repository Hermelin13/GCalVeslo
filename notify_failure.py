"""Send an SMTP TLS warning if a GitHub Actions step fails."""
import os
import smtplib
import ssl
from email.message import EmailMessage

required = ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','ALERT_EMAIL']
if any(not os.getenv(key) for key in required):
    raise SystemExit('SMTP alert not configured; check required GitHub Secrets')

msg = EmailMessage()
msg['Subject'] = '[GCalVeslo] Synchronizace selhala'
msg['From'] = os.environ['SMTP_USER']
msg['To'] = os.environ['ALERT_EMAIL']
msg.set_content('Import veslařských závodů se nezdařil. Podrobnosti: '+os.environ.get('RUN_URL','GitHub Actions'))
with smtplib.SMTP(os.environ['SMTP_HOST'], int(os.environ.get('SMTP_PORT') or 587), timeout=20) as smtp:
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
    smtp.send_message(msg)
