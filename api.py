"""Dieses Modul ist eine API Middleware für den Feuerwehr-Versorgungs-Helfer"""

import os
import sys
from functools import wraps
from dotenv import load_dotenv
import mysql.connector
from flask import Flask, jsonify, request

load_dotenv()
app = Flask(__name__)

app.config['MYSQL_HOST'] = os.getenv("MYSQL_HOST")
app.config['MYSQL_USER'] = os.getenv("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.getenv("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.getenv("MYSQL_DB")

app.json.ensure_ascii = False
app.json.mimetype = "application/json; charset=utf-8"

if not app.config['MYSQL_HOST']:
    print("Fehler: MYSQL_HOST ist nicht in den Umgebungsvariablen definiert.")
    sys.exit(1)
if not app.config['MYSQL_USER']:
    print("Fehler: MYSQL_USER ist nicht in den Umgebungsvariablen definiert.")
    sys.exit(1)
if not app.config['MYSQL_PASSWORD']:
    print("Fehler: MYSQL_PASSWORD ist nicht in den Umgebungsvariablen definiert.")
    sys.exit(1)
if not app.config['MYSQL_DB']:
    print("Fehler: MYSQL_DB ist nicht in den Umgebungsvariablen definiert.")
    sys.exit(1)

def get_db():
    """
    Stellt eine Verbindung zur MySQL-Datenbank her.

    Returns:
        mysql.connector.MySQLConnection or None: Das Datenbankverbindungsobjekt oder None bei einem Fehler.
    """

    try:
        mydb = mysql.connector.connect(host=app.config['MYSQL_HOST'],
                                       user=app.config['MYSQL_USER'],
                                       password=app.config['MYSQL_PASSWORD'],
                                       database=app.config['MYSQL_DB'])
        return mydb
    except mysql.connector.Error as err:
        print(f"Fehler bei der Verbindung zur Datenbank: {err}")
        return None


def close_db(mydb):
    """
    Schließt die Datenbankverbindung.

    Args:
        mydb (mysql.connector.MySQLConnection): Das Datenbankverbindungsobjekt.
    """

    if mydb and mydb.is_connected():
        mydb.close()


def get_user_by_api_key(api_key):
    """
    Ruft den Benutzer anhand des API-Schlüssels aus der Datenbank ab.

    Args:
        api_key (str): Der API-Schlüssel des Benutzers.

    Returns:
        tuple or None: Ein Tupel mit (user_id, username) oder None, falls kein Benutzer gefunden wird oder ein Fehler auftritt.
    """

    mydb = get_db()
    if not mydb:
        return None, None
    cursor = mydb.cursor()
    try:
        cursor.execute(
            "SELECT u.id, u.username FROM api_users u JOIN api_keys ak ON u.id = ak.user_id " \
            "WHERE ak.api_key = %s", (api_key,))
        user = cursor.fetchone()
        if user:
            return user[0], user[1]  # user_id, username
        return None, None
    except mysql.connector.Error as err:
        print(
            f"Fehler beim Abrufen des Benutzers anhand des API-Schlüssels: {err}.")
        return None, None
    finally:
        cursor.close()
        close_db(mydb)


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
            return jsonify({'message': 'API-Schlüssel fehlt!'}), 401
        user_id, username = get_user_by_api_key(api_key)
        if not user_id:
            return jsonify({'message': 'Ungültiger API-Schlüssel!'}), 401
        return f(user_id, username, *args, **kwargs)
    return decorated


@app.route('/health-protected', methods=['GET'])
@api_key_required
def health_protected_route(user_id, username):
    """
    Healthcheck gegen die Datenbank nur authentifizierte Benutzer.

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Healthcheck-Status und Benutzerinformationen.
    """

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    return jsonify({'message': f'Healthcheck OK! Authentifizierter Benutzer ID {user_id} ({username}).'})


@app.route('/credits-total', methods=['GET'])
@api_key_required
def get_alle_summe(user_id, username):
    """
    Gibt die Gesamtcredits der Personen in der Datenbank zurück (nur für authentifizierte Benutzer).

    Args:
        user_id (int): Die ID des authentifizierten Benutzers.
        username (str): Der Benutzername des authentifizierten Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste von Benutzern und ihren Gesamtcredits.
    """

    print(f"authenticated user {user_id} - {username}.")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT u.name AS benutzername, SUM(t.credits) AS summe_credits FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id GROUP BY u.name ORDER BY summe_credits DESC;")
        personen = cursor.fetchall()
        return jsonify(personen)
    except mysql.connector.Error as err:
        return jsonify({'error': f'Fehler beim Lesen der Daten: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT t.id, u.name AS benutzername, t.article, t.timestamp FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id ORDER BY t.timestamp DESC;")
        personen = cursor.fetchall()
        return jsonify(personen)
    except mysql.connector.Error as err:
        return jsonify({'error': f'Fehler beim Lesen der Daten: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor()
    try:
        sql = "TRUNCATE TABLE transactions;"
        cursor.execute(sql)
        mydb.commit()
        if cursor.rowcount >= 0:
            return jsonify({'message': 'Kontostand für alle Personen auf 0 gesetzt.'}), 200
    except mysql.connector.Error as err:
        mydb.rollback()
        return jsonify({'error': f'Fehler beim Leeren der Tabelle transactions: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    daten = request.get_json()
    if not daten or 'code' not in daten or 'name' not in daten:
        return jsonify({'error': 'Ungültige oder unvollständige Daten.'}), 400

    code = daten['code']
    name = daten['name']

    if not isinstance(code, str) or len(code) != 10 or not code.isdigit():
        return jsonify({'error': 'Der Code muss ein 10-stelliger Zahlencode sein.'}), 400
    if not isinstance(name, str) or not name.strip():
        return jsonify({'error': 'Der Name darf nicht leer sein.'}), 400

    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor()
    try:
        sql = "INSERT IGNORE INTO users (code, name) VALUES (%s, %s)"
        werte = (code, name)
        cursor.execute(sql, werte)
        mydb.commit()
        return jsonify({'message': f'Person mit Code {code} erfolgreich hinzugefügt.'}), 201
    except mysql.connector.Error as err:
        mydb.rollback()
        return jsonify({'error': f'Fehler beim Hinzufügen der Person: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor()
    try:
        sql = "DELETE FROM users WHERE code = %s"
        cursor.execute(sql, code)
        print(sql, code)
        mydb.commit()
        if cursor.rowcount > 0:
            return jsonify({'message': f'Person mit Code {code} erfolgreich gelöscht.'}), 200
        return jsonify({'error': f'Keine Person mit dem Code {code} gefunden.'}), 404
    except mysql.connector.Error as err:
        mydb.rollback()
        return jsonify({'error': f'Fehler beim Löschen der Person: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor(dictionary=True)
    try:
        cursor.execute("SELECT name FROM users WHERE code = %s", (code,))
        person = cursor.fetchone()
        if person:
            return jsonify(person)
        return jsonify({'error': 'Person nicht gefunden.'}), 200
    except mysql.connector.Error as err:
        return jsonify({'error': f'Fehler beim Lesen der Daten: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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
        flask.Response: Eine JSON-Antwort mit den Personendaten (Name, Summe der Credits) oder einem Fehler.
    """

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor(dictionary=True)
    try:
        cursor.execute("SELECT name FROM users WHERE code = %s", (code,))
        person = cursor.fetchone()
        if person:
            cursor.execute(
                "SELECT u.name AS name, SUM(t.credits) AS summe_credits FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id WHERE u.code = %s GROUP BY u.name", (code,))
            person = cursor.fetchone()
            if person:
                return jsonify(person)
            return jsonify({'error': 'Person hat nocht keine Transaktionen durchgeführt.'}), 200
        return jsonify({'error': 'Person nicht gefunden.'}), 200
    except mysql.connector.Error as err:
        return jsonify({'error': f'Fehler beim Lesen der Daten: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor()
    try:
        sql = "SELECT id FROM users WHERE code = %s"
        cursor.execute(sql, (code,))
        user_data = cursor.fetchone()
        if user_data:
            user_id = user_data[0]
            artikel = request.json.get('artikel')
            credits_change = request.json.get('credits')

            if not artikel or credits_change is None:
                return jsonify({'error': 'Parameter Artikel und Credits sind erforderlich.'}), 400

            # Transaktion erstellen
            sql_transaktion = "INSERT INTO transactions (user_id, article, credits) VALUES (%s, %s, %s)"
            werte_transaktion = (user_id, artikel, credits_change)
            cursor.execute(sql_transaktion, werte_transaktion)
            mydb.commit()
            return jsonify({'message': 'Transaktion erfolgreich erstellt.'}), 201
        else:
            return jsonify({'error': 'Person mit diesem Code nicht gefunden.'}), 404
    except mysql.connector.Error as err:
        mydb.rollback()
        return jsonify({'error': f'Fehler beim Bearbeiten der Person oder Erstellen der Transaktion: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


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

    print(f"authenticated user {user_id} - {username}")
    mydb = get_db()
    if not mydb:
        return jsonify({'error': 'Datenbankverbindung fehlgeschlagen.'}), 500
    cursor = mydb.cursor()
    try:
        sql = "SELECT id AS user_id FROM users WHERE code = %s"
        cursor.execute(sql, (code,))
        user_data = cursor.fetchone()
        if user_data:
            user_id = user_data[0]

            if not code:
                return jsonify({'error': 'Angabe eines Usercodes ist erforderlich.'}), 400

            # Transaktion erstellen
            sql_transaktion = "DELETE FROM transactions WHERE user_id = %s"
            cursor.execute(sql_transaktion, (user_id,))
            mydb.commit()
            return jsonify({'message': 'Transaktionen erfolgreich gelöscht.'}), 201
        return jsonify({'error': 'Person mit diesem Code nicht gefunden.'}), 404
    except mysql.connector.Error as err:
        mydb.rollback()
        return jsonify({'error': f'Fehler beim Löschen der Transaktion: {err}.'}), 500
    finally:
        cursor.close()
        close_db(mydb)


if __name__ == '__main__':
    app.run()
