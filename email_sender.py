"""Versendet schön formatierte HTML-Mails mit einem optionalen Logo und Text-Fallback."""

import logging
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def _validate_smtp_config(smtp_cfg: Dict[str, Any]) -> bool:
    """Prüft die SMTP-Konfiguration auf Vollständigkeit und korrekten Port-Typ."""

    required_keys = ['host', 'port', 'user', 'password', 'sender']
    if not all(key in smtp_cfg and smtp_cfg[key] is not None for key in required_keys):
        logger.error("Unvollständige SMTP-Konfiguration. Benötigt: %s.", ", ".join(required_keys))
        return False
    try:
        int(smtp_cfg['port']) # Prüft, ob Port eine Zahl ist
    except ValueError:
        logger.error("SMTP-Port '%s' ist keine gültige Zahl.", smtp_cfg.get('port'))
        return False
    return True

def _prepare_html_with_logo(html_content: str, logo_pfad_content: Optional[str], logo_cid: str) -> str:
    """Bereitet den HTML-Inhalt vor, ersetzt ggf. Logo-CID oder entfernt Logo-Referenz."""

    html_to_send = html_content
    if logo_pfad_content and Path(logo_pfad_content).is_file():
        html_to_send = html_to_send.replace('cid:logo', f'cid:{logo_cid}')
    elif 'cid:logo' in html_to_send:
        logger.warning("Logo-Platzhalter 'cid:logo' im HTML gefunden, aber kein gültiger logo_pfad ('%s') oder Datei nicht gefunden. Logo-Referenz wird entfernt.", logo_pfad_content)
        html_to_send = re.sub(r'<img[^>]*src\s*=\s*["\']cid:logo["\'][^>]*>', '', html_content, flags=re.IGNORECASE)
    return html_to_send

def _create_mime_message(empfaenger_email: str, betreff: str, content: Dict[str, Any]) -> MIMEMultipart:
    """Erstellt das MIMEMultipart-Objekt mit Text, HTML und optionalem Logo."""

    msg = MIMEMultipart('related')
    msg['From'] = content['smtp_sender_for_header']
    msg['To'] = empfaenger_email
    msg['Subject'] = betreff

    msg_alternative = MIMEMultipart('alternative')
    msg.attach(msg_alternative)

    text_part = MIMEText(content.get('text', ''), 'plain', 'utf-8')
    msg_alternative.attach(text_part)

    logo_cid = 'logoimage_cid_01'
    logo_pfad_content = content.get('logo_pfad')

    html_final_content = _prepare_html_with_logo(content.get('html', ''), logo_pfad_content, logo_cid)
    html_part = MIMEText(html_final_content, 'html', 'utf-8')
    msg_alternative.attach(html_part)

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
                logger.warning("Logo-Datei nicht gefunden unter %s (trotz vorheriger Prüfung).", logo_pfad_content)
            except Exception as e: # pylint: disable=W0718
                logger.error("Fehler beim Einbetten des Logos '%s': %s.", logo_pfad_content, e, exc_info=True)
        else:
            pass
    return msg

def _send_email_via_smtp(msg: MIMEMultipart, smtp_cfg: Dict[str, Any], empfaenger_email: str) -> bool:
    """Stellt die SMTP-Verbindung her und sendet die vorbereitete E-Mail."""

    try:
        with smtplib.SMTP(smtp_cfg['host'], int(smtp_cfg['port'])) as server:
            server.starttls()
            server.login(smtp_cfg['user'], smtp_cfg['password'])
            server.sendmail(smtp_cfg['sender'], empfaenger_email, msg.as_string())
        # logger.info("E-Mail erfolgreich an %s gesendet!", empfaenger_email)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP Authentifizierungsfehler für Benutzer %s. Überprüfe Anmeldedaten.", smtp_cfg.get('user'))
    except smtplib.SMTPServerDisconnected:
        logger.error("Die Verbindung zum SMTP-Server wurde unerwartet getrennt.")
    except smtplib.SMTPConnectError as e:
        logger.error("Fehler beim Verbinden mit dem SMTP-Server %s:%s. Fehler: %s", smtp_cfg.get('host'), smtp_cfg.get('port'), e)
    except smtplib.SMTPHeloError as e:
        logger.error("Der Server hat auf HELO/EHLO nicht korrekt geantwortet: %s", e)
    except smtplib.SMTPRecipientsRefused as e:
        logger.error("Alle Empfänger wurden abgelehnt: %s", e.recipients) # type: ignore
    except smtplib.SMTPSenderRefused as e:
        logger.error("Die Absenderadresse wurde abgelehnt: %s", e.sender)
    except smtplib.SMTPDataError as e:
        logger.error("Der Server hat die Nachrichtendaten nicht akzeptiert: %s - %s", e.smtp_code, e.smtp_error)
    except ConnectionRefusedError:
        logger.error("Verbindung zu %s:%s wurde abgelehnt. Läuft der Server und ist der Port korrekt?", smtp_cfg.get('host'), smtp_cfg.get('port'))
    except Exception as e: # pylint: disable=W0718
        logger.error("Ein unerwarteter Fehler ist beim E-Mail-Versand aufgetreten: %s", e, exc_info=True)
    return False

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

    if not _validate_smtp_config(smtp_cfg):
        return False

    content_with_sender = content.copy()
    content_with_sender['smtp_sender_for_header'] = smtp_cfg['sender']

    msg = _create_mime_message(empfaenger_email, betreff, content_with_sender)

    return _send_email_via_smtp(msg, smtp_cfg, empfaenger_email)
