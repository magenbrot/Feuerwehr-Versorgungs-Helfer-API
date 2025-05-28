"""Versendet schön formatierte HTML-Mails mit einem optionalen Logo und Text-Fallback."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from typing import Dict, Any # Optional entfernt
import re
import traceback

# Kein dataclass mehr für EmailContent und SmtpConfig

def sende_formatierte_email(empfaenger_email: str, betreff: str, content: Dict[str, Any], smtp_cfg: Dict[str, Any]) -> bool:
    """
    Versendet eine formatierte HTML-E-Mail mit optionalem Logo und Text-Fallback.
    Verwendet Dictionaries für Inhalt und SMTP-Konfiguration.

    Args:
        empfaenger_email: Die E-Mail-Adresse des Empfängers.
        betreff: Der Betreff der E-Mail.
        content: Ein Dictionary mit dem E-Mail-Inhalt.
                 Erwartete Schlüssel: 'html' (str), 'text' (str), 'logo_pfad' (str oder None).
        smtp_cfg: Ein Dictionary mit den SMTP-Serverdetails.
                  Erwartete Schlüssel: 'host' (str), 'port' (int),
                                     'user' (str), 'password' (str), 'sender' (str).

    Returns:
        bool: True, wenn die E-Mail erfolgreich gesendet wurde, sonst False.
    """
    # Zugriff auf Werte aus den Dictionaries
    # SMTP Konfiguration
    smtp_host = smtp_cfg.get('host')
    smtp_port = smtp_cfg.get('port')
    smtp_user = smtp_cfg.get('user')
    smtp_password = smtp_cfg.get('password')
    smtp_sender = smtp_cfg.get('sender')

    if not all([smtp_host, smtp_port, smtp_user, smtp_password, smtp_sender]):
        print("Fehler: Unvollständige SMTP-Konfiguration. Benötigt: host, port, user, password, sender.")
        return False
    try:
        smtp_port = int(smtp_port) # Sicherstellen, dass der Port eine Zahl ist
    except ValueError:
        print(f"Fehler: SMTP-Port '{smtp_port}' ist keine gültige Zahl.")
        return False

    # E-Mail Inhalt
    html_content = content.get('html', '') # Standardwert leerer String
    text_content = content.get('text', '') # Standardwert leerer String
    logo_pfad_content = content.get('logo_pfad') # Standardwert None, kann str oder None sein

    # Erstelle die Root-Nachricht
    msg = MIMEMultipart('related')
    msg['From'] = smtp_sender
    msg['To'] = empfaenger_email
    msg['Subject'] = betreff

    # Erstelle den alternativen Teil für HTML und Text
    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)

    # Füge den reinen Text-Teil hinzu
    text_part = MIMEText(text_content, 'plain', 'utf-8')
    msg_alternative.attach(text_part)

    # Temporäre HTML-Variable für Logo-CID-Ersetzung
    html_to_send = html_content
    logo_cid = 'logoimage'

    # Füge den HTML-Teil hinzu
    if logo_pfad_content and Path(logo_pfad_content).is_file():
        html_to_send = html_to_send.replace('cid:logo', f'cid:{logo_cid}') # Ersetze cid:logo nur, wenn Logo vorhanden
        html_part = MIMEText(html_to_send, 'html', 'utf-8')
    elif 'cid:logo' in html_to_send: # Logo-Platzhalter ist da, aber kein gültiges Logo
        print(f"Warnung: Logo-Platzhalter 'cid:logo' im HTML gefunden, aber kein gültiger logo_pfad ('{logo_pfad_content}') angegeben oder Datei nicht gefunden. Logo-Referenz wird entfernt.")
        # Entferne den img-Tag, der das Logo referenziert
        html_ohne_logo_ref = re.sub(r'<img[^>]*src\s*=\s*["\']cid:logo["\'][^>]*>', '', html_content, flags=re.IGNORECASE)
        html_part = MIMEText(html_ohne_logo_ref, 'html', 'utf-8')
    else: # Kein Logo-Pfad und kein Platzhalter im HTML
        html_part = MIMEText(html_content, 'html', 'utf-8')

    msg_alternative.attach(html_part)

    # Füge das Logo hinzu, falls ein Pfad angegeben wurde und die Datei existiert
    if logo_pfad_content:
        logo_file = Path(logo_pfad_content)
        if logo_file.is_file():
            try:
                with open(logo_file, 'rb') as fp:
                    img = MIMEImage(fp.read(), name=logo_file.name)
                img.add_header('Content-ID', f'<{logo_cid}>')
                img.add_header('Content-Disposition', 'inline', filename=logo_file.name)
                msg.attach(img)
            except FileNotFoundError:
                print(f"Warnung: Logo-Datei nicht gefunden unter {logo_pfad_content} (trotz vorheriger Prüfung).")
            except Exception as e:  # pylint: disable=W0718
                print(f"Fehler beim Einbetten des Logos '{logo_pfad_content}': {e}.")
        else:
            print(f"Warnung: Logo-Datei nicht gefunden unter {logo_pfad_content}.")

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_sender, empfaenger_email, msg.as_string())
        print(f"E-Mail erfolgreich an {empfaenger_email} gesendet!")
        return True
    except smtplib.SMTPAuthenticationError:
        print(f"SMTP Authentifizierungsfehler für Benutzer {smtp_user}. Überprüfe Anmeldedaten.")
    except smtplib.SMTPServerDisconnected:
        print("Die Verbindung zum SMTP-Server wurde unerwartet getrennt.")
    except smtplib.SMTPConnectError as e:
        print(f"Fehler beim Verbinden mit dem SMTP-Server {smtp_host}:{smtp_port}. Fehler: {e}")
    except smtplib.SMTPHeloError as e:
        print(f"Der Server hat auf HELO/EHLO nicht korrekt geantwortet: {e}")
    except smtplib.SMTPRecipientsRefused as e:
        print(f"Alle Empfänger wurden abgelehnt: {e.recipients}")
    except smtplib.SMTPSenderRefused as e:
        print(f"Die Absenderadresse wurde abgelehnt: {e.sender}")
    except smtplib.SMTPDataError as e:
        print(f"Der Server hat die Nachrichtendaten nicht akzeptiert: {e.smtp_code} - {e.smtp_error}")
    except ConnectionRefusedError:
        print(f"Verbindung zu {smtp_host}:{smtp_port} wurde abgelehnt. Läuft der Server und ist der Port korrekt?")
    except Exception as e:  # pylint: disable=W0718
        print(f"Ein unerwarteter Fehler ist beim E-Mail-Versand aufgetreten: {e}")
        print("Traceback:")
        traceback.print_exc()
    return False
