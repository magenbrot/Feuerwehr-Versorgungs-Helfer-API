"""Dieses Modul ist eine API Middleware für den Feuerwehr-Versorgungs-Helfer"""

import base64
import datetime
import sys
from functools import wraps
from pathlib import Path
from typing import Optional, Dict, Any
from flask import Flask, jsonify, request, render_template
from mysql.connector import Error
import config
import db_utils
import email_sender

app = Flask(__name__)

app.json.ensure_ascii = False
app.json.mimetype = "application/json; charset=utf-8"

# Initialisiere den Pool einmal beim Start der Anwendung # pylint: disable=R0801
try:
    db_utils.DatabaseConnectionPool.initialize_pool(config.db_config)
except Error as e:
    # Direkter Print, da Logger ggf. noch nicht voll initialisiert ist oder Konfigurationsproblem.
    print(f"Kritischer Fehler beim Starten der Datenbankverbindung: {e}")
    sys.exit(1)

def prepare_and_send_email(email_params: dict, smtp_cfg: dict) -> bool:
    """
    Bereitet eine E-Mail mit Flasks render_template vor und versendet sie.
    Die Argumente für die E-Mail-Details sind in einem Dictionary zusammengefasst.

    Args:
        email_params: Ein Dictionary mit den Details für die E-Mail.
            Erwartete Schlüssel:
                'empfaenger_email' (str): E-Mail-Adresse des Empfängers.
                'betreff' (str): Betreff der E-Mail.
                'template_name_html' (str): Dateiname des HTML-Templates (im Flask templates Ordner).
                'template_name_text' (str): Dateiname des Text-Templates (im Flask templates Ordner).
                'template_context' (dict): Dictionary mit Daten für die Templates.
                'logo_dateipfad' (str, optional): Pfad zur Logo-Datei.
        smtp_cfg: SMTP-Konfigurationsdictionary.

    Returns:
        bool: True bei Erfolg, sonst False.
    """

    empfaenger_email = email_params.get('empfaenger_email')
    betreff = email_params.get('betreff')
    template_name_html = email_params.get('template_name_html')
    template_name_text = email_params.get('template_name_text')
    template_context = email_params.get('template_context', {})
    logo_dateipfad_str = email_params.get('logo_dateipfad')

    if not all([empfaenger_email, betreff, template_name_html, template_name_text]):
        app.logger.error("Unvollständige E-Mail-Parameter. Benötigt: empfaenger_email, betreff, template_name_html, template_name_text.")
        return False

    logo_exists = False
    if logo_dateipfad_str:
        logo_path_obj = Path(logo_dateipfad_str)
        if logo_path_obj.is_file():
            logo_exists = True
        else:
            app.logger.warning("Logo-Datei nicht gefunden unter: %s", logo_dateipfad_str)

    try:
        template_context_final = template_context.copy()
        template_context_final['logo_exists_fuer_template'] = logo_exists

        with app.app_context():
            final_html_body = render_template(template_name_html, **template_context_final)
            final_text_body = render_template(template_name_text, **template_context_final)

    except Exception as e:  # pylint: disable=W0718
        app.logger.error("Fehler beim Rendern der E-Mail-Templates für '%s': %s", template_name_html, e, exc_info=True)
        return False

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

# --- Hilfsfunktionen für Benachrichtigungssystem ---
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
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("DB-Verbindungsfehler in get_user_notification_preference für User %s", user_id_int)
        return False
    # Verwendung eines try-finally Blocks, um sicherzustellen, dass die Verbindung geschlossen wird
    try:
        with cnx.cursor(dictionary=True) as cursor:
            query = """
                SELECT bba.email_aktiviert
                FROM benutzer_benachrichtigungseinstellungen bba
                JOIN benachrichtigungstypen bt ON bba.typ_id = bt.id
                WHERE bba.benutzer_id = %s AND bt.event_schluessel = %s
            """
            cursor.execute(query, (user_id_int, event_schluessel))
            result = cursor.fetchone()
            return bool(result['email_aktiviert']) if result and result['email_aktiviert'] is not None else False
    except Error as err:
        app.logger.error("DB-Fehler in get_user_notification_preference für User %s, Event %s: %s", user_id_int, event_schluessel, err)
        return False
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def get_system_setting(einstellung_schluessel: str) -> Optional[str]:
    """
    Ruft den Wert einer Systemeinstellung aus der Datenbank ab.

    Args:
        einstellung_schluessel (str): Der Schlüssel der Systemeinstellung (z.B. 'MAX_NEGATIVSALDO').

    Returns:
        Optional[str]: Der Wert der Einstellung als String, oder None wenn nicht gefunden oder bei Fehler.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("DB-Verbindungsfehler in get_system_setting für Schlüssel %s", einstellung_schluessel)
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            query = "SELECT einstellung_wert FROM system_einstellungen WHERE einstellung_schluessel = %s"
            cursor.execute(query, (einstellung_schluessel,))
            result = cursor.fetchone()
            return result['einstellung_wert'] if result else None
    except Error as err:
        app.logger.error("DB-Fehler in get_system_setting für Schlüssel %s: %s", einstellung_schluessel, err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def get_user_details_for_notification(user_id_int: int) -> Optional[dict]:
    """
    Ruft ID, Vorname und E-Mail eines Benutzers für Benachrichtigungszwecke ab.

    Args:
        user_id_int (int): Die ID des Benutzers.

    Returns:
        Optional[dict]: Ein Dictionary mit {'id': int, 'vorname': str, 'email': str} oder None bei Fehler/Nichtgefunden.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("DB-Verbindungsfehler in get_user_details_for_notification für User %s", user_id_int)
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, vorname, email FROM users WHERE id = %s", (user_id_int,))
            return cursor.fetchone()
    except Error as err:
        app.logger.error("DB-Fehler in get_user_details_for_notification für User %s: %s", user_id_int, err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def _send_saldo_null_benachrichtigung(user_id: int, vorname: str, email: str, aktueller_saldo: float, logo_pfad: str):
    """Hilfsfunktion zum Senden der "Saldo Null" Benachrichtigung."""
    if not get_user_notification_preference(user_id, 'SALDO_NULL'):
        return

    email_params = {
        'empfaenger_email': email,
        'betreff': "Ihr Saldo hat Null erreicht",
        'template_name_html': "email_saldo_null.html",
        'template_name_text': "email_saldo_null.txt",
        'template_context': {"vorname": vorname, "saldo": aktueller_saldo},
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        app.logger.info("Saldo-Null Benachrichtigung an %s (ID: %s) gesendet.", email, user_id)
    else:
        app.logger.error("Fehler beim Senden der Saldo-Null Benachrichtigung an %s (ID: %s).", email, user_id)

def _send_negativsaldo_benachrichtigung(user_id: int, vorname: str, email: str, aktueller_saldo: float, logo_pfad: str):
    """Hilfsfunktion zum Senden der "Negativsaldo" Benachrichtigung."""
    max_negativ_saldo_str = get_system_setting('MAX_NEGATIVSALDO')
    if max_negativ_saldo_str is None:
        app.logger.info("MAX_NEGATIVSALDO nicht konfiguriert, keine Negativsaldo-Prüfung für User %s.", user_id)
        return

    try:
        max_negativ_saldo = int(max_negativ_saldo_str)
    except ValueError:
        app.logger.error("Ungültiger Wert für MAX_NEGATIVSALDO ('%s') in system_einstellungen.", max_negativ_saldo_str)
        return

    if aktueller_saldo > max_negativ_saldo: # Guard clause: Wenn Saldo nicht niedrig genug ist, abbrechen
        return

    if not get_user_notification_preference(user_id, 'NEGATIVSALDO_GRENZE'): # Guard clause: Wenn User es nicht will, abbrechen
        return

    # Alle Prüfungen bestanden, E-Mail senden
    email_params = {
        'empfaenger_email': email,
        'betreff': "Wichtiger Hinweis zu deinem Saldo",
        'template_name_html': "email_negativsaldo_warnung.html",
        'template_name_text': "email_negativsaldo_warnung.txt",
        'template_context': {"vorname": vorname, "saldo": aktueller_saldo, "grenzwert": max_negativ_saldo},
        'logo_dateipfad': logo_pfad
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        app.logger.info("Negativsaldo-Warnung an %s (ID: %s) gesendet.", email, user_id)
    else:
        app.logger.error("Fehler beim Senden der Negativsaldo-Warnung an %s (ID: %s).", email, user_id)

def aktuellen_saldo_pruefen_und_benachrichtigen(target_user_id: int):
    """
    Prüft den aktuellen Saldo eines Benutzers nach einer Transaktion und versendet ggf.
    E-Mail-Benachrichtigungen für "Saldo erreicht Null" oder "Negativsaldo-Grenze erreicht",
    basierend auf den Benutzereinstellungen und Systemeinstellungen.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Saldo geprüft werden soll.
    """
    user_details = get_user_details_for_notification(target_user_id)
    if not user_details:
        app.logger.warning("Benutzerdetails für ID %s nicht gefunden in aktuellen_saldo_pruefen_und_benachrichtigen.", target_user_id)
        return

    user_vorname = user_details.get('vorname', '') # Default, falls 'vorname' fehlt
    user_email = user_details.get('email')

    if not user_email:
        app.logger.info("Benutzer %s hat keine E-Mail-Adresse hinterlegt. Keine Saldo-Benachrichtigungen möglich.", target_user_id)
        return

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("DB-Verbindungsfehler in aktuellen_saldo_pruefen_und_benachrichtigen für User %s", target_user_id)
        return

    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (target_user_id,))
            saldo_data = cursor.fetchone()
            aktueller_saldo = saldo_data['saldo'] if saldo_data and saldo_data['saldo'] is not None else 0.0 # Sicherstellen, dass es ein Float ist

        logo_pfad_str = str(Path("static/logo/logo-80x109.png"))

        if aktueller_saldo == 0:
            _send_saldo_null_benachrichtigung(target_user_id, user_vorname, user_email, aktueller_saldo, logo_pfad_str)

        _send_negativsaldo_benachrichtigung(target_user_id, user_vorname, user_email, aktueller_saldo, logo_pfad_str)

    except Error as err:
        app.logger.error("DB-Fehler in aktuellen_saldo_pruefen_und_benachrichtigen für User %s: %s", target_user_id, err)
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


def get_user_by_api_key(api_key_value: str) -> Optional[tuple[int, str]]: # api_key umbenannt
    """
    Ruft den Benutzer anhand des API-Schlüssels aus der Datenbank ab.

    Args:
        api_key_value (str): Der API-Schlüssel des Benutzers.

    Returns:
        Optional[tuple[int, str]]: Ein Tupel mit (user_id, username) oder None.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    try:
        with cnx.cursor() as cursor: # Kein dictionary=True nötig, da Indizes verwendet werden
            cursor.execute(
                "SELECT u.id, u.username FROM api_users u JOIN api_keys ak ON u.id = ak.user_id " \
                "WHERE ak.api_key = %s", (api_key_value,))
            user = cursor.fetchone()
            return (user[0], user[1]) if user else None
    except Error as err:
        app.logger.error("Fehler beim Abrufen des Benutzers anhand des API-Schlüssels: %s.", err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def api_key_required(f):
    """
    Prüfe auf gültigen API-Key.

    Args:
        f (callable): Die zu dekorierende Funktion.

    Returns:
        callable: Die dekorierte Funktion.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key_header = request.headers.get('X-API-Key')
        if not api_key_header:
            app.logger.warning("API-Zugriff ohne API-Schlüssel.")
            return jsonify({'message': 'API-Schlüssel fehlt!'}), 401

        user_data = get_user_by_api_key(api_key_header) # user_id, username
        if not user_data:
            app.logger.warning("API-Zugriff mit ungültigem API-Schlüssel: %s", api_key_header)
            return jsonify({'message': 'Ungültiger API-Schlüssel!'}), 401

        # user_data[0] ist user_id, user_data[1] ist username
        return f(user_data[0], user_data[1], *args, **kwargs)
    return decorated

def finde_benutzer_zu_nfc_token(token_base64: str) -> Optional[dict]:
    """
    Findet einen Benutzer in der Datenbank anhand der Base64-kodierten Daten eines NFC-Tokens.
    Beinhaltet jetzt auch die E-Mail-Adresse des Benutzers.

    Args:
        token_base64 (str): Die Base64-kodierte NFC-Daten des Tokens.

    Returns:
        Optional[dict]: Ein Dictionary mit den Benutzerdaten (id, nachname, vorname, email, token_id)
                        oder None, falls kein Benutzer gefunden wird.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            try:
                token_bytes = base64.b64decode(token_base64)
            except base64.binascii.Error:
                app.logger.error("Ungültiger Base64-String in finde_benutzer_zu_nfc_token: %s", token_base64)
                return None

            query = """
                SELECT u.id AS id, u.nachname AS nachname, u.vorname AS vorname, u.email AS email, t.token_id as token_id
                FROM nfc_token AS t
                INNER JOIN users AS u ON t.user_id = u.id
                WHERE t.token_daten = %s
            """
            cursor.execute(query, (token_bytes,))
            user = cursor.fetchone()
            if user:
                app.logger.info("Benutzer via NFC gefunden: ID %s - %s %s (TokenID: %s, Email: %s)",
                                user['id'], user['vorname'], user['nachname'], user['token_id'], user.get('email'))
            return user
    except Error as err:
        app.logger.error("DB-Fehler in finde_benutzer_zu_nfc_token: %s", err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def _send_new_transaction_email(user_details: Dict[str, Any], transaction_details: Dict[str, Any]):
    """
    Hilfsfunktion zum Senden der "Neue Transaktion" E-Mail.
    Nimmt Benutzer- und Transaktionsdetails als Dictionaries entgegen.

    Args:
        user_details (Dict[str, Any]): Enthält 'email', 'vorname', 'id' des Benutzers.
        transaction_details (Dict[str, Any]): Enthält 'beschreibung', 'saldo_aenderung', 'neuer_saldo'.
    """

    email_params = {
        'empfaenger_email': user_details['email'],
        'betreff': "Neue Transaktion auf deinem Konto",
        'template_name_html': "email_neue_transaktion.html",
        'template_name_text': "email_neue_transaktion.txt",
        'template_context': {
            "vorname": user_details['vorname'],
            "beschreibung_transaktion": transaction_details['beschreibung'],
            "saldo_aenderung": transaction_details['saldo_aenderung'],
            "neuer_saldo": transaction_details['neuer_saldo'],
            "datum": transaction_details['datum'],
            "uhrzeit": transaction_details['uhrzeit']
        },
        'logo_dateipfad': str(Path("static/logo/logo-80x109.png"))
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        app.logger.info("Neue Transaktion E-Mail an %s (ID: %s) gesendet.", user_details['email'], user_details['id'])
    else:
        app.logger.error("Fehler beim Senden der Neue Transaktion E-Mail an %s (ID: %s).", user_details['email'], user_details['id'])


@app.route('/health-protected', methods=['GET'])
@api_key_required
def health_protected_route(api_user_id: int, api_username: str): # Parameter umbenannt für Konsistenz
    """
    Healthcheck gegen die Datenbank (nur für authentifizierte Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Healthcheck-Status und Benutzerinformationen.
    """
    app.logger.debug("API-Benutzer authentifiziert: ID %s - %s", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("Datenbankverbindung fehlgeschlagen im Healthcheck.")
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    # Einfache Operation, um die Verbindung zu testen, z.B. SELECT 1
    try:
        with cnx.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        app.logger.debug("Datenbankverbindung erfolgreich für Healthcheck. Authentifizierter API-Benutzer: ID %s - %s", api_user_id, api_username)
        return jsonify({'message': f"Healthcheck OK! Authentifizierter API-Benutzer ID {api_user_id} ({api_username})."})
    except Error as err:
        app.logger.error("Datenbankfehler während Healthcheck: %s", err)
        return jsonify({'error': 'Datenbankfehler während Healthcheck.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/users', methods=['GET'])
@api_key_required
def get_all_users(api_user_id: int, api_username: str):
    """
    Gibt eine Liste aller angelegten Benutzer mit ihrem Code, Nachnamen und Vornamen zurück.
    (Nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste von Benutzern
                        (jeder Benutzer als Dictionary mit 'code', 'nachname', 'vorname')
                        oder einem Fehler.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe alle Benutzer ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    try:
        with cnx.cursor(dictionary=True) as cursor:
            query = "SELECT code, nachname, vorname FROM users ORDER BY nachname, vorname;"
            cursor.execute(query)
            users_list = cursor.fetchall() # Umbenannt von users
        app.logger.info("%s Benutzer erfolgreich aus der Datenbank abgerufen.", len(users_list))
        return jsonify(users_list), 200
    except Error as err:
        app.logger.error("Fehler beim Abrufen aller Benutzer aus der Datenbank: %s", err)
        return jsonify({'error': f"Fehler beim Abrufen der Benutzerdaten: {err}"}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/nfc-transaktion', methods=['PUT'])
@api_key_required
def nfc_transaction(api_user_id_auth: int, api_username_auth: str):
    """
    Verarbeitet eine NFC-Transaktion. Ordnet die Tokendaten einem Benutzer zu,
    verbucht -1 Saldo und löst ggf. E-Mail-Benachrichtigungen aus.

    Args:
        api_user_id_auth (int): Die ID des authentifizierten API-Benutzers.
        api_username_auth (str): Der Benutzername des authentifizierten API-Benutzers.
    Body (JSON): {"token": "BASE64_TOKEN", "beschreibung": "text"}
    Returns: flask.Response
    """
    app.logger.info("NFC-Transaktion Anfrage von API-Benutzer: ID %s - %s.", api_user_id_auth, api_username_auth)
    daten = request.get_json()
    if not daten or 'token' not in daten or 'beschreibung' not in daten:
        return jsonify({'error': 'Ungültige Anfrage. Token und Beschreibung sind erforderlich.'}), 400

    benutzer_info = finde_benutzer_zu_nfc_token(daten['token'])
    if not benutzer_info:
        return jsonify({'error': f"Kein Benutzer mit dem Token {daten['token']} gefunden."}), 404

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    neuer_saldo = 0 # Default Wert
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("UPDATE nfc_token SET last_used = NOW() WHERE token_id = %s", (int(benutzer_info['token_id']),))

            trans_saldo_aenderung_str = get_system_setting('TRANSACTION_SALDO_CHANGE')
            if trans_saldo_aenderung_str is None:
                app.logger.info("TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User %s.", user_id)
                return

            try:
                trans_saldo_aenderung = int(trans_saldo_aenderung_str)
            except ValueError:
                app.logger.error("Ungültiger Wert für TRANSACTION_SALDO_CHANGE ('%s') in system_einstellungen.", trans_saldo_aenderung_str)
                return

            cursor.execute("INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)",
                           (benutzer_info['id'], daten['beschreibung'], trans_saldo_aenderung))
            cnx.commit()
            app.logger.info("Transaktion für %s (ID: %s), '%s', Saldo: %s erfolgreich erstellt.",
                            benutzer_info['vorname'], benutzer_info['id'], daten['beschreibung'], trans_saldo_aenderung)

            cursor.execute("SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (benutzer_info['id'],))
            saldo_row = cursor.fetchone()
            neuer_saldo = saldo_row['saldo'] if saldo_row and saldo_row['saldo'] is not None else 0

        # Außerhalb des 'with cursor' Blocks, da DB Operationen darin abgeschlossen sein sollten.
        if benutzer_info.get('email') and get_user_notification_preference(benutzer_info['id'], 'NEUE_TRANSAKTION'):
            jetzt = datetime.datetime.now()
            user_details_for_email = {
                'email': benutzer_info['email'],
                'vorname': benutzer_info.get('vorname', ''),
                'id': benutzer_info['id']
            }
            transaction_details_for_email = {
                'beschreibung': daten['beschreibung'],
                'saldo_aenderung': trans_saldo_aenderung,
                'neuer_saldo': neuer_saldo,
                'datum': jetzt.strftime("%d.%m.%Y"),
                'uhrzeit': jetzt.strftime("%H:%M")
            }
            _send_new_transaction_email(user_details_for_email, transaction_details_for_email)
        aktuellen_saldo_pruefen_und_benachrichtigen(benutzer_info['id'])

        return jsonify({'message': f"Danke {benutzer_info['vorname']}. Dein aktueller Saldo beträgt: {neuer_saldo}."}), 200

    except Error as err:
        if cnx.is_connected(): # Nur rollback wenn Verbindung noch besteht
            cnx.rollback()
        app.logger.error("Fehler bei NFC-Transaktion für User %s: %s", benutzer_info.get('id', 'Unbekannt'), err)
        return jsonify({'error': 'Fehler bei der Transaktionsverarbeitung.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person/<string:code>/transaktion', methods=['PUT'])
@api_key_required
def person_transaktion_erstellen(api_user_id_auth: int, api_username_auth: str, code: str):
    """
    Erstellt eine manuelle Transaktion für einen Benutzer anhand seines Codes.
    Löst ggf. E-Mail-Benachrichtigungen aus.

    Args:
        api_user_id_auth (int): Die ID des authentifizierten API-Benutzers.
        api_username_auth (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der Person.

    Body (JSON): {"beschreibung": "text", "saldo_aenderung": number}

    Returns: flask.Response
    """

    app.logger.info("Manuelle Transaktion für Code %s von API-Benutzer: ID %s - %s.", code, api_user_id_auth, api_username_auth)
    daten = request.get_json()
    if not daten or 'beschreibung' not in daten:
        return jsonify({'error': 'Ungültige Anfrage. Beschreibung ist erforderlich.'}), 400

    trans_saldo_aenderung_str = get_system_setting('TRANSACTION_SALDO_CHANGE')
    if trans_saldo_aenderung_str is None:
        app.logger.info("TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User %s.", user_id)
        return

    user_info = get_user_details_for_notification_by_code(code)
    if not user_info:
        return jsonify({'error': f"Person mit Code {code} nicht gefunden."}), 404

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    neuer_saldo = 0 # Default Wert
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)",
                           (user_info['id'], daten['beschreibung'], trans_saldo_aenderung))
            cnx.commit()
            app.logger.info("Manuelle Transaktion für %s (ID: %s, Code: %s), '%s', Saldo: %s erfolgreich erstellt.",
                            user_info['vorname'], user_info['id'], code, daten['beschreibung'], trans_saldo_aenderung)

            cursor.execute("SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (user_info['id'],))
            saldo_row = cursor.fetchone()
            neuer_saldo = saldo_row['saldo'] if saldo_row and saldo_row['saldo'] is not None else 0

        # Außerhalb des 'with cursor' Blocks
        if user_info.get('email') and get_user_notification_preference(user_info['id'], 'NEUE_TRANSAKTION'):
            jetzt = datetime.datetime.now()
            user_details_for_email = {
                'email': user_info['email'],
                'vorname': user_info.get('vorname', ''),
                'id': user_info['id']
            }
            transaction_details_for_email = {
                'beschreibung': daten['beschreibung'],
                'saldo_aenderung': trans_saldo_aenderung,
                'neuer_saldo': neuer_saldo,
                'datum': jetzt.strftime("%d.%m.%Y"),
                'uhrzeit': jetzt.strftime("%H:%M")
            }
            _send_new_transaction_email(user_details_for_email, transaction_details_for_email)
        aktuellen_saldo_pruefen_und_benachrichtigen(user_info['id'])

        return jsonify({'message': f"Transaktion für {user_info['vorname']} (Code {code}) erfolgreich erstellt. Neuer Saldo: {neuer_saldo}."}), 201

    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        app.logger.error("Fehler bei manueller Transaktion für Code %s: %s", code, err)
        return jsonify({'error': 'Fehler beim Erstellen der Transaktion.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

def get_user_details_for_notification_by_code(code_val: str) -> Optional[dict]: # code umbenannt
    """
    Ruft ID, Vorname und E-Mail eines Benutzers anhand seines Codes ab.

    Args:
        code_val (str): Der Benutzercode.

    Returns:
        Optional[dict]: Ein Dictionary mit {'id': int, 'vorname': str, 'email': str} oder None.
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        app.logger.error("DB-Verbindungsfehler in get_user_details_for_notification_by_code für Code %s", code_val)
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, vorname, email FROM users WHERE code = %s", (code_val,))
            return cursor.fetchone()
    except Error as err:
        app.logger.error("DB-Fehler in get_user_details_for_notification_by_code für Code %s: %s", code_val, err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/saldo-alle', methods=['GET'])
@api_key_required
def get_alle_summe(api_user_id: int, api_username: str):
    """
    Gibt das Saldo aller Personen in der Datenbank zurück (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste von Benutzern und ihrem Saldo.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe Saldo aller Personen ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT u.id, u.nachname AS nachname, u.vorname AS vorname, SUM(t.saldo_aenderung) AS saldo " \
                "FROM users AS u LEFT JOIN transactions AS t ON u.id = t.user_id GROUP BY u.id, u.nachname, u.vorname ORDER BY saldo DESC, u.nachname, u.vorname;")
            personen_saldo = cursor.fetchall()
        app.logger.info("Saldo aller Personen wurde ermittelt (%s Einträge).", len(personen_saldo))
        return jsonify(personen_saldo)
    except Error as err:
        app.logger.error("Fehler beim Lesen der Saldo-Daten: %s", err)
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/transaktionen', methods=['GET'])
@api_key_required
def get_alle_transaktionen(api_user_id: int, api_username: str): # Funktionsname angepasst
    """
    Gibt alle Transaktionen in der Datenbank zurück, angereichert mit Benutzerinformationen
    (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste aller Transaktionen mit Benutzerinformationen.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe alle Transaktionen ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT t.id, u.nachname AS nachname, u.vorname AS vorname, t.beschreibung, t.timestamp FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id ORDER BY t.timestamp DESC;")
            transaktionen_liste = cursor.fetchall() # Umbenannt
        app.logger.info("Alle Transaktionen wurden ermittelt (%s Einträge).", len(transaktionen_liste))
        return jsonify(transaktionen_liste)
    except Error as err:
        app.logger.error("Fehler beim Lesen der Transaktionsdaten: %s", err)
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/transaktionen', methods=['DELETE'])
@api_key_required
def reset_transaktionen(api_user_id: int, api_username: str): # Parameter umbenannt
    """
    Löscht die Transaktionen für alle hinterlegten Personen (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Lösche alle Transaktionen.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor() as cursor:
            sql = "TRUNCATE TABLE transactions;"
            cursor.execute(sql)
            cnx.commit()
        app.logger.info("Alle Transaktionen wurden gelöscht.")
        return jsonify({'message': 'Alle Transaktionen wurden gelöscht.'}), 200
    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        app.logger.error("Fehler beim Leeren der Tabelle transactions: %s", err)
        return jsonify({'error': 'Fehler beim Leeren der Tabelle transactions.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person', methods=['POST'])
@api_key_required
def create_person(api_user_id: int, api_username: str): # Parameter umbenannt
    """
    Fügt eine neue Person zur Datenbank hinzu (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
    Body (JSON): {"code": "...", "nachname": "...", "vorname": "...", "password": "..."}
    Returns: flask.Response
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Erstelle neue Person.", api_user_id, api_username)
    daten = request.get_json()
    if not daten or 'code' not in daten or 'nachname' not in daten or 'vorname' not in daten:
        return jsonify({'error': 'Ungültige oder unvollständige Daten. Code, Nachname, Vorname sind erforderlich.'}), 400

    code_val = daten['code']
    nachname_val = daten['nachname']
    vorname_val = daten['vorname']
    password_val = daten.get('password', '') # Passwort ist optional, default leer

    if not isinstance(code_val, str) or len(code_val) != 10 or not code_val.isdigit():
        return jsonify({'error': 'Der Code muss ein 10-stelliger Zahlencode sein.'}), 400
    if not isinstance(nachname_val, str) or not nachname_val.strip() or \
       not isinstance(vorname_val, str) or not vorname_val.strip():
        return jsonify({'error': 'Vorname und Nachname dürfen nicht leer sein.'}), 400

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor() as cursor:
            # Annahme: `password` in `users` Tabelle kann auch leer sein oder hat einen Default-Wert.
            # Wenn Passwort-Hashing in der GUI geschieht, hier Klartext oder Hash speichern.
            sql = "INSERT IGNORE INTO users (code, nachname, vorname, password) VALUES (%s, %s, %s, %s)"
            werte = (code_val, nachname_val, vorname_val, password_val)
            cursor.execute(sql, werte)
            cnx.commit()
        app.logger.info("Person mit Code %s erfolgreich hinzugefügt.", code_val)
        return jsonify({'message': f"Person mit Code {code_val} erfolgreich hinzugefügt."}), 201
    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        app.logger.error("Fehler beim Hinzufügen der Person mit Code %s: %s", code_val, err)
        return jsonify({'error': 'Fehler beim Hinzufügen der Person.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person/<string:code>', methods=['DELETE'])
@api_key_required
def delete_person(api_user_id: int, api_username: str, code: str): # Parameter umbenannt
    """
    Person aus der Datenbank löschen (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der zu löschenden Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Lösche Person mit Code %s.", api_user_id, api_username, code)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor() as cursor:
            sql = "DELETE FROM users WHERE code = %s"
            cursor.execute(sql, (code,))
            cnx.commit()
            if cursor.rowcount > 0:
                app.logger.info("Person mit Code %s erfolgreich gelöscht.", code)
                return jsonify({'message': f"Person mit Code {code} erfolgreich gelöscht."}), 200
            app.logger.warning("Keine Person mit dem Code %s zum Löschen gefunden.", code)
            return jsonify({'error': f"Keine Person mit dem Code {code} gefunden."}), 404
    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        app.logger.error("Fehler beim Löschen der Person mit Code %s: %s", code, err)
        return jsonify({'error': 'Fehler beim Löschen der Person.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person/existent/<string:code>', methods=['GET'])
@api_key_required
def person_exists_by_code(api_user_id: int, api_username: str, code: str): # Parameter umbenannt
    """
    Prüft anhand ihres 10-stelligen Codes, ob eine Person existiert (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Namen der Person oder einem Fehler.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Prüfe Existenz von Person mit Code %s.", api_user_id, api_username, code)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT nachname, vorname FROM users WHERE code = %s", (code,))
            person = cursor.fetchone()
        if person:
            app.logger.info("Person mit Code %s gefunden: %s, %s", code, person['nachname'], person['vorname'])
            return jsonify(person)
        app.logger.info("Person mit Code %s nicht gefunden.", code)
        return jsonify({'error': 'Person nicht gefunden.'}), 404
    except Error as err:
        app.logger.error("Fehler beim Lesen der Daten für Code %s: %s", code, err)
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person/<string:code>', methods=['GET'])
@api_key_required
def get_person_by_code(api_user_id: int, api_username: str, code: str): # Parameter umbenannt
    """
    Gibt Daten einer Person anhand ihres 10-stelligen Codes zurück (nur für authentifizierte API-Benutzer).
    Beinhaltet Name, Vorname und aktuellen Saldo.

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit den Personendaten (Name, Vorname, Saldo) oder einem Fehler.
    """
    app.logger.info("Abfrage für Person mit Code %s von API-Benutzer: ID %s - %s.", code, api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, nachname, vorname FROM users WHERE code = %s", (code,))
            person_info = cursor.fetchone()

            if not person_info:
                app.logger.info("Person mit Code %s nicht gefunden.", code)
                return jsonify({'error': 'Person nicht gefunden.'}), 404

            cursor.execute(
                "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (person_info['id'],)
            )
            saldo_data = cursor.fetchone()
            aktueller_saldo = saldo_data['saldo'] if saldo_data and saldo_data['saldo'] is not None else 0.0

        response_data = {
            "nachname": person_info['nachname'],
            "vorname": person_info['vorname'],
            "saldo": aktueller_saldo
        }
        app.logger.info("Person mit Code %s gefunden: %s, %s - Saldo %s", code, response_data['nachname'], response_data['vorname'], response_data['saldo'])
        return jsonify(response_data)

    except Error as err:
        app.logger.error("DB-Fehler bei Abfrage von Person mit Code %s: %s", code, err)
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

@app.route('/person/transaktionen/<string:code>', methods=['DELETE'])
@api_key_required
def person_transaktionen_loeschen(api_user_id: int, api_username: str, code: str): # Parameter umbenannt
    """
    Ermittelt eine Person anhand des übermittelten Codes und löscht die verknüpften Transaktionen.

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der Person, deren Transaktionen gelöscht werden sollen.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """
    app.logger.info("API-Benutzer authentifiziert: ID %s - %s. Lösche Transaktionen für Code %s.", api_user_id, api_username, code)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    target_user_id_for_delete = None # Initialisieren für den Fall, dass der Benutzer nicht gefunden wird
    try:
        with cnx.cursor() as cursor: # Kein dictionary=True nötig für ID-Abfrage
            cursor.execute("SELECT id FROM users WHERE code = %s", (code,))
            user_data_row = cursor.fetchone()
            if not user_data_row:
                app.logger.warning("Person mit Code %s nicht gefunden, keine Transaktionen zum Löschen.", code)
                return jsonify({'error': 'Person mit diesem Code nicht gefunden.'}), 404

            target_user_id_for_delete = user_data_row[0]
            cursor.execute("DELETE FROM transactions WHERE user_id = %s", (target_user_id_for_delete,))
            cnx.commit()

        app.logger.info("Transaktionen für Benutzer mit Code %s (ID: %s) erfolgreich gelöscht.", code, target_user_id_for_delete)
        return jsonify({'message': 'Transaktionen erfolgreich gelöscht.'}), 200
    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        user_id_log = target_user_id_for_delete if target_user_id_for_delete is not None else "Unbekannt (Benutzer nicht gefunden)"
        app.logger.error("Fehler beim Löschen der Transaktionen für Code %s (User ID: %s): %s", code, user_id_log, err)
        return jsonify({'error': 'Fehler beim Löschen der Transaktion.'}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)

if __name__ == '__main__':
    # Logging-Konfiguration
    if not app.debug:
        import logging
        from logging.handlers import RotatingFileHandler
        try:
            # Sicherstellen, dass der logs-Ordner existiert
            log_dir = Path("logs")
            log_dir.mkdir(exist_ok=True)
            log_file_path = log_dir / 'api_activity.log'

            file_handler = RotatingFileHandler(log_file_path, maxBytes=1024 * 1024 * 10, backupCount=5, encoding='utf-8')
            #file_handler.setLevel(logging.INFO)
            file_handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s [in %(pathname)s:%(lineno)d]')
            file_handler.setFormatter(formatter)

            # Standard-Handler entfernen, falls vorhanden, um doppeltes Logging zu vermeiden
            if app.logger.hasHandlers():
                app.logger.handlers.clear()

            app.logger.addHandler(file_handler)
            app.logger.setLevel(logging.INFO)
            app.logger.info("API-Logging in Datei %s konfiguriert.", log_file_path)
        except Exception as e: # pylint: disable=W0718
            # Fallback auf print, wenn Logger-Konfiguration fehlschlägt
            print(f"Kritischer Fehler bei der Konfiguration des File-Loggings: {e}")

    # Konfigurationsprüfungen
    required_db_keys = ['host', 'port', 'user', 'password', 'database']
    if not all(key in config.db_config and config.db_config[key] is not None for key in required_db_keys):
        app.logger.critical("Fehler: Nicht alle Datenbank-Konfigurationsvariablen sind gesetzt. Benötigt: %s", ", ".join(required_db_keys))
        sys.exit(1)

    try:
        config.db_config['port'] = int(config.db_config['port'])
    except ValueError:
        app.logger.critical("Fehler: Datenbank-Port '%s' ist keine gültige Zahl.", config.db_config.get('port'))
        sys.exit(1)

    required_smtp_keys = ['host', 'port', 'user', 'password', 'sender']
    if not all(key in config.smtp_config and config.smtp_config[key] is not None for key in required_smtp_keys):
        app.logger.critical("Fehler: Nicht alle SMTP-Konfigurationsvariablen sind gesetzt. Benötigt: %s", ", ".join(required_smtp_keys))
        sys.exit(1)

    try:
        config.smtp_config['port'] = int(config.smtp_config['port'])
    except ValueError:
        app.logger.critical("Fehler: SMTP_PORT '%s' ist keine gültige Zahl.", config.smtp_config.get('port'))
        sys.exit(1)

    app.logger.info("Feuerwehr-Versorgungs-Helfer API wird gestartet...")
    app.run(host=config.api_config['host'], port=config.api_config['port'], debug=config.api_config['debug_mode'])




# TODO
# nfc_transaction und person_transaktion_erstellen sollen die Einstellung für TRANSACTION_SALDO_CHANGE aus der DB lesen
# und dann diesen Betrag vom Saldo abziehen.
#
# all_db_setting_keys = get_all_system_settings().keys()
#system_settings_data = get_all_system_settings()
