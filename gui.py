"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

# Logging zuerst aktivieren
import sys
import logging
import binascii
import os
import io
import random
import secrets
import string
import qrcode
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file # pigar: required-packages=uWSGI
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error, IntegrityError # IntegrityError für Unique-Constraint-Fehler hinzugefügt
import config
import db_utils

logging.basicConfig(
    level=logging.DEBUG,
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

app.debug = config.gui_config['debug_mode']

app.config['SECRET_KEY'] = os.urandom(24)
app.json.ensure_ascii = False
app.json.mimetype = "application/json; charset=utf-8"

logger.info("Feuerwehr-Versorgungs-Helfer GUI wurde gestartet")

if "BASE_URL" in os.environ:
    BASE_URL = os.environ.get('BASE_URL', '/')
    logger.info("BASE_URL: %s", BASE_URL)
else:
    BASE_URL=""

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
    """

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(daten)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")

    qr_breite, qr_hoehe = img.size
    text_farbe = "black"
    hintergrund_farbe = "white"
    text_abstand_unten = 40
    schriftgroesse = 20
    font_names = ["Hack-Bold.ttf", "DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf"]
    schriftart = None

    for font_name in font_names:
        try:
            schriftart = ImageFont.truetype(font_name, schriftgroesse)
            logger.info("Schriftart '%s' geladen.", font_name)
            break  # Erfolgreich geladen, Schleife verlassen
        except IOError:
            logger.error("Schriftart '%s' nicht gefunden.", font_name)

    if schriftart is None:
        logger.error("Keine der bevorzugten Schriftarten gefunden. Lade Standardschriftart.")
        try:
            schriftart = ImageFont.load_default(size=schriftgroesse)
        except AttributeError: # Fallback für ältere Pillow Versionen ohne size Parameter
            schriftart = ImageFont.load_default()

    zeichne_temp = ImageDraw.Draw(Image.new("RGB", (1,1)))

    if hasattr(zeichne_temp, "textbbox"): # Pillow 10.0.0+
        # textbbox((0,0)...) gibt (x1, y1, x2, y2) relativ zum Ankerpunkt (0,0)
        # Standardanker für textbbox ist 'la' (left-ascent), d.h. (0,0) ist links auf der Grundlinie.
        # text_box[1] ist der y-Wert des höchsten Pixels (negativ für Aufstrich).
        # text_box[3] ist der y-Wert des tiefsten Pixels (positiv für Abstriche).
        text_box = zeichne_temp.textbbox((0, 0), text, font=schriftart)
        text_breite_val = text_box[2] - text_box[0]
        text_hoehe_val = text_box[3] - text_box[1] # Gesamthöhe des Textes
    elif hasattr(zeichne_temp, "textsize"): # Ältere Pillow Versionen
        text_breite_val, text_hoehe_val = zeichne_temp.textsize(text, font=schriftart)
    else: # Fallback
        text_breite_val = len(text) * (schriftgroesse // 2)
        text_hoehe_val = schriftgroesse
        logger.error("Konnte Textgröße nicht exakt bestimmen, verwende Schätzung.")

    tatsaechliche_gesamthoehe_textbereich = max(text_abstand_unten, text_hoehe_val)

    # Berechne den Abstand über dem Text, um ihn im tatsaechliche_gesamthoehe_textbereich zu zentrieren.
    # Wenn tatsaechliche_gesamthoehe_textbereich == text_hoehe_val, ist dieser Abstand 0.
    abstand_ueber_text = (tatsaechliche_gesamthoehe_textbereich - text_hoehe_val) // 15

    # Neue Gesamthöhe des Bildes
    neue_bild_hoehe = qr_hoehe + tatsaechliche_gesamthoehe_textbereich

    # Neues Bild erstellen
    neues_bild = Image.new("RGBA", (qr_breite, neue_bild_hoehe), hintergrund_farbe)
    neues_bild.paste(img, (0, 0)) # QR-Code auf das neue Bild kopieren

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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, event_schluessel, beschreibung FROM benachrichtigungstypen ORDER BY id"
            cursor.execute(query)
            types = cursor.fetchall()
            return types
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen aller Benachrichtigungstypen: %s", err)
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []

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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    settings = {} # Key: typ_id, Value: email_aktiviert (True/False)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT typ_id, email_aktiviert FROM benutzer_benachrichtigungseinstellungen WHERE benutzer_id = %s"
            cursor.execute(query, (user_id,))
            for row in cursor.fetchall():
                settings[row['typ_id']] = bool(row['email_aktiviert'])
            return settings
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der Benutzereinstellungen für Benachrichtigungen: %s", err)
            return {}
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return {}

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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        flash("Datenbankverbindung konnte nicht hergestellt werden.", "error")
        return False

    cursor = cnx.cursor()
    try:
        # Alle verfügbaren Benachrichtigungstyp-IDs abrufen
        cursor.execute("SELECT id FROM benachrichtigungstypen")
        all_available_type_ids = [row[0] for row in cursor.fetchall()]

        for type_id in all_available_type_ids:
            is_enabled = 1 if type_id in active_notification_type_ids_int else 0
            query = """
                INSERT INTO benutzer_benachrichtigungseinstellungen (benutzer_id, typ_id, email_aktiviert)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE email_aktiviert = VALUES(email_aktiviert)
            """
            cursor.execute(query, (user_id, type_id, is_enabled))
        cnx.commit()
        return True
    except Error as err:
        logger.error("Fehler beim Aktualisieren der Benutzereinstellungen für Benachrichtigungen: %s", err)
        flash("Fehler beim Speichern der Benachrichtigungseinstellungen.", "error")
        cnx.rollback()
        return False
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)

# Systemeinstellungen (Admin)
def get_all_system_settings():
    """
    Ruft alle Systemeinstellungen aus der Datenbank ab.

    Returns:
        dict: Ein Dictionary, wobei der Schlüssel der 'einstellung_schluessel' ist
              und der Wert ein weiteres Dictionary mit 'wert' und 'beschreibung' der Einstellung ist.
              Gibt ein leeres Dictionary zurück bei Fehlern oder wenn keine Einstellungen vorhanden sind.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    settings = {} # Key: einstellung_schluessel, Value: {'wert': ..., 'beschreibung': ...}
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT einstellung_schluessel, einstellung_wert, beschreibung FROM system_einstellungen"
            cursor.execute(query)
            for row in cursor.fetchall():
                settings[row['einstellung_schluessel']] = {'wert': row['einstellung_wert'], 'beschreibung': row['beschreibung']}
            return settings
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der Systemeinstellungen: %s", err)
            return {}
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return {}

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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "UPDATE system_einstellungen SET einstellung_wert = %s WHERE einstellung_schluessel = %s"
            cursor.execute(query, (einstellung_wert, einstellung_schluessel))
            cnx.commit()
            return cursor.rowcount > 0 # True wenn eine Zeile aktualisiert wurde
        except Error as err:
            logger.error("Fehler beim Aktualisieren der Systemeinstellung '%s': %s", einstellung_schluessel, err)
            flash(f"Datenbankfehler beim Speichern der Einstellung '{einstellung_schluessel}'.", "error")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        token_binary = hex_to_binary(token_hex)
        if token_binary:
            try:
                query = "INSERT INTO nfc_token SET user_id = %s, token_name = %s, token_daten = %s, last_used = NOW()"
                cursor.execute(query, (user_id, token_name, token_binary))
                cnx.commit()
                return True
            except Error as err:
                logger.error("Fehler beim Hinzufügen des NFC-Tokens: %s", err)
                cnx.rollback()
                return False
            finally:
                cursor.close()
                db_utils.DatabaseConnectionPool.close_connection(cnx)
        else:
            flash('Ungültige NFC-Token Daten. Bitte überprüfe die Eingabe.', 'error')
            return False
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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        if token_id:
            try:
                logger.info("Lösche NFC-Tokens: %s von Benutzer %s", token_id, user_id)
                query = "DELETE FROM nfc_token WHERE token_id = %s AND user_id = %s"
                cursor.execute(query, (token_id, user_id))
                cnx.commit()
                return True
            except Error as err:
                logger.error("Fehler beim Entfernen des NFC-Tokens: %s", err)
                cnx.rollback()
                return False
            finally:
                cursor.close()
                db_utils.DatabaseConnectionPool.close_connection(cnx)
        else:
            flash('Ungültige NFC-Token Daten. Bitte überprüfe die Eingabe.', 'error')
            return False
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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT token_id, token_name, token_daten as token_daten, last_used, DATEDIFF(CURDATE(), DATE(last_used)) AS last_used_days_ago
                FROM nfc_token WHERE user_id = %s ORDER BY last_used DESC
            """
            cursor.execute(query, (user_id,))
            nfc_tokens = cursor.fetchall()
            return nfc_tokens
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen der Benutzer NFC Tokens: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None

def _handle_add_user_nfc_token_admin(form_data, target_user_id):
    """
    Verarbeitet das Hinzufügen eines NFC-Tokens für einen Benutzer durch einen Admin.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, für den der Token hinzugefügt wird.
    """

    nfc_token_name = form_data.get('nfc_token_name')
    nfc_token_daten = form_data.get('nfc_token_daten') # HEX Format erwartet
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

    Args:
        user_id (int): Die ID des zu löschenden Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Löschen des Benutzers: %s", err)
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def toggle_user_admin(user_id, admin_state):
    """
    Macht einen Benutzer zum Admin (oder umgekehrt).

    Args:
        user_id (int): Die ID des Benutzers.
        admin_state (bool): True == Befördern, False == Degradieren.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            if admin_state:
                query = "UPDATE users SET is_admin = 1 WHERE id = %s"
            else:
                query = "UPDATE users SET is_admin = 0 WHERE id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Ändern des Admin-Modes für den Benutzers: %s", err)
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def toggle_user_lock(user_id, lock_state):
    """
    Sperrt einen Benutzer anhand seiner ID oder entsperrt ihn.

    Args:
        user_id (int): Die ID des zu sperrenden/entsperrenden Benutzers.
        lock_state (bool): True == Sperren, False == Entsperren.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            if lock_state:
                query = "UPDATE users SET is_locked = 1 WHERE id = %s"
            else:
                query = "UPDATE users SET is_locked = 0 WHERE id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Ändern des Locks für den Benutzers: %s", err)
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def update_user_comment(user_id, comment):
    """
    Ändert den Kommentar eines Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des Benutzers.
        comment (str): Der neue Kommentar.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "UPDATE users SET kommentar = %s WHERE id = %s"
            cursor.execute(query, (comment, user_id))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Ändern des Kommentars für den Benutzers: %s", err)
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def update_user_email(user_id, email):
    """
    Ändert die Emailadresse eines Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des Benutzers.
        email (str): Die neue Emailadresse.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "UPDATE users SET email = %s WHERE id = %s"
            cursor.execute(query, (email, user_id))
            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Ändern der Emailadresse für den Benutzers: %s", err)
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def fetch_user(code):
    """
    Ruft einen Benutzer aus der Datenbank anhand seines Codes ab.

    Args:
        code (str): Der eindeutige Code des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, password, is_admin, is_locked)
              oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, code, nachname, vorname, password, is_admin, is_locked FROM users WHERE code = %s"
            cursor.execute(query, (code,))
            user = cursor.fetchone()
            return user
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen des Benutzers: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None

def get_user_by_id(user_id):
    """
    Ruft einen Benutzer anhand seiner ID ab.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, email, kommentar, is_locked, is_admin, password)
              oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, nachname, vorname, email, kommentar, is_locked, is_admin, password
                FROM users
                WHERE id = %s
            """
            cursor.execute(query, (user_id,))
            user = cursor.fetchone()
            return user
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen des Benutzers: %s", err)
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None

def get_saldo_for_user(user_id):
    """
    Berechnet das Saldo für den Benutzer mit der übergebenen user_id.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        int: Das Saldo oder 0, falls kein Benutzer gefunden wird oder keine Transaktionen vorhanden sind.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "SELECT SUM(saldo_aenderung) FROM transactions WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            saldo = result[0] if result and result[0] is not None else 0
            return saldo
        except Error as err:
            logger.error("Datenbankfehler beim Abrufen des Saldos: %s", err)
            return 0
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
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
              (id, api_key). Gibt eine leere Liste zurück, falls keine Keys gefunden werden oder ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, api_key FROM api_keys WHERE user_id = %s ORDER BY id"
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
                INSERT INTO users (code, nachname, vorname, password, email, kommentar, is_admin, is_locked)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            """
            cursor.execute(query, (
                user_data['code'],
                user_data['nachname'],
                user_data['vorname'],
                hashed_password,
                user_data.get('email'),
                user_data.get('kommentar'),
                1 if user_data.get('is_admin') else 0
            ))
            cnx.commit()
            return True
        except IntegrityError:
            flash(f"Benutzercode '{user_data['code']}' existiert bereits oder ein anderes eindeutiges Feld ist doppelt.", 'error')
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
            return cursor.lastrowid # Gibt die ID des eingefügten Datensatzes zurück
        except IntegrityError:
            flash(f"API-Benutzername '{username}' existiert bereits.", 'error')
            cnx.rollback()
            return None
        except Error as err:
            logger.error("Fehler beim Hinzufügen des API-Benutzers: %s", err)
            flash("Datenbankfehler beim Hinzufügen des API-Benutzers.", 'error')
            cnx.rollback()
            return None
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None

def add_api_key_for_user_db(api_user_id, api_key_string):
    """
    Fügt einen neuen API-Key für einen API-Benutzer hinzu.

    Args:
        api_user_id (int): Die ID des API-Benutzers.
        api_key_string (str): Der zu speichernde API-Key.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO api_keys (user_id, api_key) VALUES (%s, %s)"
            cursor.execute(query, (api_user_id, api_key_string))
            cnx.commit()
            return True
        except IntegrityError: # Sollte extrem selten sein, falls der Key schon existiert
            flash("Generierter API-Key existiert bereits. Bitte erneut versuchen.", 'error')
            cnx.rollback()
            return False
        except Error as err:
            logger.error("Fehler beim Hinzufügen des API-Keys für API-Benutzer {api_user_id}: %s", err)
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
            # Überprüfen, ob eine Zeile tatsächlich gelöscht wurde
            return cursor.rowcount > 0
        except Error as err:
            logger.error("Fehler beim Löschen des API-Keys {api_key_id}: %s", err)
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
            # Zuerst alle zugehörigen API-Keys löschen
            query_delete_keys = "DELETE FROM api_keys WHERE user_id = %s"
            cursor.execute(query_delete_keys, (api_user_id,))

            # Dann den API-Benutzer löschen
            query_delete_user = "DELETE FROM api_users WHERE id = %s"
            cursor.execute(query_delete_user, (api_user_id,))

            cnx.commit()
            return True
        except Error as err:
            logger.error("Fehler beim Löschen des API-Benutzers %s und seiner Keys: %s", api_user_id, err)
            flash("Datenbankfehler beim Löschen des API-Benutzers.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

def _handle_delete_all_user_transactions(target_user_id):
    """
    Verarbeitet die Löschanfrage für alle Transaktionen eines Benutzers.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Transaktionen gelöscht werden sollen.
    """

    if delete_all_transactions(target_user_id):
        flash('Alle Transaktionen für diesen Benutzer wurden gelöscht.', 'success')
    else:
        flash('Fehler beim Löschen der Transaktionen.', 'error')

def _handle_add_user_transaction(form_data, target_user_id):
    """
    Verarbeitet das Hinzufügen einer neuen Transaktion für einen Benutzer.

    Args:
        form_data (werkzeug.datastructures.ImmutableMultiDict): Die Formulardaten.
        target_user_id (int): Die ID des Benutzers, für den die Transaktion hinzugefügt wird.
    """

    beschreibung = form_data.get('beschreibung', '')
    saldo_aenderung_str = form_data.get('saldo_aenderung')
    if not beschreibung:
        flash('Beschreibung für Transaktion darf nicht leer sein.', 'error')
    elif saldo_aenderung_str is None:
        flash('Saldoänderung für Transaktion darf nicht leer sein.', 'error')
    else:
        try:
            saldo_aenderung = int(saldo_aenderung_str)
            # Die Funktion add_transaction flasht bereits Fehlermeldungen bei DB-Fehlern
            if add_transaction(target_user_id, beschreibung, saldo_aenderung):
                flash('Transaktion erfolgreich hinzugefügt.', 'success')
        except ValueError:
            flash('Ungültiger Wert für Saldoänderung. Es muss eine Zahl sein.', 'error')

def _handle_toggle_user_lock_state(target_user_id, target_user, lock_state):
    """
    Verarbeitet das Sperren oder Entsperren eines Benutzers.

    Args:
        target_user_id (int): Die ID des Zielbenutzers.
        target_user (dict): Das Benutzerobjekt des Zielbenutzers.
        lock_state (bool): True zum Sperren, False zum Entsperren.
    """

    action_text = "gesperrt" if lock_state else "entsperrt"
    if toggle_user_lock(target_user_id, lock_state):
        flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde {action_text}.', 'success')
    else:
        flash(f'Fehler beim {action_text} des Benutzers.', 'error')

def _handle_toggle_user_admin_state(target_user_id, target_user, admin_state):
    """
    Verarbeitet das Befördern oder Degradieren eines Benutzers/Admins.

    Args:
        target_user_id (int): Die ID des Zielbenutzers.
        target_user (dict): Das Benutzerobjekt des Zielbenutzers.
        admin_state (bool): True zum Befördern, False zum Degradieren.
    """

    action_text = "zum Admin befördert" if admin_state else "zum Benutzer degradiert"
    role_text = "Benutzer" if admin_state else "Admin"
    if toggle_user_admin(target_user_id, admin_state):
        flash(f'{role_text} "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde {action_text}.', 'success')
    else:
        flash(f'Fehler beim {"Befördern" if admin_state else "Degradieren"} des {role_text.lower()}s.', 'error')

def _handle_delete_target_user(target_user_id, target_user, logged_in_user_id):
    """
    Verarbeitet die Löschanfrage für einen Benutzer. Verhindert Selbstlöschung.

    Args:
        target_user_id (int): Die ID des zu löschenden Benutzers.
        target_user (dict): Das Benutzerobjekt des zu löschenden Benutzers.
        logged_in_user_id (int): Die ID des aktuell angemeldeten Admin-Benutzers.

    Returns:
        bool: True, wenn der Benutzer gelöscht wurde und eine Weiterleitung zum Dashboard erfolgen soll, sonst False.
    """

    if target_user_id == logged_in_user_id:
        flash("Sie können sich nicht selbst löschen.", "warning")
        return False # Keine Weiterleitung zum Dashboard

    if delete_user(target_user_id): # delete_user löscht auch Transaktionen durch DB CASCADE
        flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {target_user_id}) wurde gelöscht.', 'success')
        return True # Weiterleitung zum Dashboard
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
    # Leerer Kommentar ist erlaubt, um ihn zu löschen. Validierung hier ggf. anpassen.
    # Die DB-Funktion sollte leere Strings handhaben können (z.B. als NULL speichern oder leer).
    if update_user_comment(target_user_id, comment if comment is not None else ""):
        flash('Kommentar erfolgreich aktualisiert.', 'success')
    else:
        flash('Fehler beim Aktualisieren des Kommentars.', 'error') # Fallback, falls DB-Funktion nicht flasht

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
        flash('Fehler beim Aktualisieren der Emailadresse.', 'error') # Fallback

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

    if errors: # Wenn schon Pflichtfelder fehlen, sind die folgenden Prüfungen ggf. nicht sinnvoll
        if not all(form_data.get(field) for field in ['password', 'confirm_password']): # Sicherstellen, dass beide PW-Felder existieren
            flash("Passwortfelder dürfen nicht leer sein.", "error") # Redundant, aber zur Sicherheit
        return False # Frühzeitiger Ausstieg bei fehlenden Pflichtfeldern

    if form_data.get('password') != form_data.get('confirm_password'):
        flash("Die Passwörter stimmen nicht überein.", "error")
        errors = True
    if form_data.get('password') and len(form_data.get('password')) < 8: # type: ignore
        flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'error')
        errors = True
    # fetch_user benötigt code, der oben schon als Pflichtfeld geprüft wurde
    if form_data.get('code') and fetch_user(form_data.get('code')):
        flash(f"Der Code '{form_data.get('code')}' wird bereits verwendet. Bitte wählen Sie einen anderen.", "error")
        errors = True
    return not errors

def _process_system_setting_update(key, new_value_str):
    """
    Verarbeitet die Aktualisierung einer einzelnen Systemeinstellung.
    Beinhaltet Validierung für MAX_NEGATIVSALDO.

    Args:
        key (str): Der Schlüssel der Systemeinstellung.
        new_value_str (str): Der neue Wert als String.

    Returns:
        bool: True, wenn die Aktualisierung für diese Einstellung erfolgreich war, sonst False.
    """
    if key == 'MAX_NEGATIVSALDO':
        try:
            val_int = int(new_value_str)
            if val_int > 0:
                flash("Der Wert für 'Maximale Negativsaldo-Grenze' muss 0 oder negativ sein.", "error")
                return False
        except ValueError:
            flash("Der Wert für 'Maximale Negativsaldo-Grenze' muss eine ganze Zahl sein.", "error")
            return False

    if not update_system_setting(key, new_value_str):
        # Fehler wird bereits in update_system_setting geflasht
        return False
    return True

# --- Flask Routen ---

@app.route('/', methods=['GET', 'POST'])
def login():
    """
    Verarbeitet den Login eines Benutzers.

    Wenn die Methode POST ist, wird der Benutzercode und das Passwort überprüft.
    Bei erfolgreicher Anmeldung wird der Benutzer in der Session gespeichert und zur Benutzerinformationsseite weitergeleitet.
    Bei fehlgeschlagener Anmeldung wird eine Fehlermeldung angezeigt.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Login-Seite (login.html)
        mit optionaler Fehlermeldung oder eine Weiterleitung.
    """

    if 'user_id' in session:
        user = get_user_by_id(session['user_id'])
        if user and user.get('is_locked'): # Prüfen ob User gesperrt ist
            session.pop('user_id', None)
            flash('Ihr Konto wurde gesperrt. Bitte kontaktieren Sie einen Administrator.', 'error')
            return render_template('login.html')
        return redirect(BASE_URL + url_for('user_info'))

    if request.method == 'POST':
        code = request.form['code']
        password = request.form['password']
        user = fetch_user(code)
        if user and not user['is_locked'] and check_password_hash(user['password'], password): # Prüfen ob User gesperrt ist
            session['user_id'] = user['id']
            session.permanent = True
            return redirect(BASE_URL + url_for('user_info'))
        if user and user['is_locked']:
            flash('Ihr Konto ist gesperrt. Bitte kontaktieren Sie einen Administrator.', 'error')
        else:
            flash('Ungültiger Benutzername oder Passwort', 'error')
    return render_template('login.html')

@app.route('/user_info', methods=['GET', 'POST'])
def user_info():
    """
    Zeigt die Benutzerinformationen an und verarbeitet Passwortänderung, E-Mail-Änderung
    sowie die Verwaltung der E-Mail-Benachrichtigungseinstellungen.

    Bei GET-Anfragen werden Benutzerdaten, Transaktionen, Saldo, NFC-Token, verfügbare
    Benachrichtigungstypen und die aktuellen Einstellungen des Benutzers geladen und angezeigt.
    Bei POST-Anfragen werden Formulare für Passwortänderung, E-Mail-Änderung oder
    Aktualisierung der Benachrichtigungseinstellungen verarbeitet.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Benutzerinformationsseite (`user_info.html`)
        oder eine Weiterleitung zur Login-Seite bei Fehlern oder wenn nicht eingeloggt.
    """

    user_id = session.get('user_id')
    if not user_id:
        return redirect(BASE_URL + url_for('login'))

    user = get_user_by_id(user_id) #
    if not user:
        session.pop('user_id', None) #
        flash('Benutzer nicht gefunden oder Sitzung abgelaufen.', 'error') #
        return redirect(BASE_URL + url_for('login')) #

    if user.get('is_locked'): #
        session.pop('user_id', None) #
        flash('Ihr Konto wurde gesperrt. Bitte kontaktieren Sie einen Administrator.', 'error') #
        return redirect(BASE_URL + url_for('login')) #

    if request.method == 'POST':
        if 'change_password' in request.form: #
            current_password = request.form['current_password'] #
            new_password = request.form['new_password'] #
            confirm_new_password = request.form['confirm_new_password'] #

            if not check_password_hash(user['password'], current_password): #
                flash('Falsches aktuelles Passwort.', 'error') #
            elif new_password != confirm_new_password: #
                flash('Die neuen Passwörter stimmen nicht überein.', 'error') #
            elif len(new_password) < 8: #
                flash('Das neue Passwort muss mindestens 8 Zeichen lang sein.', 'error') #
            else:
                new_password_hash = generate_password_hash(new_password) #
                if update_password(user_id, new_password_hash): #
                    flash('Passwort erfolgreich geändert.', 'success') #
                else:
                    flash('Fehler beim Ändern des Passworts.', 'error') #
            return redirect(BASE_URL + url_for('user_info')) #

        if 'change_email' in request.form: #
            new_email = request.form.get('new_email', '').strip() #
            if update_user_email(user_id, new_email): #
                flash('Emailadresse erfolgreich geändert.', 'success') #
            else:
                flash('Fehler beim Ändern der Emailadresse.', 'error') #
            return redirect(BASE_URL + url_for('user_info')) #

        if 'update_notification_settings' in request.form:
            all_notification_types_db = get_all_notification_types() # Ruft alle Typen aus DB ab.
            active_type_ids = []
            for n_type in all_notification_types_db: # Durchläuft alle in der DB definierten Typen.
                # Prüft, ob für den aktuellen Typ eine Checkbox gesendet wurde (und damit aktiviert ist).
                # Der `value` der Checkbox im HTML wurde auf `n_type.id` gesetzt.
                if request.form.get(f'notification_type_{n_type["id"]}'):
                    active_type_ids.append(n_type["id"])

            if update_user_notification_settings(user_id, active_type_ids):
                flash('Benachrichtigungseinstellungen erfolgreich gespeichert.', 'success')
            # Fehler werden in update_user_notification_settings selbst geflasht.
            return redirect(BASE_URL + url_for('user_info'))

    # GET Request oder nach POST redirect
    user = get_user_by_id(user_id) # Erneut laden für aktuelle Daten
    if not user: # Sicherheitscheck
        session.pop('user_id', None) #
        flash('Benutzer nicht mehr vorhanden.', 'error') #
        return redirect(BASE_URL + url_for('login')) #

    nfc_tokens = get_user_nfc_tokens(user_id) #
    transactions = get_user_transactions(user_id) #
    saldo = sum(t['saldo_aenderung'] for t in transactions) if transactions else 0 #

    # Für Benachrichtigungseinstellungen
    all_notification_types_data = get_all_notification_types()
    user_notification_settings_data = get_user_notification_settings(user_id)

    return render_template('user_info.html',
                           user=user,
                           nfc_tokens=nfc_tokens,
                           transactions=transactions,
                           saldo=saldo,
                           all_notification_types=all_notification_types_data, # Korrigierter Variablenname
                           user_notification_settings=user_notification_settings_data) # Korrigierter Variablenname

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
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    # Die Daten für den QR-Code werden als URL-Parameter erwartet (z.B. /qr_code?data=1234567890a)
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
    byte_io.seek(0) # Wichtig: Den Puffer an den Anfang zurücksetzen

    # Bild als Datei-Antwort senden
    return send_file(byte_io, mimetype='image/png')

@app.route('/admin', methods=['GET', 'POST'])
def admin_dashboard():
    """
    Zeigt das Admin-Dashboard mit einer Benutzerübersicht und deren Salden.
    Ermöglicht Admins zudem die Verwaltung von globalen Systemeinstellungen.

    Bei GET-Anfragen werden Benutzerdaten und aktuelle Systemeinstellungen geladen.
    Bei POST-Anfragen können Systemeinstellungen aktualisiert werden.
    Erfordert Admin-Rechte und eine aktive Benutzersitzung.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Admin-Dashboard-Seite (`admin_dashboard.html`)
        oder eine Weiterleitung bei fehlenden Rechten, Fehlern oder wenn nicht eingeloggt.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    if request.method == 'POST':
        if 'update_system_settings' in request.form:
            settings_updated_successfully = True # Gesamterfolg aller Einstellungen

            # Hole alle Schlüssel aus der DB, um sicherzustellen, dass nur existierende verarbeitet werden
            # und um die Reihenfolge der Verarbeitung ggf. zu steuern (obwohl hier nicht kritisch)
            all_db_setting_keys = get_all_system_settings().keys()

            for key in all_db_setting_keys:
                if key in request.form: # Nur verarbeiten, wenn das Feld im Formular gesendet wurde
                    new_value = request.form[key].strip()
                    if not _process_system_setting_update(key, new_value):
                        settings_updated_successfully = False
                        # Optional: Hier `break` einfügen, wenn bei erstem Fehler abgebrochen werden soll

            if settings_updated_successfully:
                flash("Systemeinstellungen erfolgreich aktualisiert.", "success")
            # Individuelle Fehler wurden bereits in _process_system_setting_update oder update_system_setting geflasht
        return redirect(BASE_URL + url_for('admin_dashboard'))

    # GET Request
    users_data = get_all_users()
    saldo_by_user_data = get_saldo_by_user()
    system_settings_data = get_all_system_settings()

    return render_template('admin_dashboard.html',
                           user=admin_user,
                           users=users_data,
                           saldo_by_user=saldo_by_user_data,
                           system_settings=system_settings_data)

@app.route('/admin/add_user', methods=['GET', 'POST'])
def add_user():
    """
    Verarbeitet das Hinzufügen eines neuen regulären Benutzers (Frontend-Benutzer).

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Seite zum Hinzufügen
        eines Benutzers oder eine Weiterleitung.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

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
                flash(f"Benutzer '{user_details['vorname']} {user_details['nachname']}' erfolgreich hinzugefügt.", "success")
                return redirect(BASE_URL + url_for('admin_dashboard'))
        # Bei Validierungsfehler oder DB-Fehler (geflasht in add_regular_user_db oder _validate_add_user_form),
        # das Formular mit den eingegebenen Daten erneut anzeigen
        return render_template('user_add.html',
                               user=admin_user,
                               current_code=form_data.get('code'), # Den vom User eingegebenen Code wiederverwenden
                               form_data=form_data
                              )

    # GET Request
    generated_code = None
    for _ in range(100): # Max 100 attempts
        potential_code = ''.join(random.choices(string.digits, k=10))
        if not fetch_user(potential_code):
            generated_code = potential_code
            break
    if not generated_code:
        flash("Konnte keinen eindeutigen Code generieren. Bitte versuchen Sie es manuell oder später erneut.", "warning")
        generated_code = "" # Fallback

    return render_template('user_add.html', user=admin_user, current_code=generated_code, form_data=None)

@app.route('/admin/api_users', methods=['GET', 'POST'])
def admin_api_user_manage():
    """
    Verwaltet API-Benutzer, zeigt eine Liste an und erlaubt das Hinzufügen neuer.

    Bei einer GET-Anfrage wird eine Seite mit einer Liste aller API-Benutzer und
    einem Formular zum Hinzufügen eines neuen API-Benutzers angezeigt. Bei einer
    POST-Anfrage (aus dem Hinzufügen-Formular) wird versucht, den neuen
    API-Benutzer zu erstellen.

    Returns:
        str oder werkzeug.wrappers.response.Response: Bei GET das gerenderte Template
        `admin_api_user_manage.html`. Bei POST eine Weiterleitung zurück zur
        gleichen Seite (`admin_api_user_manage`) mit entsprechenden
        Erfolgs- oder Fehlermeldungen. Bei Authentifizierungs-/Autorisierungsfehlern
        erfolgt eine Weiterleitung zur Login- bzw. Benutzerinformationsseite.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    if request.method == 'POST':
        # Hinzufügen eines neuen API-Benutzers
        username = request.form.get('username')
        if not username:
            flash("API-Benutzername darf nicht leer sein.", "error")
        else:
            new_api_user_id = add_api_user_db(username)
            if new_api_user_id:
                flash(f"API-Benutzer '{username}' erfolgreich hinzugefügt.", "success")
                # Optional: Direkt zur Detailseite des neuen Users weiterleiten
                # return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id=new_api_user_id))
            # Fehler (z.B. doppelter Name) wird in add_api_user_db geflasht
        return redirect(BASE_URL + url_for('admin_api_user_manage')) # Nach POST zur gleichen Seite zurück

    api_users_list = get_all_api_users()
    return render_template('admin_api_user_manage.html', user=admin_user, api_users=api_users_list)

@app.route('/admin/api_user/<int:api_user_id_route>')
def admin_api_user_detail(api_user_id_route):
    """
    Zeigt die Detailansicht für einen spezifischen API-Benutzer inklusive seiner API-Keys.

    Diese Route prüft, ob der anfragende Benutzer ein eingeloggter, aktiver Administrator
    ist. Die Details des API-Benutzers und seiner zugehörigen API-Keys werden aus
    der Datenbank geladen und im Template `admin_api_user_detail.html` dargestellt.

    Args:
        api_user_id_route (int): Die ID des anzuzeigenden API-Benutzers aus der URL.

    Returns:
        str oder werkzeug.wrappers.response.Response: Das gerenderte Template
        `admin_api_user_detail.html` mit den API-Benutzerdaten.
        Bei Authentifizierungs-/Autorisierungsfehlern oder wenn der API-Benutzer
        nicht gefunden wird, erfolgen entsprechende Weiterleitungen mit Flash-Nachrichten.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    target_api_user = get_api_user_by_id(api_user_id_route)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    api_keys_list = get_api_keys_for_api_user(api_user_id_route)
    return render_template('admin_api_user_detail.html', user=admin_user, api_user=target_api_user, api_keys=api_keys_list)

@app.route('/admin/api_user/<int:api_user_id_route>/generate_key', methods=['POST'])
def admin_generate_api_key_for_user(api_user_id_route):
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

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    target_api_user = get_api_user_by_id(api_user_id_route)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden, für den ein Key generiert werden soll.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    new_key_string = generate_api_key_string()
    if add_api_key_for_user_db(api_user_id_route, new_key_string):
        # WICHTIG: Den Key nur dieses eine Mal anzeigen!
        flash(f"Neuer API-Key für '{target_api_user['username']}' generiert: {new_key_string}. Bitte sofort sicher kopieren!", "success")
    else:
        # Fehler wurde bereits in add_api_key_for_user_db geflasht
        pass

    return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id_route=api_user_id_route))

@app.route('/admin/api_key/<int:api_key_id_route>/delete', methods=['POST'])
def admin_delete_api_key(api_key_id_route):
    """
    Löscht einen spezifischen API-Key.

    Diese Route erfordert eine POST-Anfrage. Sie prüft, ob der anfragende
    Benutzer ein eingeloggter, aktiver Administrator ist. Der zu löschende
    API-Key wird durch `api_key_id_route` identifiziert. Die ID des
    zugehörigen API-Benutzers (`api_user_id_for_redirect`) wird aus dem
    Formular erwartet, um korrekt zur Detailseite des API-Benutzers zurückleiten
    zu können.

    Args:
        api_key_id_route (int): Die ID des zu löschenden API-Keys aus der URL.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur Detailseite des
        betreffenden API-Benutzers oder zur API-Benutzerverwaltungsseite als Fallback.
        Bei Authentifizierungs-/Autorisierungsfehlern erfolgt eine Weiterleitung
        zur Login- bzw. Benutzerinformationsseite.
    """

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    api_user_id_for_redirect = request.form.get('api_user_id_for_redirect')

    if delete_api_key_db(api_key_id_route):
        flash(f"API-Key (ID: {api_key_id_route}) erfolgreich gelöscht.", "success")
    else:
        # Fehler wurde bereits in delete_api_key_db geflasht, oder der Key existierte nicht
        flash(f"API-Key (ID: {api_key_id_route}) konnte nicht gelöscht werden oder wurde nicht gefunden.", "warning")

    if api_user_id_for_redirect:
        try:
            # Sicherstellen, dass es eine gültige ID ist, bevor umgeleitet wird
            api_user_id_int = int(api_user_id_for_redirect)
            return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id_route=api_user_id_int))
        except ValueError:
            flash("Ungültige API User ID für Weiterleitung.", "error")
    # Fallback, falls die api_user_id nicht ermittelt werden konnte oder ungültig war
    return redirect(BASE_URL + url_for('admin_api_user_manage'))

@app.route('/admin/api_user/<int:api_user_id_route>/delete', methods=['POST']) # Nur POST für Löschaktionen
def admin_delete_api_user(api_user_id_route):
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

    user_id = session.get('user_id')
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    api_user_to_delete = get_api_user_by_id(api_user_id_route)
    if not api_user_to_delete:
        flash("Zu löschender API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_api_user_manage'))

    if delete_api_user_and_keys_db(api_user_id_route):
        flash(f"API-Benutzer '{api_user_to_delete['username']}' und zugehörige API-Keys wurden gelöscht.", "success")
    else:
        # Genauere Fehlermeldung kommt von DB-Funktion und wird dort geflasht
        # flash(f"Fehler beim Löschen des API-Benutzers '{api_user_to_delete['username']}'.", "error")
        pass

    return redirect(BASE_URL + url_for('admin_api_user_manage'))

@app.route('/admin/user/<int:target_user_id>/transactions', methods=['GET', 'POST'])
def admin_user_modification(target_user_id):
    """
    Zeigt die Transaktionen eines bestimmten Benutzers an und ermöglicht diverse Modifikationen.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Daten modifiziert werden sollen.

    Returns:
        str oder werkzeug.wrappers.response.Response: Die gerenderte Seite mit den Benutzerdaten
        (admin_user_modification.html) oder eine Weiterleitung.
    """
    logged_in_user_id = session.get('user_id')
    if not logged_in_user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    current_admin_user = get_user_by_id(logged_in_user_id)
    if not (current_admin_user and current_admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if current_admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

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
            'add_transaction': lambda: _handle_add_user_transaction(form_data, target_user_id),
            'lock_user': lambda: _handle_toggle_user_lock_state(target_user_id, target_user, True),
            'unlock_user': lambda: _handle_toggle_user_lock_state(target_user_id, target_user, False),
            'promote_user': lambda: _handle_toggle_user_admin_state(target_user_id, target_user, True),
            'demote_user': lambda: _handle_toggle_user_admin_state(target_user_id, target_user, False),
            'add_user_nfc_token': lambda: _handle_add_user_nfc_token_admin(form_data, target_user_id),
            'update_user_comment': lambda: _handle_update_user_comment_admin(form_data, target_user_id),
            'update_user_email': lambda: _handle_update_user_email_admin(form_data, target_user_id),
            'delete_user_nfc_token': lambda: _handle_delete_user_nfc_token_admin(form_data, target_user_id),
        }

        for action_key, handler_func in action_handlers.items():
            if action_key in form_data:
                handler_func()
                action_handled = True
                break # Nur eine Aktion pro POST-Request annehmen

        # Spezielle Behandlung für 'delete_user', da es die Weiterleitungs-URL ändern kann
        if 'delete_user' in form_data and not action_handled: # 'not action_handled' zur Sicherheit
            if _handle_delete_target_user(target_user_id, target_user, logged_in_user_id):
                redirect_url = BASE_URL + url_for('admin_dashboard')
            action_handled = True

        if not action_handled:
            flash('Ungültige oder fehlende Aktion.', 'error')

        return redirect(redirect_url)

    # GET Request
    nfc_tokens = get_user_nfc_tokens(target_user_id)
    transactions = get_user_transactions(target_user_id)
    saldo = get_saldo_for_user(target_user_id)

    refreshed_target_user = get_user_by_id(target_user_id) # Für aktuelle Daten im Template
    if not refreshed_target_user:
        flash("Zielbenutzer konnte nicht erneut geladen werden.", "error")
        return redirect(BASE_URL + url_for('admin_dashboard'))

    return render_template('admin_user_modification.html',
                           user=refreshed_target_user,
                           nfc_tokens=nfc_tokens,
                           transactions=transactions,
                           saldo=saldo,
                           admin_user=current_admin_user)

@app.route('/logout')
def logout():
    """
    Meldet den Benutzer ab, indem die Benutzer-ID aus der Session entfernt wird.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur Login-Seite.
    """

    session.pop('user_id', None)
    flash("Erfolgreich abgemeldet.", "info")
    return redirect(BASE_URL + url_for('login'))

if __name__ == '__main__':
    app.run(host=config.gui_config['host'], port=config.gui_config['port'], debug=config.gui_config['debug_mode'])
