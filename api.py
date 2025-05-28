"""Dieses Modul ist eine API Middleware für den Feuerwehr-Versorgungs-Helfer"""

import base64
import sys
from functools import wraps
from pathlib import Path # Für die Logo-Pfadprüfung
from flask import Flask, jsonify, request, render_template # pigar: required-packages=uWSGI
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
except Error:
    print("Fehler beim Starten der Datenbankverbindung.")
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
    logo_dateipfad = email_params.get('logo_dateipfad')

    if not all([empfaenger_email, betreff, template_name_html, template_name_text]):
        app.logger.error("Fehler: Unvollständige E-Mail-Parameter. Benötigt: empfaenger_email, betreff, template_name_html, template_name_text.")
        return False

    try:
        # Kontext für Templates erweitern
        template_context_final = template_context.copy()
        template_context_final['logo_exists_fuer_template'] = bool(logo_dateipfad and Path(logo_dateipfad).is_file())

        # Templates mit Flasks render_template rendern
        with app.app_context(): # Stellt sicher, dass render_template funktioniert
            final_html_body = render_template(template_name_html, **template_context_final)
            final_text_body = render_template(template_name_text, **template_context_final)

    except Exception as e:  # pylint: disable=W0718
        print(f"Fehler beim Rendern der E-Mail-Templates: {e}")
        return False

    email_content_dict = {
        'html': final_html_body,
        'text': final_text_body,
        'logo_pfad': logo_dateipfad if logo_dateipfad and Path(logo_dateipfad).is_file() else None
    }

    return email_sender.sende_formatierte_email(
        empfaenger_email=empfaenger_email,
        betreff=betreff,
        content=email_content_dict,
        smtp_cfg=smtp_cfg
    )


def send_friendly_reminder_mail(email, vorname, saldo):
    """
    Versendet eine freundliche Erinnerungs-E-Mail mit Saldoinformationen.

    Verwendet vordefinierte Templates (email_friendly_reminder.html/.txt)
    und ein Logo, um eine formatierte E-Mail zu erstellen. Die SMTP-Konfiguration
    wird aus `config.smtp_config` bezogen.

    Args:
        email (str): Die E-Mail-Adresse des Empfängers.
        vorname (str): Der Vorname des Empfängers für die persönliche Anrede.
        saldo (str): Der aktuelle Saldo des Empfängers, der in der E-Mail angezeigt wird.

    Returns:
        bool: True, wenn die E-Mail erfolgreich versendet wurde, sonst False.
    """

    logo_pfad = Path("static/logo/logo-80x109.png")

    # Parameter für die E-Mail
    email_details = {
        'empfaenger_email': email,
        'betreff': "Kleiner Hinweis zu deinem Guthaben (Getränke & Essen)",
        'template_name_html': "email_friendly_reminder.html",
        'template_name_text': "email_friendly_reminder.txt",
        'template_context': {
            "vorname": vorname,
            "saldo": saldo,
        },
        'logo_dateipfad': str(logo_pfad) if logo_pfad.is_file() else None,
    }

    erfolg = prepare_and_send_email(email_params=email_details, smtp_cfg=config.smtp_config)

    if erfolg:
        return True
    return False


def aktuellen_saldo_pruefen(user_id):
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT u.nachname AS nachname, u.vorname AS vorname, u.email AS email, SUM(t.saldo_aenderung) AS saldo " \
            "FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id WHERE u.id = %s GROUP BY u.nachname, u.vorname", (user_id,))
        person = cursor.fetchone()
        if person:
            print(f"Person mit UID {user_id} gefunden: {person['nachname']}, {person['vorname']} (Email: {person['email']}) - Saldo {person['saldo']}")
            if person['saldo'] <= config.saldo_grenzwert: # Email nur senden wenn der Saldo unter dem Grenzwert liegt
                send_friendly_reminder_mail(person['email'], person['vorname'], person['saldo'])
            return jsonify(person)
        print(f"Person mit UID {user_id} hat noch keine Transaktionen durchgeführt.")
        return jsonify({'error': 'Person hat noch keine Transaktionen durchgeführt.'}), 200
    except Error as err:
        print(f"Fehler beim Lesen der Daten: {err}")
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


def get_user_by_api_key(api_key):
    """
    Ruft den Benutzer anhand des API-Schlüssels aus der Datenbank ab.

    Args:
        api_key (str): Der API-Schlüssel des Benutzers.

    Returns:
        tuple or None: Ein Tupel mit (user_id, username) oder None, falls kein Benutzer gefunden wird oder ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None, None
    cursor = cnx.cursor()

    try:
        cursor.execute(
            "SELECT u.id, u.username FROM api_users u JOIN api_keys ak ON u.id = ak.user_id " \
            "WHERE ak.api_key = %s", (api_key,))
        user = cursor.fetchone()
        if user:
            return user[0], user[1]  # user_id, username
        return None, None
    except Error as err:
        print(
            f"Fehler beim Abrufen des Benutzers anhand des API-Schlüssels: {err}.")
        return None, None
    finally:
        cursor.close()
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
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            print("Kein API-Schlüssel angegeben!")
            return jsonify({'message': 'API-Schlüssel fehlt!'}), 401
        user_id, username = get_user_by_api_key(api_key)
        if not user_id:
            print("Ungültiger API-Schlüssel!")
            return jsonify({'message': 'Ungültiger API-Schlüssel!'}), 401
        return f(user_id, username, *args, **kwargs)
    return decorated


def finde_benutzer_zu_nfc_token(token_base64):
    """
    Findet einen Benutzer in der Datenbank anhand der Base64-kodierten Daten eines NFC-Tokens.

    Args:
        token_base64 (str): Die Base64-kodierte NFC-Daten des Tokens.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, nachname, vorname, token_id) oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    cursor = cnx.cursor(dictionary=True)

    try:
        token_bytes = base64.b64decode(token_base64)

        cursor.execute("SELECT u.id AS id, u.nachname AS nachname, u.vorname AS vorname, t.token_id as token_id " \
        "FROM nfc_token AS t INNER JOIN users AS u ON t.user_id = u.id WHERE t.token_daten = %s", (token_bytes,))
        user = cursor.fetchone()
        if user:
            print(f"Benutzer: {user['id']} - {user['vorname']}, {user['nachname']} (TokenID: {user['token_id']})") # ID, Nachnachme, Vorname, TokenID
            return user
        return None
    except Error as err:
        print(f"Fehler beim Suchen des Benutzers anhand des Tokens: {err}")
        return None
    except base64.binascii.Error:
        print(f"Fehler: Ungültiger Base64-String: {token_base64}")
        return None
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/health-protected', methods=['GET'])
@api_key_required
def health_protected_route(user_id, username):
    """
    Healthcheck gegen die Datenbank (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Healthcheck-Status und Benutzerinformationen.
    """

    print(f"API-Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        print("Datenbankverbindung fehlgeschlagen")
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    print(f"Datenbankverbindung erfolgreich. Authentifizierter Benutzer {user_id} - {username}")
    try:
        return jsonify({'message': f'Healthcheck OK! Authentifizierter Benutzer ID {user_id} ({username}).'})
    finally:
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/users', methods=['GET'])
@api_key_required
def get_all_users(api_user_id, api_username):
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
    print(f"API-Benutzer authentifiziert: {api_user_id} - {api_username}. Rufe alle Benutzer ab.")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500

    cursor = cnx.cursor(dictionary=True)
    try:
        query = "SELECT code, nachname, vorname FROM users ORDER BY nachname, vorname;"
        cursor.execute(query)
        users = cursor.fetchall()
        print(f"{len(users)} Benutzer erfolgreich aus der Datenbank abgerufen.")
        return jsonify(users), 200
    except Error as err:
        print(f"Fehler beim Abrufen aller Benutzer aus der Datenbank: {err}")
        return jsonify({'error': f'Fehler beim Abrufen der Benutzerdaten: {err}'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/saldo-alle', methods=['GET'])
@api_key_required
def get_alle_summe(user_id, username):
    """
    Gibt das Saldo aller Personen in der Datenbank zurück (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste von Benutzern und ihrem Saldo.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}.")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor(dictionary=True)

    try:
        cursor.execute(
            "SELECT u.nachname AS nachname, u.vorname AS vorname, SUM(t.saldo_aenderung) AS saldo " \
            "FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id GROUP BY u.nachname, u.vorname ORDER BY saldo DESC;")
        personen = cursor.fetchall()
        print("Das Saldo aller Personen wurde ermittelt.")
        return jsonify(personen)
    except Error as err:
        print(f"Fehler beim Lesen der Daten: {err}.")
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/nfc-transaktion', methods=['PUT'])
@api_key_required
def nfc_transaction(user_id, username):
    """
    Verarbeitet eine NFC-Transaktion, indem die übermittelten Tokendaten (ATS oder UID) einem Benutzer zugeordnet
    und -1 Saldo  in der Datenbank vermerkt wird.

    Args:
        user_id (int): Die ID des authentifizierten API-Benutzers.
        username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}.")
    daten = request.get_json()
    if not daten or 'token' not in daten:
        return jsonify({'error': 'Ungültige Anfrage. Die Daten des NFC-Tokens fehlen.'}), 400

    nfc_token = daten['token']
    beschreibung = daten['beschreibung']

    benutzer = finde_benutzer_zu_nfc_token(nfc_token)
    # (id, nachname, vorname, token_id)
    if benutzer:
        cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
        if not cnx:
            return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
        cursor = cnx.cursor(dictionary=True)

        try:
            sql_transaktion = "UPDATE nfc_token SET last_used = NOW() WHERE token_id = %s"
            cursor.execute(sql_transaktion, (int(benutzer['token_id']),))
            cnx.commit()
        except Error as err:
            cnx.rollback()
            print(f"Fehler beim Aktualisieren der zuletzt verwendet Zeit des NFC-Tokens: {err}")
            return jsonify({'error': 'Fehler beim Aktualisieren der zuletzt verwendet Zeit des NFC-Tokens.'}), 500

        try:
            saldo_aenderung = -1
            sql_transaktion = "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)"
            werte_transaktion = (benutzer['id'], beschreibung, saldo_aenderung)
            cursor.execute(sql_transaktion, werte_transaktion)
            cnx.commit()
            print(f"Transaktion für Benutzer-ID {benutzer['id']} - {benutzer['vorname']} {benutzer['nachname']}, \"{beschreibung}\", erfolgreich erstellt (Saldo {saldo_aenderung}).")

            cursor.execute(
                "SELECT SUM(t.saldo_aenderung) AS saldo " \
                "FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id WHERE u.id = %s", (benutzer['id'],))
            person = cursor.fetchone()
            if person:
                aktuellen_saldo_pruefen(benutzer['id']) # löst ggf. eine Email an den Benutzer aus
                print(f"Benutzer ID {benutzer['id']} gefunden: {benutzer['vorname']} {benutzer['nachname']} - Aktueller Saldo: {person['saldo']}")
                return jsonify({'message': f"Danke {benutzer['vorname']}. Dein aktueller Saldo beträgt: {person['saldo']}."}), 200
            return jsonify({'message': f"Transaktion für {benutzer['vorname']} {benutzer['nachname']} erfolgreich erstellt (Saldo {saldo_aenderung})."}), 200 # dieser Code sollte nie erreicht werden
        except Error as err:
            cnx.rollback()
            print(f"Fehler beim Erstellen der Transaktion: {err}")
            return jsonify({'error': 'Fehler beim Erstellen der Transaktion.'}), 500
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    else:
        return jsonify({'error': f'Kein Benutzer mit dem Token {nfc_token} gefunden.'}), 404


@app.route('/transaktionen', methods=['GET'])
@api_key_required
def get_alle_personen(user_id, username):
    """
    Gibt alle Personen in der Datenbank zurück (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste aller Transaktionen mit Benutzerinformationen.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT t.id, u.nachname AS nachname, u.vorname AS vorname, t.beschreibung, t.timestamp FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id ORDER BY t.timestamp DESC;")
        personen = cursor.fetchall()
        print("Transaktionen wurden ermittelt.")
        return jsonify(personen)
    except Error as err:
        print(f"Fehler beim Lesen der Daten: {err}.")
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/transaktionen', methods=['DELETE'])
@api_key_required
def reset_transaktionen(user_id, username):
    """
    Löscht die Transaktionen für alle hinterlegten Personen (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor()
    try:
        sql = "TRUNCATE TABLE transactions;"
        cursor.execute(sql)
        cnx.commit()
        print("Alle Transaktionen wurden gelöscht.")
        return jsonify({'message': 'Alle Transaktionen wurden gelöscht.'}), 200
    except Error as err:
        cnx.rollback()
        print(f"Fehler beim Leeren der Tabelle transactions: {err}")
        return jsonify({'error': 'Fehler beim Leeren der Tabelle transactions.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person', methods=['POST'])
@api_key_required
def create_person(user_id, username):
    """
    Fügt eine neue Person zur Datenbank hinzu (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    daten = request.get_json()
    if not daten or 'code' not in daten or 'nachname' not in daten or 'vorname' not in daten:
        return jsonify({'error': 'Ungültige oder unvollständige Daten.'}), 400

    code = daten['code']
    nachname = daten['nachname']
    vorname = daten['vorname']
    password = daten['password']

    if not isinstance(code, str) or len(code) != 10 or not code.isdigit():
        return jsonify({'error': 'Der Code muss ein 10-stelliger Zahlencode sein.'}), 400
    if not isinstance(nachname, str) or not nachname.strip() or not isinstance(vorname, str) or not vorname.strip():
        return jsonify({'error': 'Der Name darf nicht leer sein.'}), 400

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor()
    try:
        sql = "INSERT IGNORE INTO users (code, nachname, vorname, password) VALUES (%s, %s, %s, %s)"
        werte = (code, nachname, vorname, password)
        cursor.execute(sql, werte)
        cnx.commit()
        print(f"Person mit Code {code} erfolgreich hinzugefügt.")
        return jsonify({'message': f'Person mit Code {code} erfolgreich hinzugefügt.'}), 201
    except Error as err:
        cnx.rollback()
        print(f"Fehler beim Hinzufügen der Person: {err}")
        return jsonify({'error': 'Fehler beim Hinzufügen der Person.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person/<string:code>', methods=['DELETE'])
@api_key_required
def delete_person(user_id, username, code):
    """
    Person aus der Datenbank löschen (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.
        code (str): Der 10-stellige Code der zu löschenden Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor
    try:
        sql = "DELETE FROM users WHERE code = %s"
        cursor.execute(sql, code)
        print(sql, code)
        cnx.commit()
        if cursor.rowcount > 0:
            print(f"Person mit Code {code} erfolgreich gelöscht.")
            return jsonify({'message': f'Person mit Code {code} erfolgreich gelöscht.'}), 200
        return jsonify({'error': f'Keine Person mit dem Code {code} gefunden.'}), 404
    except Error as err:
        cnx.rollback()
        print(f"Fehler beim Löschen der Person: {err}")
        return jsonify({'error': 'Fehler beim Löschen der Person.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person/existent/<string:code>', methods=['GET'])
@api_key_required
def person_exists_by_code(user_id, username, code):
    """
    Prüft anhand ihres 10-stelligen Codes, ob eine Person existiert (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Namen der Person oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute("SELECT nachname, vorname FROM users WHERE code = %s", (code,))
        person = cursor.fetchone()
        if person:
            print(f"Person mit Code {code} gefunden: {person['nachname']}, {person['vorname']}")
            return jsonify(person)
        print(f"Person mit Code {code} nicht gefunden.")
        return jsonify({'error': 'Person nicht gefunden.'}), 404
    except Error as err:
        print(f"Fehler beim Lesen der Daten: {err}")
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person/<string:code>', methods=['GET'])
@api_key_required
def get_person_by_code(user_id, username, code):
    """
    Gibt Daten einer Person anhand ihres 10-stelligen Codes zurück (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit den Personendaten (Name, Vorname, Saldo) oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor(dictionary=True)
    try:
        cursor.execute("SELECT nachname, vorname FROM users WHERE code = %s", (code,))
        person = cursor.fetchone()
        if person:
            cursor.execute(
                "SELECT u.nachname AS nachname, u.vorname AS vorname, SUM(t.saldo_aenderung) AS saldo " \
                "FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id WHERE u.code = %s GROUP BY u.nachname, u.vorname", (code,))
            person = cursor.fetchone()
            if person:
                print(f"Person mit Code {code} gefunden: {person['nachname']}, {person['vorname']} - Saldo {person['saldo']}")
                return jsonify(person)
            print(f"Person mit Code {code} hat noch keine Transaktionen durchgeführt.")
            return jsonify({'error': 'Person hat noch keine Transaktionen durchgeführt.'}), 200
        print(f"Person mit Code {code} nicht gefunden.")
        return jsonify({'error': 'Person nicht gefunden.'}), 200
    except Error as err:
        print(f"Fehler beim Lesen der Daten: {err}")
        return jsonify({'error': 'Fehler beim Lesen der Daten.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person/<string:code>', methods=['PUT'])
@api_key_required
def person_bearbeiten(user_id, username, code):
    """
    Ermittelt eine Person anhand des übermittelten Codes und erstellt eine Transaktion.

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.
        code (str): Der 10-stellige Code der Person, für die eine Transaktion erstellt wird.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor()
    try:
        sql = "SELECT id FROM users WHERE code = %s"
        cursor.execute(sql, (code,))
        user_data = cursor.fetchone()
        if user_data:
            user_id = user_data[0]
            beschreibung = request.json.get('beschreibung')
            saldo_aenderung = request.json.get('saldo_aenderung')

            if not beschreibung or saldo_aenderung is None:
                print("Ungültige Anfrage. Beschreibung und Saldoänderung sind erforderlich.")
                return jsonify({'error': 'Parameter Beschreibung und Saldoänderung sind erforderlich.'}), 400

            # Transaktion erstellen
            sql_transaktion = "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)"
            werte_transaktion = (user_id, beschreibung, saldo_aenderung)
            cursor.execute(sql_transaktion, werte_transaktion)
            cnx.commit()
            print("Transaktion erfolgreich erstellt.")
            aktuellen_saldo_pruefen(user_id) # löst ggf. eine Email an den Benutzer aus
            return jsonify({'message': 'Transaktion erfolgreich erstellt.'}), 201
        print(f"Person mit diesem Code nicht gefunden: {code}")
        return jsonify({'error': 'Person mit diesem Code nicht gefunden.'}), 404
    except Error as err:
        cnx.rollback()
        print(f"Fehler beim Bearbeiten der Person oder Erstellen der Transaktion: {err}")
        return jsonify({'error': 'Fehler beim Bearbeiten der Person oder Erstellen der Transaktion.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route('/person/transaktionen/<string:code>', methods=['DELETE'])
@api_key_required
def person_transaktionen_loeschen(user_id, username, code):
    """
    Ermittelt eine Person anhand des übermittelten Codes und löscht die verknüpften Transaktionen.

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.
        code (str): Der 10-stellige Code der Person, deren Transaktionen gelöscht werden sollen.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    print(f"Benutzer authentifiziert {user_id} - {username}")
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = cnx.cursor()
    try:
        sql = "SELECT id AS user_id FROM users WHERE code = %s"
        cursor.execute(sql, (code,))
        user_data = cursor.fetchone()
        if user_data:
            user_id = user_data[0]

            if not code:
                print("Ungültige Anfrage. Angabe eines Usercodes ist erforderlich.")
                return jsonify({'error': 'Angabe eines Usercodes ist erforderlich.'}), 400

            # Transaktion erstellen
            sql_transaktion = "DELETE FROM transactions WHERE user_id = %s"
            cursor.execute(sql_transaktion, (user_id,))
            cnx.commit()
            print("Transaktionen erfolgreich gelöscht.")
            return jsonify({'message': 'Transaktionen erfolgreich gelöscht.'}), 201
        print(f"Person mit diesem Code nicht gefunden: {code}")
        return jsonify({'error': 'Person mit diesem Code nicht gefunden.'}), 404
    except Error as err:
        cnx.rollback()
        print(f"Fehler beim Löschen der Transaktion: {err}")
        return jsonify({'error': 'Fehler beim Löschen der Transaktion.'}), 500
    finally:
        cursor.close()
        db_utils.DatabaseConnectionPool.close_connection(cnx)


if __name__ == '__main__':
    if not all(key in config.db_config and config.db_config[key] is not None for key in ['host', 'port', 'user', 'password', 'database']):
        print("Fehler: Nicht alle Datenbank-Konfigurationsvariablen (MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB) sind in der .env Datei oder Umgebung gesetzt.")
        sys.exit()

    try:
        config.db_config['port'] = int(config.db_config['port'])
    except ValueError:
        print(f"Fehler: Datenbank-Port '{config.db_config['port']}' ist keine gültige Zahl.")
        sys.exit()

    if not all(key in config.smtp_config and config.smtp_config[key] is not None for key in ['host', 'port', 'user', 'password', 'sender']):
        print("Fehler: Nicht alle SMTP-Konfigurationsvariablen (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_SENDER) sind in der .env Datei oder Umgebung gesetzt.")
        sys.exit()

    try:
        config.smtp_config['port'] = int(config.smtp_config['port'])
    except ValueError:
        print(f"Fehler: SMTP_PORT '{config.smtp_config['port']}' ist keine gültige Zahl.")
        sys.exit()

    app.run()
