"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

# Logging zuerst aktivieren
import sys
import logging
import binascii
import functools
import json
import os
import io
import random
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
import qrcode
import qrcode.constants
from qrcode.image.pil import PilImage
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file  # pigar: required-packages=uWSGI
from jinja2 import TemplateError
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error, IntegrityError
import config
import email_sender
import db_utils

logging.basicConfig(
    level=config.gui_config['log_level'],
    format='%(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

if config.gui_config['static_url_prefix']:
    app = Flask(__name__, static_url_path=config.gui_config['static_url_prefix'] + '/static')
else:
    app = Flask(__name__)

app.debug = config.gui_config['flask_debug_mode']

app.config['SECRET_KEY'] = config.gui_config.get('secret_key')
if not app.config['SECRET_KEY']:
    logger.critical("Fehler: APP_SECRET ist in der Konfiguration (.env) nicht gesetzt!")
    sys.exit(1)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['DEBUG'] = config.api_config['flask_debug_mode']
app.config['JSON_AS_ASCII'] = False

if "BASE_URL" in os.environ:
    BASE_URL = os.environ.get('BASE_URL', '/')
    logger.info("BASE_URL: %s", BASE_URL)
else:
    BASE_URL = ""  # pylint: disable=C0103

# Konfigurationsprüfungen
required_db_keys = ['host', 'port', 'user', 'password', 'database']
if not all(key in config.db_config and config.db_config[key] is not None for key in required_db_keys):
    logger.critical("Fehler: Nicht alle Datenbank-Konfigurationsvariablen sind gesetzt. Benötigt: %s", ", ".join(required_db_keys))
    sys.exit(1)

try:
    config.db_config['port'] = int(config.db_config['port'])
except ValueError:
    logger.critical("Fehler: Datenbank-Port '%s' ist keine gültige Zahl.", config.db_config.get('port'))
    sys.exit(1)

# Initialisiere den Datenbank-Pool einmal beim Start der Anwendung # pylint: disable=R0801
try:
    db_utils.DatabaseConnectionPool.initialize_pool(config.db_config)
except Error:
    logger.critical("Fehler beim Starten der Datenbankverbindung.")
    sys.exit(1)

# Starte den Health-Check-Thread, nachdem der Pool initialisiert wurde
#db_utils.DatabaseConnectionPool.start_health_check_thread()

# Lade das Manifest mit Author- und Versionsinfos
try:
    with open('manifest.json', 'r', encoding='utf-8') as manifest:
        app.config.update(json.load(manifest))
except FileNotFoundError:
    app.config.update(version="N/A", author="N/A")

logger.info("Feuerwehr-Versorgungs-Helfer GUI (Version %s) wurde gestartet", app.config.get('version'))


def generate_api_key_string(length=32):
    """
    Generiert einen sicheren, zufälligen API-Key-String.
    """

    return secrets.token_hex(length)


def hex_to_binary(hex_string):
    """
    Konvertiert einen Hexadezimalstring in Binärdaten.

    Diese Funktion nimmt einen Hexadezimalstring entgegen und wandelt ihn in die entsprechende
    Binärdarstellung um. Sie wird typischerweise verwendet, um NFC-Token Daten zu verarbeiten,
    die oft als Hexadezimalstrings dargestellt werden.

    Args:
        hex_string (str): Der Hexadezimalstring, der konvertiert werden soll.

    Returns:
        bytes: Die Binärdaten, die dem Hexadezimalstring entsprechen. Gibt None zurück,
               wenn die Konvertierung aufgrund eines ungültigen Hexadezimalstrings oder Typs fehlschlägt.
    """

    try:
        return binascii.unhexlify(hex_string)
    except binascii.Error:
        logger.error("Fehler bei der Hexadezimal-Konvertierung: Ungültiger Hexadezimalstring '%s'", hex_string)
        return None
    except TypeError:
        logger.error("Fehler bei der Hexadezimal-Konvertierung: Ungültiger Typ für Hexadezimalstring: %s", type(hex_string))
        return None


def erzeuge_qr_code(daten, text):
    """
    Erzeugt einen QR-Code mit zusätzlichem Infotext als PNG-Datei.

    Args:
        daten (str): Die zu codierenden Daten, hier unser User-Code.
        text (str): Wird als zusätzlicher Text unterhalb des QR-Codes hinzugefügt.

    Returns:
        ImageDraw: Bilddaten
    """

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(daten)
    qr.make(fit=True)

    img = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white").convert("RGBA")

    qr_breite, qr_hoehe = img.size
    text_farbe = "black"
    hintergrund_farbe = "white"
    text_abstand_unten = 40
    schriftgroesse = 22
    font_names = ["Hack-Bold.ttf", "DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf"]
    schriftart = None

    for font_name in font_names:
        try:
            schriftart = ImageFont.truetype(font_name, schriftgroesse)
            logger.info("Schriftart '%s' geladen.", font_name)
            break
        except IOError:
            logger.error("Schriftart '%s' nicht gefunden.", font_name)

    if schriftart is None:
        logger.error("Keine der bevorzugten Schriftarten gefunden. Lade Standardschriftart.")
        schriftart = ImageFont.load_default(size=schriftgroesse)

    zeichne_temp = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # textbbox((0,0)...) gibt (x1, y1, x2, y2) relativ zum Ankerpunkt (0,0)
    # Standardanker für textbbox ist 'la' (left-ascent), d.h. (0,0) ist links auf der Grundlinie.
    # text_box[1] ist der y-Wert des höchsten Pixels (negativ für Aufstrich).
    # text_box[3] ist der y-Wert des tiefsten Pixels (positiv für Abstriche).
    text_box = zeichne_temp.textbbox((0, 0), text, font=schriftart)
    text_breite_val = text_box[2] - text_box[0]
    text_hoehe_val = text_box[3] - text_box[1]  # Gesamthöhe des Textes

    tatsaechliche_gesamthoehe_textbereich = max(text_abstand_unten, text_hoehe_val)

    # Berechne den Abstand über dem Text, um ihn im tatsaechliche_gesamthoehe_textbereich zu zentrieren.
    # Wenn tatsaechliche_gesamthoehe_textbereich == text_hoehe_val, ist dieser Abstand 0.
    abstand_ueber_text = (tatsaechliche_gesamthoehe_textbereich - text_hoehe_val) // 15

    # Neue Gesamthöhe des Bildes
    neue_bild_hoehe = qr_hoehe + tatsaechliche_gesamthoehe_textbereich

    # Neues Bild erstellen
    neues_bild = Image.new("RGBA", (qr_breite, neue_bild_hoehe), hintergrund_farbe)
    neues_bild.paste(img, (0, 0))  # QR-Code auf das neue Bild kopieren

    # Text auf das neue Bild zeichnen
    zeichne_neu = ImageDraw.Draw(neues_bild)

    text_x = (qr_breite - text_breite_val) // 2
    # text_y ist die y-Koordinate für die Oberkante des Textes.
    # Die text() Funktion von Pillow (ohne expliziten Anker) erwartet die obere linke Ecke.
    text_y = qr_hoehe + abstand_ueber_text

    zeichne_neu.text((text_x, text_y), text, fill=text_farbe, font=schriftart)

    return neues_bild


# Benachrichtigungseinstellungen
def get_all_notification_types():
    """
    Ruft alle verfügbaren Benachrichtigungstypen aus der Datenbank ab.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benachrichtigungstyp
              repräsentiert (enthält 'id', 'event_schluessel', 'beschreibung').
              Gibt eine leere Liste zurück, falls ein Fehler auftritt oder keine Typen vorhanden sind.
    """

    query = "SELECT id, event_schluessel, beschreibung FROM benachrichtigungstypen ORDER BY id"
    return db_utils.fetch_all(query, dictionary=True)


def get_user_notification_preference(user_id_int: int, event_schluessel: str) -> bool:
    """
    Prüft, ob ein Benutzer eine bestimmte E-Mail-Benachrichtigung aktiviert hat.

    Args:
        user_id_int (int): Die ID des Benutzers.
        event_schluessel (str): Der eindeutige Schlüssel des Benachrichtigungstyps
                                (z.B. 'NEUE_TRANSAKTION').

    Returns:
        bool: True, wenn die Benachrichtigung für den Benutzer aktiviert ist, sonst False.
    """

    query = """
        SELECT bba.email_aktiviert
        FROM benutzer_benachrichtigungseinstellungen bba
        JOIN benachrichtigungstypen bt ON bba.typ_id = bt.id
        WHERE bba.benutzer_id = %s AND bt.event_schluessel = %s
    """
    row = db_utils.fetch_one(query, (user_id_int, event_schluessel), dictionary=True)
    try:
        return bool(row['email_aktiviert']) if row and row.get('email_aktiviert') is not None else False
    except (KeyError, TypeError):
        return False


def get_user_notification_settings(user_id):
    """
    Ruft die aktuellen E-Mail-Benachrichtigungseinstellungen für einen bestimmten Benutzer ab.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary, das die Einstellungen des Benutzers abbildet.
              Der Schlüssel ist die 'typ_id' (ID des Benachrichtigungstyps) und
              der Wert ist ein Boolean, der angibt, ob E-Mail-Benachrichtigungen für diesen Typ
              aktiviert ('True') oder deaktiviert ('False') sind.
              Gibt ein leeres Dictionary zurück, wenn keine Einstellungen gefunden werden oder ein Fehler auftritt.
    """

    # Hole alle Typen
    all_types = db_utils.fetch_all("SELECT id FROM benachrichtigungstypen", dictionary=True)
    type_ids = [int(row['id']) for row in all_types] if all_types else []

    # Hole die Einstellungen des Benutzers
    query = "SELECT typ_id, email_aktiviert FROM benutzer_benachrichtigungseinstellungen WHERE benutzer_id = %s"
    rows = db_utils.fetch_all(query, (user_id,), dictionary=True)
    settings = {int(row['typ_id']): bool(row['email_aktiviert']) for row in rows} if rows else {}

    # Setze Default False für nicht gesetzte Typen
    for tid in type_ids:
        if tid not in settings:
            settings[tid] = False
    return settings


def update_user_notification_settings(user_id, active_notification_type_ids_int):
    """
    Aktualisiert die E-Mail-Benachrichtigungseinstellungen für einen Benutzer.

    Diese Funktion setzt die Einstellungen für alle verfügbaren Benachrichtigungstypen.
    Typen, deren IDs in `active_notification_type_ids_int` enthalten sind, werden als
    aktiviert (email_aktiviert = 1) markiert. Alle anderen bekannten Typen werden
    für diesen Benutzer deaktiviert (email_aktiviert = 0).
    Verwendet `INSERT ... ON DUPLICATE KEY UPDATE`, um Einträge zu erstellen oder zu aktualisieren.

    Args:
        user_id (int): Die ID des Benutzers, dessen Einstellungen aktualisiert werden sollen.
        active_notification_type_ids_int (list): Eine Liste von Integer-IDs der Benachrichtigungstypen,
                                                   die für den Benutzer aktiviert werden sollen.

    Returns:
        bool: True bei Erfolg, False bei einem Fehler.
    """

    # Hole alle verfügbaren Typ-IDs
    all_types = db_utils.fetch_all("SELECT id FROM benachrichtigungstypen", dictionary=False)
    if all_types is None:
        flash("Fehler beim Laden der Benachrichtigungstypen.", "error")
        return False
    try:
        for row in all_types:
            type_id = row[0]
            is_enabled = 1 if type_id in active_notification_type_ids_int else 0
            query = """
                INSERT INTO benutzer_benachrichtigungseinstellungen (benutzer_id, typ_id, email_aktiviert)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE email_aktiviert = VALUES(email_aktiviert)
            """
            result = db_utils.execute_commit(query, (user_id, type_id, is_enabled))
            success = result[0] if result else False
            if not success:
                raise Error("DB-Fehler beim Setzen der Benachrichtigungseinstellung")
        return True
    except Error as err:
        logger.error("Fehler beim Aktualisieren der Benutzereinstellungen für Benachrichtigungen: %s", err)
        flash("Fehler beim Speichern der Benachrichtigungseinstellungen.", "error")
        return False


# Systemeinstellungen (Admin)
def get_all_system_settings():
    """
    Ruft alle Systemeinstellungen aus der Datenbank ab.

    Returns:
        dict: Ein Dictionary, wobei der Schlüssel der 'einstellung_schluessel' ist
              und der Wert ein weiteres Dictionary mit 'wert' und 'beschreibung' der Einstellung ist.
              Gibt ein leeres Dictionary zurück bei Fehlern oder wenn keine Einstellungen vorhanden sind.
    """

    query = "SELECT einstellung_schluessel, einstellung_wert, beschreibung FROM system_einstellungen"
    rows = db_utils.fetch_all(query, dictionary=True)
    settings = {row['einstellung_schluessel']: {'wert': row['einstellung_wert'], 'beschreibung': row['beschreibung']} for row in rows} if rows else {}
    return settings


def update_system_setting(einstellung_schluessel, einstellung_wert):
    """
    Aktualisiert den Wert einer spezifischen Systemeinstellung in der Datenbank.

    Args:
        einstellung_schluessel (str): Der Schlüssel der zu aktualisierenden Einstellung.
        einstellung_wert (str): Der neue Wert für die Einstellung.

    Returns:
        bool: True, wenn die Aktualisierung erfolgreich war (mindestens eine Zeile betroffen),
              False andernfalls (z.B. bei Datenbankfehlern oder wenn der Schlüssel nicht existiert).
    """

    query = "UPDATE system_einstellungen SET einstellung_wert = %s WHERE einstellung_schluessel = %s"
    result = db_utils.execute_commit(query, (einstellung_wert, einstellung_schluessel))
    success = result[0] if result else False
    if not success:
        flash(f"Datenbankfehler beim Speichern der Einstellung '{einstellung_schluessel}'.", "error")
    return success


# NFC-Token Handling
def add_user_nfc_token(user_id, token_name, token_hex):
    """
    Fügt einen neuen NFC-Token der Datenbank hinzu.

    Args:
        user_id (int): Die ID des Benutzers.
        token_name (str): Der Name des Tokens.
        token_hex (str): Die Hexadezimaldarstellung der NFC-Token Daten.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. ungültige Daten, Datenbankfehler).
    """

    token_binary = hex_to_binary(token_hex)
    if not token_binary:
        flash('Ungültige NFC-Token Daten. Bitte überprüfe die Eingabe.', 'error')
        return False
    query = "INSERT INTO nfc_token SET user_id = %s, token_name = %s, token_daten = %s, last_used = NOW()"
    try:
        result = db_utils.execute_commit(query, (user_id, token_name, token_binary))
        success = result[0] if result else False
        if success:
            return True
        flash('Fehler beim Hinzufügen des NFC-Tokens.', 'error')
        return False
    except IntegrityError as err:
        if err.errno == 1062:
            logger.warning("Versuch, einen doppelten NFC-Token hinzuzufügen: %s", token_hex)
            flash('Dieser NFC-Token ist bereits vorhanden und kann nicht erneut hinzugefügt werden.', 'error')
        else:
            logger.error("Datenbank-Integritätsfehler beim Hinzufügen des NFC-Tokens: %s", err)
            flash(f"Ein Datenbank-Integritätsfehler ist aufgetreten: {err}", "error")
        return False
    except Error as err:
        logger.error("Fehler beim Hinzufügen des NFC-Tokens: %s", err)
        flash("Ein unerwarteter Datenbankfehler ist aufgetreten.", "error")
        return False


def delete_user_nfc_token(user_id, token_id):
    """
    Entfernt einen NFC-Token aus der Datenbank.

    Args:
        user_id (int): Die ID des Benutzers.
        token_id (int): Die des zu entfernenen Tokens.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. ungültige ID, Datenbankfehler).
    """

    if not token_id:
        flash('Ungültige NFC-Token Daten. Bitte überprüfe die Eingabe.', 'error')
        return False
    query = "DELETE FROM nfc_token WHERE token_id = %s AND user_id = %s"
    result = db_utils.execute_commit(query, (token_id, user_id))
    success = result[0] if result else False
    if success:
        return True
    flash('Fehler beim Entfernen des NFC-Tokens.', 'error')
    return False


def get_user_nfc_tokens(user_id):
    """
    Ruft alle Tokens eines Benutzer ab, absteigend sortiert nach dem Zeitpunkt der letzten Verwendung.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Token repräsentiert
              (token_id, token_name, token_daten, last_used, last_used_days_ago).
              Gibt None zurück, falls ein Fehler auftritt.
    """

    query = """
        SELECT token_id, token_name, token_daten as token_daten, last_used, DATEDIFF(CURDATE(), DATE(last_used)) AS last_used_days_ago
        FROM nfc_token WHERE user_id = %s ORDER BY last_used DESC
    """
    try:
        return db_utils.fetch_all(query, (user_id,), dictionary=True)
    except Error as err:
        logger.error("Datenbankfehler beim Abrufen der Benutzer NFC Tokens: %s", err)
        return None


def _handle_add_user_nfc_token_admin(form_data, target_user_id):
    """
    Verarbeitet das Hinzufügen eines NFC-Tokens für einen Benutzer durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, für den der Token hinzugefügt wird.
    """

    nfc_token_name = form_data.get('nfc_token_name')
    nfc_token_daten = form_data.get('nfc_token_daten')  # HEX Format erwartet
    if not nfc_token_name or not nfc_token_daten:
        flash('Token Name und Token Daten (HEX) dürfen nicht leer sein.', 'error')
    # Die Funktion add_user_nfc_token flasht bereits Fehlermeldungen bei ungültigen Daten
    elif add_user_nfc_token(target_user_id, nfc_token_name, nfc_token_daten):
        flash('NFC-Token erfolgreich hinzugefügt.', 'success')


def _handle_delete_user_nfc_token_admin(form_data, target_user_id):
    """
    Verarbeitet das Löschen eines NFC-Tokens eines Benutzers durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, dessen Token gelöscht wird.
                               (Wird in delete_user_nfc_token zur Sicherheit mitgeprüft)
    """

    nfc_token_id = form_data.get('nfc_token_id')
    if not nfc_token_id:
        flash('Keine Token ID zum Löschen übergeben.', 'error')
    # Die Funktion delete_user_nfc_token flasht bereits Fehlermeldungen
    elif delete_user_nfc_token(target_user_id, nfc_token_id):
        flash('NFC-Token erfolgreich entfernt.', 'success')


# Benutzerfunktionen
def delete_user(user_id):
    """
    Löscht einen Benutzer anhand seiner ID.
    """
    query = "DELETE FROM users WHERE id = %s"
    result = db_utils.execute_commit(query, (user_id,))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Löschen des Benutzers (ID: %s)", user_id)
    return success


def toggle_user_admin(user_id, admin_state):
    """
    Macht einen Benutzer zum Admin (oder umgekehrt).
    """
    query = "UPDATE users SET is_admin = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (admin_state, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Ändern des Admin-Status für Benutzer %s", user_id)
    return success


def toggle_user_lock(user_id, lock_state):
    """
    Sperrt einen Benutzer anhand seiner ID oder entsperrt ihn.
    """
    query = "UPDATE users SET is_locked = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (lock_state, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Sperren/Entsperren des Benutzers %s", user_id)
    return success


def update_user_comment(user_id, comment):
    """
    Ändert den Kommentar eines Benutzer anhand seiner ID.
    """
    query = "UPDATE users SET kommentar = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (comment, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Aktualisieren des Kommentars für Benutzer %s", user_id)
    return success


def update_user_infomail_responsible_threshold(user_id, infomail_responsible_threshold):
    """
    Ändert die Infomail-Verantwortlichen-Schwelle eines Benutzer anhand seiner ID.
    """
    query = "UPDATE users SET infomail_responsible_threshold = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (infomail_responsible_threshold, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Aktualisieren der Infomail-Verantwortlichen-Schwelle für Benutzer %s", user_id)
    return success


def update_user_infomail_user_threshold(user_id, infomail_user_threshold):
    """
    Ändert die Infomail-User-Schwelle eines Benutzer anhand seiner ID.
    """
    query = "UPDATE users SET infomail_user_threshold = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (infomail_user_threshold, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Aktualisieren der Infomail-User-Schwelle für Benutzer %s", user_id)
    return success


def update_user_email(user_id, email):
    """
    Ändert die Emailadresse eines Benutzer anhand seiner ID.
    """
    query = "UPDATE users SET email = %s WHERE id = %s"
    result = db_utils.execute_commit(query, (email, user_id))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Aktualisieren der E-Mail-Adresse für Benutzer %s", user_id)
    return success


def fetch_user(code_or_email):
    """
    Ruft einen Benutzer aus der Datenbank anhand seines Codes oder seiner Emailadresse ab.

    Args:
        code (str): Der eindeutige Code des Benutzers oder seine Emailadresse

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, password, infomail_user_threshold, infomail_responsible_threshold, is_admin, is_locked)
              oder None, falls kein Benutzer gefunden wird.
    """

    query = "SELECT id, code, nachname, vorname, password, infomail_user_threshold, infomail_responsible_threshold, is_admin, is_locked FROM users WHERE code = %s OR email = %s"
    try:
        return db_utils.fetch_one(query, (code_or_email, code_or_email), dictionary=True)
    except Error as err:
        logger.error("Datenbankfehler beim Abrufen des Benutzers: %s", err)
        return None


def get_user_by_id(user_id):
    """
    Ruft einen Benutzer anhand seiner ID ab.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, email, kommentar, infomail_user_threshold, infomail_responsible_threshold, is_locked, is_admin, password)
              oder None, falls kein Benutzer gefunden wird.
    """

    query = "SELECT id, code, nachname, vorname, email, kommentar, infomail_user_threshold, infomail_responsible_threshold, is_locked, is_admin, password FROM users WHERE id = %s"
    try:
        return db_utils.fetch_one(query, (user_id,), dictionary=True)
    except Error as err:
        logger.error("Datenbankfehler beim Abrufen des Benutzers: %s", err)
        return None


def get_saldo_for_user(user_id):
    """
    Berechnet das Saldo für den Benutzer mit der übergebenen user_id.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        int: Das Saldo oder 0, falls kein Benutzer gefunden wird oder keine Transaktionen vorhanden sind.
    """

    query = "SELECT SUM(saldo_aenderung) FROM transactions WHERE user_id = %s"
    try:
        result = db_utils.fetch_one(query, (user_id,), dictionary=False)
        return result[0] if result and result[0] is not None else 0
    except Error as err:
        logger.error("Datenbankfehler beim Berechnen des Saldos: %s", err)
        return 0


def get_saldo_by_user():
    """
    Berechnet das Saldo für jeden Benutzer.

    Returns:
        dict: Ein Dictionary, wobei der Schlüssel die Benutzer-ID und der Wert das Saldo ist.
              Enthält alle Benutzer, auch solche ohne Transaktionen (Wert dann 0).
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT u.id, SUM(t.saldo_aenderung) AS saldo
                FROM users u
                LEFT JOIN transactions t ON u.id = t.user_id
                GROUP BY u.id
            """
            cursor.execute(query)
            saldo_by_user = {row['id']: row['saldo'] or 0 for row in cursor.fetchall()}
            return saldo_by_user
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen des Saldos pro Benutzer: %s", err)
            return {}
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return {}


def get_all_users():
    """
    Ruft alle Benutzer aus der Datenbank ab, sortiert nach Namen.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benutzer repräsentiert
              (id, code, nachname, vorname, email, kommentar, is_locked, is_admin).
              Gibt eine leere Liste zurück, falls ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, nachname, vorname, email, kommentar, is_locked, is_admin
                FROM users
                ORDER BY nachname, vorname
            """
            cursor.execute(query)
            users = cursor.fetchall()
            return users
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen aller Benutzer: %s", err)
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []


def get_all_api_users():
    """
    Ruft alle API-Benutzer aus der Datenbank ab, sortiert nach Username.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen API-Benutzer repräsentiert
              (id, username). Gibt eine leere Liste zurück, falls ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, username FROM api_users ORDER BY username"
            cursor.execute(query)
            api_users = cursor.fetchall()
            return api_users
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen aller API-Benutzer: %s", err)
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []


def get_api_user_by_id(api_user_id):
    """
    Ruft einen API-Benutzer anhand seiner ID ab.

    Args:
        api_user_id (int): Die ID des API-Benutzers.

    Returns:
        dict: Ein Dictionary mit den API-Benutzerdaten (id, username)
              oder None, falls kein API-Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, username FROM api_users WHERE id = %s"
            cursor.execute(query, (api_user_id,))
            api_user = cursor.fetchone()
            return api_user
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen des API-Benutzers: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def get_api_keys_for_api_user(api_user_id):
    """
    Ruft alle API-Keys für einen bestimmten API-Benutzer ab.

    Args:
        api_user_id (int): Die ID des API-Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen API-Key repräsentiert
              (id, api_key_name, api_key). Gibt eine leere Liste zurück, falls keine Keys gefunden werden oder ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, api_key_name, api_key FROM api_keys WHERE user_id = %s ORDER BY id"
            cursor.execute(query, (api_user_id,))
            keys = cursor.fetchall()
            return keys
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der API-Keys für API-Benutzer %s: %s", api_user_id, err)
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []


def get_user_transactions(user_id):
    """
    Ruft alle Transaktionen für einen bestimmten Benutzer ab, sortiert nach Zeitstempel (neueste zuerst).

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary eine Transaktion repräsentiert
              (id, beschreibung, saldo_aenderung, timestamp). Gibt None zurück, falls ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, beschreibung, saldo_aenderung, timestamp FROM transactions WHERE user_id = %s ORDER BY timestamp DESC"
            cursor.execute(query, (user_id,))
            transactions = cursor.fetchall()
            return transactions
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der Benutzertransaktionen: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def add_transaction(user_id, beschreibung, saldo_aenderung):
    """
    Fügt eine neue Transaktion für einen Benutzer hinzu.

    Args:
        user_id (int): Die ID des Benutzers.
        beschreibung (str): Die Beschreibung der Transaktion.
        saldo_aenderung (int): Die Änderung im Saldo der Transaktion.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)"
            cursor.execute(query, (user_id, beschreibung, saldo_aenderung))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Hinzufügen der Transaktion: %s", err)
            flash(f"Datenbankfehler beim Hinzufügen der Transaktion: {err}", "error")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def delete_all_transactions(user_id):
    """
    Löscht alle Transaktionen eines Benutzers.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM transactions WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Löschen der Transaktionen: %s", err)
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def get_recent_transactions(limit=10):
    """
    Ruft die neuesten Transaktionen mit optionalen Benutzerinformationen ab.

    Args:
        limit (int): Maximale Anzahl der zurückzugebenden Transaktionen.

    Returns:
        list: Liste von Dictionaries mit Feldern wie id, user_id, nachname, vorname, beschreibung, saldo_aenderung, timestamp.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = (
                "SELECT t.id, t.user_id, u.nachname AS nachname, u.vorname AS vorname, "
                "t.beschreibung, t.saldo_aenderung, t.timestamp "
                "FROM transactions t LEFT JOIN users u ON t.user_id = u.id "
                "ORDER BY t.timestamp DESC LIMIT %s"
            )
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()

            # Format timestamps for display
            for row in rows or []:
                ts = row.get('timestamp')
                try:
                    if ts:
                        row['timestamp_display'] = ts.strftime('%d.%m.%Y %H:%M')
                    else:
                        row['timestamp_display'] = ''
                except (AttributeError, ValueError):
                    # Fallback: use str()
                    row['timestamp_display'] = str(ts) if ts is not None else ''
            return rows if rows else []
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der neuesten Transaktionen: %s", err)
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []


def update_password(user_id, new_password_hash):
    """
    Aktualisiert das Passwort eines Benutzers in der Datenbank.

    Args:
        user_id (int): Die ID des Benutzers.
        new_password_hash (str): Der Hash des neuen Passworts.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "UPDATE users SET password = %s WHERE id = %s"
            cursor.execute(query, (new_password_hash, user_id))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Aktualisieren des Passworts: %s", err)
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def add_regular_user_db(user_data):
    """
    Fügt einen neuen regulären Benutzer der Datenbank hinzu.

    Args:
        user_data (dict): Ein Dictionary mit den Benutzerdaten:
            'code' (str): Eindeutiger Code des Benutzers.
            'nachname' (str): Nachname des Benutzers.
            'vorname' (str): Vorname des Benutzers.
            'password' (str): Passwort des Benutzers (Klartext, wird hier gehasht).
            'email' (str, optional): E-Mail-Adresse des Benutzers.
            'kommentar' (str, optional): Kommentar zum Benutzer.
            'acc_duties' (bool): Buchungs- und Mitwirkungspflicht akzeptiert.
            'acc_privacy_policy' (bool): Datenschutzerklärung wurde akzeptiert.
            'is_locked (bool): Benutzer ist gesperrt
            'is_admin' (bool): Gibt an, ob der Benutzer Admin-Rechte hat.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. Datenbankfehler, doppelter Code).
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        hashed_password = generate_password_hash(user_data['password'])
        try:
            query = """
                INSERT INTO users (code, nachname, vorname, password, email, kommentar, acc_duties, acc_privacy_policy, is_locked, is_admin)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                user_data['code'],
                user_data['nachname'],
                user_data['vorname'],
                hashed_password,
                user_data.get('email') or None,
                user_data.get('kommentar') or None,
                1 if user_data.get('acc_duties') else 0,
                1 if user_data.get('acc_privacy_policy') else 0,
                1 if user_data.get('is_locked') else 0,
                1 if user_data.get('is_admin') else 0
            ))
            cnx.commit()
            return True
        except IntegrityError:
            flash(f"Die Emailadresse '{user_data['email']}' existiert bereits oder ein anderes eindeutiges Feld ist doppelt.", 'error')
            cnx.rollback()
            return False
        except Error as err:
            logger.error("Fehler beim Hinzufügen des regulären Benutzers: %s", err)
            flash("Datenbankfehler beim Hinzufügen des Benutzers.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def get_user_by_email(email):
    """
    Ruft einen Benutzer anhand seiner E-Mail-Adresse ab.

    Args:
        email (str): Die E-Mail-Adresse des Benutzers.

    Returns:
        dict: Ein Dictionary mit Benutzerdaten oder None.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, code, nachname, vorname, email, is_locked FROM users WHERE email = %s"
            cursor.execute(query, (email,))
            return cursor.fetchone()
        except Error as err:
            logger.error("Datenbankfehler bei der Suche nach E-Mail: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def store_reset_token(user_id, token):
    """
    Speichert einen Passwort-Reset-Token in der Datenbank.

    Args:
        user_id (int): Die ID des Benutzers.
        token (str): Der sichere Token.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return False
    cursor = cnx.cursor()
    try:
        # Alte Tokens für diesen Benutzer löschen, um Missbrauch zu vermeiden
        cursor.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
        # Neuen Token mit 1 Stunde Gültigkeit einfügen
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        query = "INSERT INTO password_reset_tokens (user_id, token, expires_at) VALUES (%s, %s, %s)"
        cursor.execute(query, (user_id, token, expires_at))
        cnx.commit()
        return True
    except Error as err:
        logger.error("Fehler beim Speichern des Reset-Tokens: %s", err)
        cnx.rollback()
        return False
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


def get_user_by_reset_token(token):
    """
    Validiert einen Reset-Token und gibt den zugehörigen Benutzer zurück.

    Args:
        token (str): Der zu validierende Token.

    Returns:
        dict: Benutzerdaten, wenn der Token gültig und nicht abgelaufen ist, sonst None.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    cursor = cnx.cursor(dictionary=True)
    try:
        query = """
            SELECT u.* FROM users u
            JOIN password_reset_tokens prt ON u.id = prt.user_id
            WHERE prt.token = %s AND prt.expires_at > %s
        """
        cursor.execute(query, (token, datetime.now(timezone.utc)))
        return cursor.fetchone()
    except Error as err:
        logger.error("Fehler beim Validieren des Reset-Tokens: %s", err)
        return None
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


def delete_reset_token(token):
    """
    Löscht einen verwendeten Reset-Token.

    Args:
        token (str): Der zu löschende Token.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        logger.error("Konnte keine DB-Verbindung für delete_reset_token herstellen.")
        return False
    cursor = None
    try:
        cursor = cnx.cursor()
        query = "DELETE FROM password_reset_tokens WHERE token = %s"
        cursor.execute(query, (token,))
        cnx.commit()
        return True
    except db_utils.Error as err:
        logger.error("Fehler beim Löschen des Reset-Tokens: %s", err)
        cnx.rollback()
        return False
    finally:
        if cursor is not None:
            cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


# --- E-Mail Hilfsfunktion: Template-Rendering und Versand ---
def prepare_and_send_email(email_params: dict, smtp_cfg: dict) -> bool:
    """
    Rendert HTML- und Text-Templates, baut die E-Mail und versendet sie.
    Args:
        email_params (dict):
            - empfaenger_email (str)
            - betreff (str)
            - template_name_html (str)
            - template_name_text (str)
            - template_context (dict)
            - logo_dateipfad (str, optional)
        smtp_cfg (dict): SMTP-Konfiguration
    Returns:
        bool: True bei Erfolg, sonst False
    """
    empfaenger_email = email_params.get('empfaenger_email')
    betreff = email_params.get('betreff')
    template_name_html = email_params.get('template_name_html')
    template_name_text = email_params.get('template_name_text')
    template_context = email_params.get('template_context', {})
    logo_dateipfad_str = email_params.get('logo_dateipfad')

    # Defensive: Fallback auf leere Strings falls None
    if not isinstance(empfaenger_email, str):
        logger.error("empfaenger_email fehlt oder ist kein String")
        return False
    if not isinstance(betreff, str):
        logger.error("betreff fehlt oder ist kein String")
        return False
    if not isinstance(template_name_html, str):
        logger.error("template_name_html fehlt oder ist kein String")
        return False
    if not isinstance(template_name_text, str):
        logger.error("template_name_text fehlt oder ist kein String")
        return False

    # Render templates
    try:
        final_html_body = render_template(template_name_html, **template_context)
        final_text_body = render_template(template_name_text, **template_context)
    except TemplateError as err:
        logger.error("Fehler beim Rendern der E-Mail-Templates: %s", err)
        return False

    logo_exists = False
    if logo_dateipfad_str:
        logo_path_obj = Path(logo_dateipfad_str)
        if logo_path_obj.is_file():
            logo_exists = True
        else:
            logger.warning("Logo-Datei nicht gefunden unter: %s", logo_dateipfad_str)

    email_content_dict = {
        'html': final_html_body,
        'text': final_text_body,
        'logo_pfad': logo_dateipfad_str if logo_exists else None
    }

    return email_sender.sende_formatierte_email(
        empfaenger_email=empfaenger_email,
        betreff=betreff,
        content=email_content_dict,
        smtp_cfg=smtp_cfg
    )


def _send_user_register_email(vorname: str, email: str, code: str, logo_pfad: str):
    """Sendet eine Willkommens-E-Mail mit Verifizierungscode an neue Benutzer.

    Baut die E-Mail zusammen und ruft `prepare_and_send_email` für den
    Versand auf. Das Ergebnis wird geloggt.

    Args:
        vorname (str): Der Vorname des neuen Benutzers.
        email (str): Die E-Mail-Adresse des neuen Benutzers.
        code (int): Der Verifizierungscode für die Registrierung.
        logo_pfad (str): Der Dateipfad zum E-Mail-Logo.
    """

    email_params = {
        'empfaenger_email': email,
        'betreff': "Dein neuer Account auf Feuerwehr-Versorgungs-Helfer",
        'template_name_html': "email_user_register.html",
        'template_name_text': "email_user_register.txt",
        'template_context': {"vorname": vorname, "code": code},
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Neuer Benutzer Benachrichtigung an %s gesendet.", email)
    else:
        logger.error("Fehler beim Senden der Neuer Benutzer Benachrichtigung an %s.", email)


def _send_password_reset_email(email: str, token: str, logo_pfad: str):
    """Versendet eine E-Mail mit einem Link zum Zurücksetzen des Passworts.

    Der einzigartige Link wird aus dem Token generiert. Der Versandstatus
    wird geloggt.

    Args:
        email (str): Die E-Mail-Adresse des Benutzers.
        token (str): Das sichere Token zur Link-Generierung.
        logo_pfad (str): Der Dateipfad zum E-Mail-Logo.
    """

    reset_url = url_for('reset_with_token', token=token, _external=True)
    email_params = {
        'empfaenger_email': email,
        'betreff': "Passwort zurücksetzen für Feuerwehr-Versorgungs-Helfer",
        'template_name_html': "email_reset_password.html",
        'template_name_text': "email_reset_password.txt",
        'template_context': {"reset_url": reset_url},
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Passwort Reset Benachrichtigung an %s gesendet.", email)
    else:
        logger.error("Fehler beim Senden der Passwort Reset Benachrichtigung an %s.", email)


def _send_manual_transaction_email(target_user: dict, beschreibung: str, saldo_aenderung_str: str, new_saldo: str, logo_pfad: str):
    """Informiert einen Benutzer per E-Mail über eine manuelle Transaktion.

    Die E-Mail enthält Details zur Buchung. Das Ergebnis des Versands
    wird geloggt.

    Args:
        target_user (dict): Benutzer-Dictionary mit 'email' und 'vorname'.
        beschreibung (str): Beschreibung der Transaktion.
        saldo_aenderung_str (str): Die formatierte Änderung des Saldos.
        new_saldo (str): Der formatierte neue Saldo.
        logo_pfad (str): Der Dateipfad zum E-Mail-Logo.
    """

    jetzt = datetime.now()
    email_params = {
        'empfaenger_email': target_user['email'],
        'betreff': "Neue Transaktion auf deinem Konto",
        'template_name_html': "email_neue_transaktion.html",
        'template_name_text': "email_neue_transaktion.txt",
        'template_context': {
            "vorname": target_user['vorname'],
            "beschreibung_transaktion": beschreibung,
            "saldo_aenderung": saldo_aenderung_str,
            "neuer_saldo": new_saldo,
            "datum": jetzt.strftime("%d.%m.%Y"),
            "uhrzeit": jetzt.strftime("%H:%M")
        },
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Manuelle Transaktion Benachrichtigung an %s gesendet.", target_user['email'])
    else:
        logger.error("Fehler beim Senden der Manuelle Transaktion Benachrichtigung an %s.", target_user['email'])


def _send_responsible_benachrichtigung(target_user: dict, aktueller_saldo: int, logo_pfad: str):
    """Hilfsfunktion zur Information der Verantwortlichen wenn ein Benutzer das Limit unterschreitet."""

    # Breche ab, wenn der aktuelle Saldo gleich dem gesetzten Limit ist und gleichzeitig größer als das Limit -5
    if not (target_user['infomail_responsible_threshold'] - 5) < aktueller_saldo <= target_user['infomail_responsible_threshold']:
        return

    # Alle Prüfungen bestanden, E-Mail senden
    email_params = {
        'empfaenger_email': config.api_config['responsible_email'],
        'betreff': f"{target_user['vorname']} {target_user['nachname']} hat das Saldo-Info-Limit erreicht",
        'template_name_html': "email_info_responsible_threshold.html",
        'template_name_text': "email_info_responsible_threshold.txt",
        'template_context': {"vorname": target_user['vorname'], "nachname": target_user['nachname'],
                             "infomail_responsible_threshold": target_user['infomail_responsible_threshold'], 'app_name': config.app_name},
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Info über Saldo-Schwelle-erreicht (ID: %s) an Verantwortliche gesendet.", target_user['id'])
    else:
        logger.error("Fehler beim Senden der Saldo-Schwelle-erreicht-Info an ID: %s.", target_user['id'])


def add_api_user_db(username):
    """
    Fügt einen neuen API-Benutzer der Datenbank hinzu.

    Args:
        username (str): Eindeutiger Benutzername des API-Benutzers.

    Returns:
        int or None: Die ID des neu erstellten API-Benutzers bei Erfolg, sonst None.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO api_users (username) VALUES (%s)"
            cursor.execute(query, (username,))
            cnx.commit()
            new_id = cursor.lastrowid
            return new_id
        except db_utils.Error as err:
            logger.error("Fehler beim Hinzufügen des API-Benutzers: %s", err)
            flash("Datenbankfehler beim Hinzufügen des API-Benutzers.", 'error')
            cnx.rollback()
            return None
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def add_api_key_for_user_db(api_user_id, api_key_name_string, api_key_string):
    """
    Fügt einen neuen API-Key für einen API-Benutzer hinzu.

    Args:
        api_user_id (int): Die ID des API-Benutzers.
        api_key_name_string (str): Name des API-Keys.
        api_key_string (str): Der zu speichernde API-Key.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO api_keys (user_id, api_key_name, api_key) VALUES (%s, %s, %s)"
            cursor.execute(query, (api_user_id, api_key_name_string, api_key_string))
            cnx.commit()
            return True
        except db_utils.Error as err:
            logger.error("Fehler beim Hinzufügen des API-Keys: %s", err)
            flash("Datenbankfehler beim Hinzufügen des API-Keys.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def delete_api_key_db(api_key_id):
    """
    Löscht einen spezifischen API-Key anhand seiner ID.

    Args:
        api_key_id (int): Die ID des zu löschenden API-Keys.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM api_keys WHERE id = %s"
            cursor.execute(query, (api_key_id,))
            cnx.commit()
            return True
        except db_utils.Error as err:
            logger.error("Fehler beim Löschen des API-Keys: %s", err)
            flash("Datenbankfehler beim Löschen des API-Keys.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def delete_api_user_and_keys_db(api_user_id):
    """
    Löscht einen API-Benutzer und alle zugehörigen API-Keys.

    Args:
        api_user_id (int): Die ID des zu löschenden API-Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            # Zuerst alle API-Keys löschen (korrekte Spalte: user_id)
            query_keys = "DELETE FROM api_keys WHERE user_id = %s"
            cursor.execute(query_keys, (api_user_id,))
            # Dann den API-Benutzer löschen
            query_user = "DELETE FROM api_users WHERE id = %s"
            cursor.execute(query_user, (api_user_id,))
            cnx.commit()
            return True
        except db_utils.Error as err:
            logger.error("Fehler beim Löschen des API-Benutzers und seiner Keys: %s", err)
            flash("Datenbankfehler beim Löschen des API-Benutzers.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def _handle_delete_all_user_transactions(target_user_id):
    """
    Verarbeitet die Löschanfrage für alle Transaktionen eines Benutzers

        query = "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung, timestamp) VALUES (%s, %s, %s, NOW())"
        success, _ = db_utils.execute_commit(query, (user_id, beschreibung, saldo_aenderung))
        if not success:
            logger.error("Fehler beim Hinzufügen der Transaktion für Benutzer %s", user_id)
        return success
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user (dict): Das Benutzerobjekt des Zielbenutzers.
    """

    # Löscht alle Transaktionen für den angegebenen Benutzer
    query = "DELETE FROM transactions WHERE user_id = %s"
    result = db_utils.execute_commit(query, (target_user_id,))
    success = result[0] if result else False
    if not success:
        logger.error("Fehler beim Löschen der Transaktionen für Benutzer %s", target_user_id)
    return success


def _handle_toggle_user_lock_state(target_user_id, target_user, lock_state):
    """
    Verarbeitet das Sperren oder Entsperren eines Benutzers.

        query = "UPDATE users SET password = %s WHERE id = %s"
        success, _ = db_utils.execute_commit(query, (new_password_hash, user_id))
        if not success:
            logger.error("Fehler beim Aktualisieren des Passworts für Benutzer %s", user_id)
        return success
    Verarbeitet das Befördern oder Degradieren eines Benutzers/Admins.

    Args:
        target_user_id (int): Die ID des Zielbenutzers.
        target_user (dict): Das Benutzerobjekt des Zielbenutzers.
        admin_state (bool): True zum Befördern, False zum Degradieren.
    """

    # Sperrt oder entsperrt einen Benutzer
    if toggle_user_lock(target_user_id, lock_state):
        flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde {"gesperrt" if lock_state else "entsperrt"}.', 'success')
    else:
        flash(f'Fehler beim {"Sperren" if lock_state else "Entsperren"} des Benutzers.', 'error')


def _validate_bulk_change_form(form_data):
    """
    Validiert das Bulk-Änderungsformular für Sammelbuchungen.
    Gibt (is_valid, saldo_aenderung, selected_user_ids) zurück.
    """

    errors = False

    saldo_aenderung_str = form_data.get('saldo_aenderung')
    beschreibung = form_data.get('beschreibung')
    # Korrigiere das Feld: Im HTML heißt es 'selected_users'
    if hasattr(form_data, 'getlist'):
        selected_user_ids = form_data.getlist('selected_users')
    else:
        selected_user_ids = form_data.get('selected_users', [])

    # Prüfe, ob mindestens ein Benutzer ausgewählt wurde
    if not selected_user_ids or len(selected_user_ids) == 0:
        flash('Bitte mindestens einen Benutzer für die Sammelbuchung auswählen.', 'error')
        errors = True

    # Prüfe, ob eine Beschreibung vorhanden ist
    if not beschreibung or beschreibung.strip() == '':
        flash('Bitte eine Beschreibung für die Sammelbuchung angeben.', 'error')
        errors = True

    # Prüfe, ob die Saldoänderung eine gültige Zahl ist
    try:
        saldo_aenderung = int(saldo_aenderung_str)
    except (TypeError, ValueError):
        flash('Die Saldoänderung muss eine ganze Zahl sein.', 'error')
        errors = True
        saldo_aenderung = 0

    return (not errors), saldo_aenderung, selected_user_ids

def _handle_add_user_transaction(form_data, target_user):
    """
    Fügt eine Transaktion für den Zielbenutzer hinzu und versendet ggf. eine Benachrichtigung.
    Args:
        form_data: Die Formulardaten (enthält 'beschreibung', 'saldo_aenderung').
        target_user: Das Benutzerobjekt des Zielbenutzers.
    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    beschreibung = form_data.get('beschreibung')
    saldo_aenderung_str = form_data.get('saldo_aenderung')
    try:
        saldo_aenderung = int(saldo_aenderung_str)
    except (TypeError, ValueError):
        flash('Die Saldoänderung muss eine ganze Zahl sein.', 'error')
        return False

    user_id = target_user.get('id')
    if not user_id:
        flash('Benutzer-ID fehlt für die Transaktion.', 'error')
        return False

    success = add_transaction(user_id, beschreibung, saldo_aenderung)
    if success:
        # E-Mail-Benachrichtigung, falls aktiviert und E-Mail vorhanden
        if target_user.get('email') and get_user_notification_preference(user_id, 'NEUE_TRANSAKTION'):
            new_saldo = get_saldo_for_user(user_id)
            saldo_aenderung_str_fmt = f"{saldo_aenderung:+d} €"
            new_saldo_fmt = f"{new_saldo} €"
            logo_pfad = config.gui_config.get('email_logo_path', '')
            _send_manual_transaction_email(target_user, beschreibung, saldo_aenderung_str_fmt, new_saldo_fmt, logo_pfad)
        flash('Transaktion erfolgreich hinzugefügt.', 'success')
        return True
    flash('Fehler beim Hinzufügen der Transaktion.', 'error')
    return False


def _handle_delete_target_user(target_user_id, target_user):
    """
    Verarbeitet die Löschanfrage für einen Benutzer. Verhindert Selbstlöschung.

    Args:
        target_user_id (int): Die ID des zu löschenden Benutzers.
        target_user (dict): Das Benutzerobjekt des zu löschenden Benutzers.
        logged_in_user_id (int): Die ID des aktuell angemeldeten Admin-Benutzers.

    Returns:
        bool: True, wenn der Benutzer gelöscht wurde und eine Weiterleitung zum Dashboard erfolgen soll, sonst False.
    """

    logged_in_user_id = session.get('user_id')
    if target_user_id == logged_in_user_id:
        flash("Du kannst dich nicht selbst löschen.", "warning")
        return False  # Keine Weiterleitung zum Dashboard

    if delete_user(target_user_id):
        flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde gelöscht.', 'success')
        return True  # Weiterleitung zum Dashboard
    flash('Fehler beim Löschen des Benutzers.', 'error')
    return False


def _handle_update_user_comment_admin(form_data, target_user_id):
    """
    Verarbeitet die Aktualisierung des Kommentars eines Benutzers durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, dessen Kommentar aktualisiert wird.
    """

    comment = form_data.get('kommentar')
    if update_user_comment(target_user_id, comment if comment is not None else ""):
        flash('Kommentar erfolgreich aktualisiert.', 'success')
    else:
        flash('Fehler beim Aktualisieren des Kommentars.', 'error')  # Fallback, falls DB-Funktion nicht flasht


def _handle_update_infomail_responsible_threshold_admin(form_data, target_user_id):
    """
    Verarbeitet die Aktualisierung der Infomail-Schwelle eines Benutzers durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, dessen Infomail-Schwelle aktualisiert wird.
    """

    infomail_responsible_threshold = form_data.get('infomail_responsible_threshold')
    if update_user_infomail_responsible_threshold(target_user_id, infomail_responsible_threshold if infomail_responsible_threshold is not None else ""):
        flash('Infomail-Schwelle erfolgreich aktualisiert.', 'success')
    else:
        flash('Fehler beim Aktualisieren der Infomail-Schwelle.', 'error')  # Fallback, falls DB-Funktion nicht flasht


def _handle_update_user_email_admin(form_data, target_user_id):
    """
    Verarbeitet die Aktualisierung der E-Mail-Adresse eines Benutzers durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, dessen E-Mail aktualisiert wird.
    """

    email = form_data.get('email')
    if update_user_email(target_user_id, email):
        flash('Emailadresse erfolgreich aktualisiert.', 'success')
    else:
        flash('Fehler beim Aktualisieren der Emailadresse.', 'error')  # Fallback


def _validate_add_user_form(form_data):
    """
    Validiert die Formulardaten für das Hinzufügen eines neuen Benutzers.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.

    Returns:
        bool: True, wenn die Daten gültig sind, sonst False. Fehlermeldungen werden geflasht.
    """

    errors = False
    required_fields = ['code', 'nachname', 'vorname', 'password', 'confirm_password']
    for field in required_fields:
        if not form_data.get(field):
            flash(f"Bitte fülle das Pflichtfeld '{field}' aus.", "error")
            errors = True
            # Nicht nach erstem Fehler abbrechen, um alle fehlenden Felder zu melden (optional)

    if errors:  # Wenn schon Pflichtfelder fehlen, sind die folgenden Prüfungen ggf. nicht sinnvoll
        if not all(form_data.get(field) for field in ['password', 'confirm_password']):  # Sicherstellen, dass beide PW-Felder existieren
            flash("Passwortfelder dürfen nicht leer sein.", "error")  # Redundant, aber zur Sicherheit
        return False  # Frühzeitiger Ausstieg bei fehlenden Pflichtfeldern

    if form_data.get('password') != form_data.get('confirm_password'):
        flash("Die Passwörter stimmen nicht überein.", "error")
        errors = True
    if form_data.get('password') and len(form_data.get('password')) < 8:  # type: ignore
        flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'error')
        errors = True
    # fetch_user benötigt code, der oben schon als Pflichtfeld geprüft wurde
    if form_data.get('code') and fetch_user(form_data.get('code')):
        flash(f"Der Code '{form_data.get('code')}' wird bereits verwendet. Bitte wähle einen anderen.", "error")
        errors = True
    return not errors


def _validate_register_form(form_data):
    """
    Validiert die Formulardaten für die Registrierung eines neuen Benutzers.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.

    Returns:
        bool: True, wenn die Daten gültig sind, sonst False. Fehlermeldungen werden geflasht.
    """

    errors = False
    required_fields = ['nachname', 'vorname', 'password', 'confirm_password']
    for field in required_fields:
        if not form_data.get(field):
            flash(f"Bitte fülle das Pflichtfeld '{field}' aus.", "error")
            errors = True

    if errors:
        return False  # Frühzeitiger Ausstieg

    if form_data.get('password') != form_data.get('confirm_password'):
        flash("Die Passwörter stimmen nicht überein.", "error")
        errors = True

    if form_data.get('password') and len(form_data.get('password')) < 8:
        flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'error')
        errors = True

    if fetch_user(form_data.get('code')):
        flash(f"Der Benutzercode '{form_data.get('code')}' ist bereits vergeben.", "error")
        errors = True

    return not errors


def _process_system_setting_update(key, new_value_str):
    """
    Verarbeitet die Aktualisierung einer einzelnen Systemeinstellung.
    Beinhaltet Validierung für TRANSACTION_SALDO_CHANGE

    Args:
        key (str): Der Schlüssel der Systemeinstellung.
        new_value_str (str): Der neue Wert als String.

    Returns:
        bool: True, wenn die Aktualisierung für diese Einstellung erfolgreich war, sonst False.
    """

    if key == 'TRANSACTION_SALDO_CHANGE':
        try:
            val_int = int(new_value_str)
            if val_int >= 0:
                flash("Der Wert für 'Transaktions-Saldo-Änderung' muss kleiner als 0 sein.", "error")
                return False
        except ValueError:
            flash("Der Wert für 'Maximale Negativsaldo-Grenze' muss eine ganze Zahl sein.", "error")
            return False

    if not update_system_setting(key, new_value_str):
        # Fehler wird bereits in update_system_setting geflasht
        return False
    return True


# --- Stub für _handle_toggle_user_admin_state ---
def _handle_toggle_user_admin_state(target_user_id, target_user, admin_state):
    """
    Verarbeitet das Befördern oder Degradieren eines Benutzers zum/vom Admin.

    Args:
        target_user_id (int): Die ID des Zielbenutzers.
        target_user (dict): Das Benutzerobjekt des Zielbenutzers.
        admin_state (bool): True zum Befördern, False zum Degradieren.
    """
    if toggle_user_admin(target_user_id, admin_state):
        flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde {"zum Admin befördert" if admin_state else "zum normalen Benutzer degradiert"}.', 'success')
        return True
    flash(f'Fehler beim {"Befördern zum Admin" if admin_state else "Degradieren zum normalen Benutzer"} des Benutzers.', 'error')
    return False


def _process_bulk_transactions(user_ids, beschreibung, saldo_aenderung):
    """
    Verarbeitet die Sammelbuchung, fügt Transaktionen hinzu und sendet E-Mails.

    Args:
        user_ids (list[str]): Liste der ausgewählten Benutzer-IDs.
        beschreibung (str): Beschreibung für die Transaktion.
        saldo_aenderung (int): Der zu buchende Betrag.

    Returns:
        tuple[int, int]: Ein Tupel mit (Anzahl erfolgreicher, Anzahl fehlgeschlagener Transaktionen).
    """

    successful = 0
    failed = 0
    for user_id_str in user_ids:
        user_id_int = int(user_id_str)
        if add_transaction(user_id_int, beschreibung, saldo_aenderung):
            successful += 1
            target_user = get_user_by_id(user_id_int)
            if target_user and target_user.get('email') and get_user_notification_preference(user_id_int, 'NEUE_TRANSAKTION'):
                new_saldo = get_saldo_for_user(user_id_int)
                logo_pfad_str = str(Path("static/logo/logo-80x109.png"))
                _send_manual_transaction_email(target_user, beschreibung, str(saldo_aenderung), str(new_saldo), logo_pfad_str)
        else:
            failed += 1
    return successful, failed


def _process_user_info_form(form, user):
    """
    Verarbeitet die Formular-Aktionen von der Benutzerinformationsseite.

    Args:
        form (werkzeug.datastructures.ImmutableMultiDict): Die übermittelten Formulardaten.
        user (dict): Das Objekt des aktuell angemeldeten Benutzers.

    Returns:
        bool: True, wenn eine Aktion verarbeitet wurde, andernfalls False.
              Die Weiterleitung (Redirect) wird innerhalb der Funktion gehandhabt.
    """
    user_id = user['id']

    if 'change_password' in form:
        current_password = form['current_password']
        new_password = form['new_password']
        confirm_new_password = form['confirm_new_password']

        if not check_password_hash(user['password'], current_password):
            flash('Falsches aktuelles Passwort.', 'error')
        elif new_password != confirm_new_password:
            flash('Die neuen Passwörter stimmen nicht überein.', 'error')
        elif len(new_password) < 8:
            flash('Das neue Passwort muss mindestens 8 Zeichen lang sein.', 'error')
        else:
            new_password_hash = generate_password_hash(new_password)
            if update_password(user_id, new_password_hash):
                flash('Passwort erfolgreich geändert.', 'success')
            else:
                flash('Fehler beim Ändern des Passworts.', 'error')
        return True

    if 'change_email' in form:
        new_email = form.get('new_email', '').strip()
        if update_user_email(user_id, new_email):
            flash('Emailadresse erfolgreich geändert.', 'success')
        else:
            flash('Fehler beim Ändern der Emailadresse.', 'error')
        return True

    if 'update_notification_settings' in form:
        all_notification_types_db = get_all_notification_types()
        active_type_ids = [
            n_type["id"] for n_type in all_notification_types_db
            if form.get(f'notification_type_{n_type["id"]}')
        ]
        if update_user_notification_settings(user_id, active_type_ids):
            flash('Benachrichtigungseinstellungen erfolgreich gespeichert.', 'success')
        # Fehler wird in der Funktion selbst geflasht
        return True

    if 'update_infomail_user_threshold' in form:
        new_user_threshold = form.get('infomail_user_threshold', '').strip()
        if update_user_infomail_user_threshold(user_id, new_user_threshold):
            flash('Infomail-Guthaben-Grenze erfolgreich geändert.', 'success')
        else:
            flash('Fehler beim Ändern der Infomail-Guthaben-Grenze.', 'error')
        return True

    return False


# --- Flask Decorator ---
def admin_required(f):
    """
    Decorator, der sicherstellt, dass der Benutzer ein eingeloggter,
    nicht gesperrter Administrator ist.
    """

    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash("Bitte zuerst einloggen.", "success")
            return redirect(BASE_URL + url_for('login'))

        admin_user = get_user_by_id(user_id)
        if not (admin_user and admin_user.get('is_admin')):
            flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
            return redirect(BASE_URL + url_for('user_info'))

        if admin_user.get('is_locked'):
            session.pop('user_id', None)
            flash('Dein Administratorkonto wurde gesperrt.', 'error')
            return redirect(BASE_URL + url_for('login'))

        # Übergibt den geprüften Admin-Benutzer an die eigentliche Routen-Funktion
        return f(admin_user, *args, **kwargs)
    return decorated_function


@app.before_request
def make_session_permanent():
    """
    Setzt die Session-Lebensdauer bei jeder Anfrage zurück.
    """

    if 'user_id' in session:
        session.permanent = True


# --- Flask Injector ---
@app.context_processor
def inject_global_vars():
    """
    Stellt globale Variablen für alle Templates zur Verfügung.

    Diese Funktion wird von Flask vor dem Rendern jedes Templates
    aufgerufen und fügt das zurückgegebene Dictionary dem
    Template-Kontext hinzu.

    Returns:
        dict: Ein Dictionary mit globalen Variablen.
    """

    return {'app_name': config.app_name, 'app_slogan': config.app_slogan, 'version': app.config.get('version', 'unbekannt')}


# --- Flask Routen ---
@app.route('/', methods=['GET', 'POST'])
def login():
    """
    Verarbeitet den Login eines Benutzers.

    Wenn die Methode POST ist, wird der Benutzercode und das Passwort überprüft.
    Bei erfolgreicher Anmeldung wird der Benutzer in der Session gespeichert und zur Benutzerinformationsseite weitergeleitet.
    Bei fehlgeschlagener Anmeldung wird eine Fehlermeldung angezeigt.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Login-Seite (web_login.html)
        mit optionaler Fehlermeldung oder eine Weiterleitung.
    """

    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        if user and user.get('is_locked'):
            session.pop('user_id', None)
            flash('Dein Konto wurde gesperrt. Bitte kontaktiere einen Administrator.', 'error')
            return render_template('web_login.html')
        return redirect(BASE_URL + url_for('user_info'))

    if request.method == 'POST':
        code_email = request.form['code_email']
        password = request.form['password']
        user = fetch_user(code_email)
        if user and not user['is_locked'] and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session.permanent = True
            session.modified = True
            logger.debug(f"[login] Nach Setzen: session['user_id'] = {session.get('user_id')}")
            # Logging für gesetzte Cookies
            logger.debug(f"[login] Request cookies vor Redirect: {request.cookies}")
            response = redirect(BASE_URL + url_for('user_info'))
            logger.debug(f"[login] Response-Objekt vor Rückgabe: {response}")
            return response
        if user and user['is_locked']:
            flash('Dein Konto ist gesperrt. Bitte kontaktiere einen Administrator.', 'error')
        else:
            flash('Ungültiger Benutzername oder Passwort', 'error')
    return render_template('web_login.html')


@app.route('/datenschutz')
def datenschutz():
    """
    Rendert die Datenschutzerklärung-Seite.

    Diese Funktion ist für die Anzeige der statischen HTML-Seite
    der Datenschutzerklärung zuständig.
    """

    return render_template('web_privacy_policy.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Verarbeitet die Registrierung eines neuen Benutzers.

    Bei GET wird das Registrierungsformular angezeigt.
    Bei POST werden die Formulardaten validiert. Bei Erfolg wird ein neuer Benutzer
    in der Datenbank angelegt und der Benutzer zur Login-Seite weitergeleitet.
    Bei Fehlern wird das Formular mit entsprechenden Meldungen erneut angezeigt.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Registrierungsseite
        oder eine Weiterleitung zur Login-Seite.
    """

    if 'user_id' in session:
        return redirect(BASE_URL + url_for('user_info'))

    if request.method == 'POST':
        form_data = request.form
        if _validate_register_form(form_data):
            # GET Request
            generated_code = None
            for _ in range(100):  # Max 100 attempts
                potential_code = ''.join(random.choices(string.digits, k=10))
                if not fetch_user(potential_code):
                    generated_code = potential_code
                    break
            if not generated_code:
                flash("Ich konnte keinen eindeutigen Code generieren. Bitte versuche es später erneut.", "warning")
                generated_code = ""  # Fallback
            user_details = {
                'code': generated_code,
                'nachname': form_data.get('nachname', '').strip(),
                'vorname': form_data.get('vorname', '').strip(),
                'password': form_data.get('password'),
                'email': form_data.get('email', '').strip(),  # Optional
                'kommentar': form_data.get('kommentar', '').strip(),  # Optional
                'acc_duties': form_data.get('pflichten'),
                'acc_privacy_policy': form_data.get('datenschutz'),
                'is_locked': False,
                'is_admin': False  # Neue Benutzer sind niemals Admins
            }
            if add_regular_user_db(user_details):
                if user_details['email']:
                    logo_pfad_str = str(Path("static/logo/logo-80x109.png"))
                    _send_user_register_email(user_details['vorname'], user_details['email'], generated_code, logo_pfad_str)

                flash(f"Registrierung erfolgreich! Du kannst dich nun anmelden mit dem Code '{generated_code}'. Bitte notiere dir "
                      "diesen Code für künftige Logins!", "success")
                return redirect(BASE_URL + url_for('login'))
        # Bei Validierungsfehler oder DB-Fehler, das Formular erneut mit den
        # eingegebenen Daten anzeigen.
        return render_template('web_user_register.html',
                               form_data=form_data,
                               version=app.config.get('version', 'unbekannt'))

    # GET Request
    return render_template('web_user_register.html',
                           form_data=None,
                           version=app.config.get('version', 'unbekannt'))


@app.route('/request-password-reset', methods=['GET', 'POST'])
def request_password_reset():
    """
    Verarbeitet die Anforderung eines Passwort-Reset-Links.
    """

    if 'user_id' in session:
        return redirect(url_for('user_info'))
    if request.method == 'POST':
        email = request.form.get('email')
        user = get_user_by_email(email)

        # Aus Sicherheitsgründen wird immer dieselbe Meldung angezeigt,
        # um nicht preiszugeben, ob eine E-Mail existiert.
        if user and not user['is_locked']:
            token = secrets.token_urlsafe(32)
            if store_reset_token(user['id'], token):
                logo_pfad_str = str(Path("static/logo/logo-80x109.png"))
                _send_password_reset_email(user['email'], token, logo_pfad_str)

        flash('Wenn ein Konto mit dieser E-Mail-Adresse existiert und nicht gesperrt ist, wurde ein Link zum Zurücksetzen des Passworts gesendet.', 'success')
        return redirect(url_for('login'))

    return render_template('web_request_reset.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_with_token(token):
    """
    Verarbeitet das tatsächliche Zurücksetzen des Passworts mit einem Token.
    """

    if 'user_id' in session:
        return redirect(url_for('user_info'))

    user = get_user_by_reset_token(token)
    if not user:
        flash('Der Link zum Zurücksetzen des Passworts ist ungültig oder abgelaufen.', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not password or len(password) < 8:
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'error')
        elif password != confirm_password:
            flash('Die Passwörter stimmen nicht überein.', 'error')
        else:
            new_password_hash = generate_password_hash(password)
            if update_password(user['id'], new_password_hash):
                delete_reset_token(token)  # Wichtig: Token nach Nutzung entwerten
                flash('Dein Passwort wurde erfolgreich zurückgesetzt. Du kannst dich nun anmelden.', 'success')
                return redirect(url_for('login'))
            flash('Beim Aktualisieren des Passworts ist ein Fehler aufgetreten.', 'error')

    return render_template('web_reset_password.html', token=token)


@app.route('/user_info', methods=['GET', 'POST'])
def user_info():
    """
    Zeigt Benutzerinformationen an und verarbeitet Änderungen (Passwort, E-Mail, Benachrichtigungen).

    Die POST-Logik ist in die Hilfsfunktion _process_user_info_form ausgelagert.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Benutzerseite oder eine Weiterleitung.
    """
    user_id = session.get('user_id')
    logger.debug(f"[user_info] Session user_id: {user_id}")
    if not user_id:
        logger.debug("[user_info] Kein user_id in Session, redirect zu Login.")
        return redirect(BASE_URL + url_for('login'))

    user = get_user_by_id(user_id)
    logger.debug(f"[user_info] get_user_by_id({user_id}) -> {user}")
    if not user:
        logger.debug("[user_info] Benutzer nicht gefunden, Session löschen und redirect zu Login.")
        session.pop('user_id', None)
        flash('Benutzer nicht gefunden oder Sitzung abgelaufen.', 'error')
        return redirect(BASE_URL + url_for('login'))

    if user.get('is_locked'):
        logger.debug("[user_info] Benutzer ist gesperrt, Session löschen und redirect zu Login.")
        session.pop('user_id', None)
        flash('Dein Konto wurde gesperrt. Bitte kontaktiere einen Administrator.', 'error')
        return redirect(BASE_URL + url_for('login'))

    if request.method == 'POST':
        logger.debug(f"[user_info] POST request: {request.form}")
        if _process_user_info_form(request.form, user):
            logger.debug("[user_info] POST Verarbeitung erfolgreich, redirect zu user_info.")
            return redirect(BASE_URL + url_for('user_info'))

    # GET Request oder nach POST-Redirect
    # Benutzerdaten neu laden, um eventuelle Änderungen anzuzeigen
    user_data = get_user_by_id(user_id)
    logger.debug(f"[user_info] user_data nach Reload: {user_data}")
    if not user_data:  # Sicherheitscheck, falls der Benutzer zwischenzeitlich gelöscht wurde
        logger.debug("[user_info] Benutzer nach Reload nicht mehr vorhanden, Session löschen und redirect zu Login.")
        session.pop('user_id', None)
        flash('Benutzer nicht mehr vorhanden.', 'error')
        return redirect(BASE_URL + url_for('login'))

    nfc_tokens = get_user_nfc_tokens(user_id)
    transactions = get_user_transactions(user_id)
    saldo = sum(t['saldo_aenderung'] for t in transactions) if transactions else 0

    all_notification_types_data = get_all_notification_types()
    user_notification_settings_data = get_user_notification_settings(user_id)

    logger.debug(f"[user_info] Rendering Template mit user={user_data}, saldo={saldo}, nfc_tokens={nfc_tokens}, transactions={transactions}, all_notification_types={all_notification_types_data}, user_notification_settings={user_notification_settings_data}")
    return render_template('web_user_info.html',
                           user=user_data,
                           nfc_tokens=nfc_tokens,
                           transactions=transactions,
                           saldo=saldo,
                           all_notification_types=all_notification_types_data,
                           user_notification_settings=user_notification_settings_data,
                           version=app.config.get('version', 'unbekannt'))


@app.route('/qr_code')
def generate_qr():
    """
    Generiert dynamisch einen QR-Code als PNG-Bild und sendet ihn an den Browser.

    Diese Route erfordert, dass der Benutzer eingeloggt ist. Andernfalls wird er
    zur Login-Seite weitergeleitet.
    Der Inhalt des QR-Codes wird durch die URL-Parameter 'usercode' und 'aktion' bestimmt.
    'aktion' wird intern auf einen beschreibenden Text abgebildet.

        URL-Parameter (Query-Argumente):
        usercode (str): Der Benutzercode, der im QR-Code kodiert werden soll.
                        Dieser Parameter ist erforderlich.
        aktion (str): Ein Kürzel für die Aktion, die mit dem QR-Code verbunden ist.
                      Mögliche Werte:
                        - 'a': Wird zu "Transaktion buchen".
                        - 'k': Wird zu "Kontostand".
                      Andere Werte führen zu einem Standardtext "hier stimmt was nicht!".
                      Dieser Parameter ist erforderlich.

    Returns:
        flask.Response: Eine Flask-Antwort, die entweder das generierte QR-Code-Bild
                        (mimetype 'image/png') enthält oder eine Weiterleitung
                        (redirect) zur Login-Seite oder zur Benutzerinformationsseite,
                        falls Parameter fehlen oder der Benutzer nicht eingeloggt ist.
                        Im Falle eines ungültigen 'aktion'-Parameters wird eine
                        Fehlermeldung geflasht.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "success")
        return redirect(BASE_URL + url_for('login'))

    # Die Daten für den QR-Code werden als URL-Parameter erwartet (z.B. /qr_code?usercode=1234567890a&aktion=a)
    usercode_to_encode = request.args.get('usercode')
    text_to_add = request.args.get('aktion')

    if not usercode_to_encode or not text_to_add:
        flash("Ungültige Aktion für QR-Code.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if text_to_add == "a":
        text_to_add = "Transaktion buchen"
        img = erzeuge_qr_code(usercode_to_encode + "a", text_to_add)
    elif text_to_add == "k":
        text_to_add = "Kontostand"
        img = erzeuge_qr_code(usercode_to_encode + "k", text_to_add)
    else:
        text_to_add = "Hier stimmt was nicht!"
        img = None
        flash("Ungültige Aktion für QR-Code.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    # Bild in einem In-Memory Bytes-Puffer speichern
    byte_io = io.BytesIO()
    img.save(byte_io, 'PNG')
    byte_io.seek(0)  # Wichtig: Den Puffer an den Anfang zurücksetzen

    # Bild als Datei-Antwort senden
    return send_file(byte_io, mimetype='image/png')


@app.route('/admin', methods=['GET', 'POST'])
@admin_required
def admin_dashboard(admin_user):
    """
    Zeigt das Admin-Dashboard mit einer Benutzerübersicht und deren Salden.
    Ermöglicht Admins zudem die Verwaltung von globalen Systemeinstellungen.

    Bei GET-Anfragen werden Benutzerdaten und aktuelle Systemeinstellungen geladen.
    Bei POST-Anfragen können Systemeinstellungen aktualisiert werden.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Admin-Dashboard-Seite (`web_admin_dashboard.html`)
        oder eine Weiterleitung bei fehlenden Rechten, Fehlern oder wenn nicht eingeloggt.
    """

    if request.method == 'POST':
        if 'update_system_settings' in request.form:
            settings_updated_successfully = True

            # Hole alle Schlüssel aus der DB, um sicherzustellen, dass nur existierende verarbeitet werden
            all_db_setting_keys = get_all_system_settings().keys()

            for key in all_db_setting_keys:
                if key in request.form:
                    new_value = request.form[key].strip()
                    if not _process_system_setting_update(key, new_value):
                        settings_updated_successfully = False
            if settings_updated_successfully:
                flash("Systemeinstellungen erfolgreich aktualisiert.", "success")
            # Individuelle Fehler wurden bereits in _process_system_setting_update oder update_system_setting geflasht
        return redirect(BASE_URL + url_for('admin_dashboard'))

    # GET Request - Daten holen
    users_data = get_all_users()
    saldo_by_user_data = get_saldo_by_user()
    system_settings_data = get_all_system_settings()
    user_saldo_all = sum(saldo_by_user_data.values())
    recent_transactions = get_recent_transactions(limit=10)

    return render_template('web_admin_dashboard.html',
                           user=admin_user,
                           users=users_data,
                           saldo_by_user=saldo_by_user_data,
                           user_saldo_all=user_saldo_all,
                           recent_transactions=recent_transactions,
                           system_settings=system_settings_data,
                           version=app.config.get('version', 'unbekannt'))


@app.route('/admin/add_user', methods=['GET', 'POST'])
@admin_required
def add_user(admin_user):
    """
    Verarbeitet das Hinzufügen eines neuen regulären Benutzers (Frontend-Benutzer).

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Seite zum Hinzufügen
        eines Benutzers oder eine Weiterleitung.
    """

    if request.method == 'POST':
        form_data = request.form
        if _validate_add_user_form(form_data):
            user_details = {
                'code': form_data.get('code'),
                'nachname': form_data.get('nachname'),
                'vorname': form_data.get('vorname'),
                'password': form_data.get('password'),
                'email': form_data.get('email'),
                'kommentar': form_data.get('kommentar'),
                'is_admin': 'is_admin' in form_data
            }
            if add_regular_user_db(user_details):
                if user_details['email']:
                    logo_pfad_str = str(Path("static/logo/logo-80x109.png"))
                    _send_user_register_email(user_details['vorname'], user_details['email'], user_details['code'], logo_pfad_str)

                flash(f"Benutzer '{user_details['vorname']} {user_details['nachname']}' erfolgreich hinzugefügt.", "success")
                return redirect(BASE_URL + url_for('admin_dashboard'))
        # Bei Validierungsfehler oder DB-Fehler (geflasht in add_regular_user_db oder _validate_add_user_form),
        # das Formular mit den eingegebenen Daten erneut anzeigen
        return render_template('web_user_add.html', user=admin_user, current_code=form_data.get('code'), form_data=form_data, version=app.config.get('version', 'unbekannt'))

    # GET Request
    generated_code = None
    for _ in range(100):  # Max 100 attempts
        potential_code = ''.join(random.choices(string.digits, k=10))
        if not fetch_user(potential_code):
            generated_code = potential_code
            break
    if not generated_code:
        flash("Konnte keinen eindeutigen Code generieren. Bitte versuche es später erneut.", "warning")
        generated_code = ""  # Fallback

    return render_template('web_user_add.html', user=admin_user, current_code=generated_code, form_data=None)


# --- Flask Route: API-Key löschen (muss nach app-Init und admin_required stehen) ---
@app.route('/admin/api_key/<int:api_key_id_route>/delete', methods=['POST'])
@admin_required
def admin_delete_api_key(_admin_user, api_key_id_route):
    """
    Löscht einen spezifischen API-Key anhand seiner ID und leitet zur passenden API-User-Detailseite weiter.
    """
    api_user_id_for_redirect = request.form.get('api_user_id_for_redirect')

    if delete_api_key_db(api_key_id_route):
        flash(f"API-Key (ID: {api_key_id_route}) erfolgreich gelöscht.", "success")
    else:
        flash(f"API-Key (ID: {api_key_id_route}) konnte nicht gelöscht werden oder wurde nicht gefunden.", "warning")

    if api_user_id_for_redirect:
        try:
            api_user_id_int = int(api_user_id_for_redirect)
            return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id_route=api_user_id_int))
        except ValueError:
            flash("Ungültige API User ID für Weiterleitung.", "error")
    return redirect(BASE_URL + url_for('admin_api_user_manage'))


@app.route('/admin/api_users', methods=['GET', 'POST'])
@admin_required
def admin_api_user_manage(admin_user):
    """
    Verwaltet API-Benutzer, zeigt eine Liste an und erlaubt das Hinzufügen neuer.

    Bei einer GET-Anfrage wird eine Seite mit einer Liste aller API-Benutzer und
    einem Formular zum Hinzufügen eines neuen API-Benutzers angezeigt. Bei einer
    POST-Anfrage (aus dem Hinzufügen-Formular) wird versucht, den neuen
    API-Benutzer zu erstellen.

    Returns:
        str oder werkzeug.wrappers.response.Response: Bei GET das gerenderte Template
        `web_admin_api_user_manage.html`. Bei POST eine Weiterleitung zurück zur
        gleichen Seite (`admin_api_user_manage`) mit entsprechenden
        Erfolgs- oder Fehlermeldungen. Bei Authentifizierungs-/Autorisierungsfehlern
        erfolgt eine Weiterleitung zur Login- bzw. Benutzerinformationsseite.
    """

    if request.method == 'POST':
        # Hinzufügen eines neuen API-Benutzers
        username = request.form.get('username')
        if not username:
            flash("API-Benutzername darf nicht leer sein.", "error")
        else:
            new_api_user_id = add_api_user_db(username)
            if new_api_user_id:
                flash(f"API-Benutzer '{username}' erfolgreich hinzugefügt.", "success")
            # Fehler (z.B. doppelter Name) wird in add_api_user_db geflasht
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    api_users_list = get_all_api_users()
    return render_template('web_admin_api_user_manage.html', user=admin_user, api_users=api_users_list)


@app.route('/admin/api_user/<int:api_user_id_route>')
@admin_required
def admin_api_user_detail(admin_user, api_user_id_route):
    """
    Zeigt die Detailansicht für einen spezifischen API-Benutzer inklusive seiner API-Keys.

    Diese Route prüft, ob der anfragende Benutzer ein eingeloggter, aktiver Administrator
    ist. Die Details des API-Benutzers und seiner zugehörigen API-Keys werden aus
    der Datenbank geladen und im Template `web_admin_api_user_detail.html` dargestellt.

    Args:
        api_user_id_route (int): Die ID des anzuzeigenden API-Benutzers aus der URL.

    Returns:
        str oder werkzeug.wrappers.response.Response: Das gerenderte Template
        `web_admin_api_user_detail.html` mit den API-Benutzerdaten.
        Bei Authentifizierungs-/Autorisierungsfehlern oder wenn der API-Benutzer
        nicht gefunden wird, erfolgen entsprechende Weiterleitungen mit Flash-Nachrichten.
    """

    target_api_user = get_api_user_by_id(api_user_id_route)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    api_keys_list = get_api_keys_for_api_user(api_user_id_route)
    return render_template('web_admin_api_user_detail.html', user=admin_user, api_user=target_api_user, api_keys=api_keys_list)


@app.route('/admin/api_user/<int:api_user_id_route>/generate_key', methods=['POST'])
@admin_required
def admin_generate_api_key_for_user(_admin_user, api_user_id_route):
    """
    Generiert einen neuen API-Key für einen spezifischen API-Benutzer.

    Diese Route erfordert eine POST-Anfrage. Sie prüft, ob der anfragende Benutzer
    ein eingeloggter, aktiver Administrator ist. Der API-Benutzer, für den ein
    Key generiert wird, wird durch `api_user_id_route` identifiziert. Der neu
    generierte Key wird einmalig per Flash-Nachricht angezeigt und muss vom
    Administrator sofort kopiert werden.

    Args:
        api_user_id_route (int): Die ID des API-Benutzers aus der URL, für den ein
                                 Key generiert werden soll.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur Detailseite des
        betreffenden API-Benutzers. Bei Authentifizierungs-/Autorisierungsfehlern
        oder wenn der API-Benutzer nicht gefunden wird, erfolgen entsprechende
        Weiterleitungen mit Flash-Nachrichten.
    """

    target_api_user = get_api_user_by_id(api_user_id_route)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden, für den ein Key generiert werden soll.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    new_key_name_string = request.form['api_key_name']
    new_key_string = generate_api_key_string()
    if add_api_key_for_user_db(api_user_id_route, new_key_name_string, new_key_string):
        flash(f"Neuer API-Key für '{target_api_user['username']}' generiert: {new_key_string} - "
              "Bitte sofort sicher kopieren, er kann nicht wieder angezeigt werden!", "success")
    # Fehler wurde bereits in add_api_key_for_user_db geflasht
    return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id_route=api_user_id_route))


@app.route('/admin/api_user/<int:api_user_id_route>/delete', methods=['POST'])
@admin_required
def admin_delete_api_user(_admin_user, api_user_id_route):
    """
    Löscht einen API-Benutzer und alle zugehörigen API-Keys.

    Diese Route erfordert eine POST-Anfrage. Vor dem Löschen wird geprüft, ob
    der anfragende Benutzer ein eingeloggter, aktiver Administrator ist. Der zu
    löschende API-Benutzer wird anhand der `api_user_id_route` identifiziert.
    Nach erfolgreichem Löschen oder bei Fehlern erfolgt eine Weiterleitung zur
    API-Benutzerverwaltungsseite mit einer entsprechenden Flash-Nachricht.

    Args:
        api_user_id_route (int): Die ID des zu löschenden API-Benutzers aus der URL.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur
        API-Benutzerverwaltungsseite (`admin_api_user_manage`) oder zur Login- bzw.
        Benutzerinformationsseite bei Authentifizierungs-/Autorisierungsfehlern.
    """

    api_user_to_delete = get_api_user_by_id(api_user_id_route)
    if not api_user_to_delete:
        flash("Zu löschender API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    if delete_api_user_and_keys_db(api_user_id_route):
        flash(f"API-Benutzer '{api_user_to_delete['username']}' und zugehörige API-Keys wurden gelöscht.", "success")
    else:
        pass

    return redirect(BASE_URL + url_for('admin_api_user_manage'))


@app.route('/admin/bulk_change', methods=['GET', 'POST'])
@admin_required
def admin_bulk_change(admin_user):
    """
    Ermöglicht Admins das Erstellen von Sammelbuchungen für ausgewählte Benutzer.
    Die Authentifizierung wird durch den @admin_required Decorator gehandhabt.
    """

    if request.method == 'POST':
        is_valid, saldo_aenderung, selected_user_ids = _validate_bulk_change_form(request.form)

        if not is_valid:
            # Bei Fehlern zum Formular zurückkehren und eingegebene Daten beibehalten
            users_data = get_all_users()
            return render_template('web_admin_bulk_change.html',
                                   user=admin_user,
                                   users=users_data,
                                   form_data=request.form)

        # Verarbeitung der Sammelbuchung
        successful, failed = _process_bulk_transactions(
            selected_user_ids,
            request.form.get('beschreibung'),
            saldo_aenderung
        )

        flash(f"{successful} Transaktionen erfolgreich erstellt.", "success")
        if failed > 0:
            flash(f"{failed} Transaktionen konnten nicht erstellt werden.", "error")

        return redirect(BASE_URL + url_for('admin_dashboard'))

    # GET-Logik zum Anzeigen der Seite
    users_data = get_all_users()
    today_str = datetime.now().strftime('%d.%m.%Y')
    default_form_data = {
        'beschreibung': f'Essen zum Dienst am {today_str}',
        'saldo_aenderung': -3
    }

    return render_template('web_admin_bulk_change.html',
                           user=admin_user,
                           users=users_data,
                           form_data=default_form_data)


@app.route('/admin/user/<int:target_user_id>/transactions', methods=['GET', 'POST'])
@admin_required
def admin_user_modification(admin_user, target_user_id):
    """
    Zeigt die Transaktionen eines bestimmten Benutzers an und ermöglicht diverse Modifikationen.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Daten modifiziert werden sollen.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Seite mit den Benutzerdaten
        (web_admin_user_modification.html) oder eine Weiterleitung.
    """

    target_user = get_user_by_id(target_user_id)
    if not target_user:
        flash("Zielbenutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_dashboard'))

    if request.method == 'POST':
        form_data = request.form
        action_handled = False
        # Standard-Weiterleitung nach einer Aktion (außer Benutzerlöschung)
        redirect_url = BASE_URL + url_for('admin_user_modification', target_user_id=target_user_id)

        action_handlers = {
            'delete_transactions': lambda: _handle_delete_all_user_transactions(target_user_id),
            'add_transaction': lambda: _handle_add_user_transaction(form_data, target_user),
            'lock_user': lambda: _handle_toggle_user_lock_state(target_user_id, target_user, True),
            'unlock_user': lambda: _handle_toggle_user_lock_state(target_user_id, target_user, False),
            'promote_user': lambda: _handle_toggle_user_admin_state(target_user_id, target_user, True),
            'demote_user': lambda: _handle_toggle_user_admin_state(target_user_id, target_user, False),
            'add_user_nfc_token': lambda: _handle_add_user_nfc_token_admin(form_data, target_user_id),
            'update_user_comment': lambda: _handle_update_user_comment_admin(form_data, target_user_id),
            'update_infomail_responsible_threshold': lambda: _handle_update_infomail_responsible_threshold_admin(form_data, target_user_id),
            'update_user_email': lambda: _handle_update_user_email_admin(form_data, target_user_id),
            'delete_user_nfc_token': lambda: _handle_delete_user_nfc_token_admin(form_data, target_user_id),
        }

        for action_key, handler_func in action_handlers.items():
            if action_key in form_data:
                handler_func()
                action_handled = True
                break  # Nur eine Aktion pro POST-Request annehmen

        # Spezielle Behandlung für 'delete_user', da es die Weiterleitungs-URL ändern kann
        if 'delete_user' in form_data and not action_handled:  # 'not action_handled' zur Sicherheit
            if _handle_delete_target_user(target_user_id, target_user):
                redirect_url = BASE_URL + url_for('admin_dashboard')
            action_handled = True

        if not action_handled:
            flash('Ungültige oder fehlende Aktion.', 'error')

        return redirect(redirect_url)

    # GET Request
    nfc_tokens = get_user_nfc_tokens(target_user_id)
    transactions = get_user_transactions(target_user_id)
    saldo = get_saldo_for_user(target_user_id)

    refreshed_target_user = get_user_by_id(target_user_id)  # Für aktuelle Daten im Template
    if not refreshed_target_user:
        flash("Zielbenutzer konnte nicht erneut geladen werden.", "error")
        return redirect(BASE_URL + url_for('admin_dashboard'))

    return render_template('web_admin_user_modification.html',
                           user=refreshed_target_user,
                           nfc_tokens=nfc_tokens,
                           transactions=transactions,
                           saldo=saldo,
                           admin_user=admin_user,
                           version=app.config.get('version', 'unbekannt'))


@app.route('/logout')
def logout():
    """
    Meldet den Benutzer ab, indem die Benutzer-ID aus der Session entfernt wird.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur Login-Seite.
    """

    session.pop('user_id', None)
    flash("Erfolgreich abgemeldet.", "success")
    return redirect(BASE_URL + url_for('login'))


if __name__ == '__main__':
    app.run(host=config.gui_config['host'], port=config.gui_config['port'], debug=config.gui_config['flask_debug_mode'])
