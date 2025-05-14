"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

import binascii
import os
import sys
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash # pigar: required-packages=uWSGI
from werkzeug.security import check_password_hash, generate_password_hash
import mysql.connector
from mysql.connector import pooling

load_dotenv()

if "STATIC_URL_PREFIX" in os.environ:
    app = Flask(__name__, static_url_path=os.environ.get('STATIC_URL_PREFIX', '/static'))
else:
    app = Flask(__name__)

if "BASE_URL" in os.environ:
    BASE_URL = os.environ.get('BASE_URL', '/')
    print(f"BASE_URL: {BASE_URL}")
else:
    BASE_URL=""

app.config['SECRET_KEY'] = os.urandom(24)
app.config['MYSQL_HOST'] = os.getenv("MYSQL_HOST")
app.config['MYSQL_USER'] = os.getenv("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.getenv("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.getenv("MYSQL_DB")

# Globaler Connection Pool
try:
    db_config = {
        'host': app.config['MYSQL_HOST'],
        'user': app.config['MYSQL_USER'],
        'password': app.config['MYSQL_PASSWORD'],
        'database': app.config['MYSQL_DB'],
    }
    cnxpool = pooling.MySQLConnectionPool(pool_name="guipool", pool_size=3, **db_config)  # Pool initialisieren
    print("GUI Connection Pool erfolgreich initialisiert.")
except mysql.connector.Error as e:
    print(f"Fehler beim Initialisieren des GUI Connection Pools: {e}")
    sys.exit(1)


def get_db_connection():
    """
    Ruft eine Datenbankverbindung aus dem Pool ab.

    Diese Funktion versucht, eine freie Verbindung aus dem globalen Verbindungspool abzurufen.
    Bei Erfolg wird die Verbindung zur Verwendung zurückgegeben.  Falls keine Verbindung
    verfügbar ist, wird eine Fehlermeldung ausgegeben.

    Returns:
        mysql.connector.connection_cext.CMySQLConnection: Eine Datenbankverbindung, falls erfolgreich;
                                                         None, falls kein Verbindung verfügbar ist oder ein Fehler auftritt.
    """
    try:
        cnx = cnxpool.get_connection()
        return cnx
    except mysql.connector.Error as e:
        print(f"Fehler beim Abrufen einer Verbindung aus dem Pool: {e}")
        return None


def close_db_connection(cnx):
    """
    Gibt eine Datenbankverbindung an den Pool zurück.

    Diese Funktion gibt eine zuvor abgerufene Datenbankverbindung an den globalen Verbindungspool zurück.
    Es ist wichtig, diese Funktion aufzurufen, wenn die Verbindung nicht mehr benötigt wird,
    um sicherzustellen, dass sie von anderen Teilen der Anwendung wiederverwendet werden kann
    und keine Ressourcenlecks entstehen.

    Args:
        cnx (mysql.connector.connection_cext.CMySQLConnection): Die Datenbankverbindung, die an den Pool
                                                               zurückgegeben werden soll.  Wenn None übergeben wird,
                                                               wird die Funktion beendet, ohne zu versuchen,
                                                               die Verbindung zu schließen.
    """
    if cnx:
        cnx.close()


def hex_to_binary(hex_string):
    """
    Konvertiert einen Hexadezimalstring in Binärdaten.

    Diese Funktion nimmt einen Hexadezimalstring entgegen und wandelt ihn in die entsprechende
    Binärdarstellung um.  Sie wird typischerweise verwendet, um NFC-UIDs zu verarbeiten,
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
        print(f"Fehler bei der Hexadezimal-Konvertierung: Ungültiger Hexadezimalstring '{hex_string}'")
        return None
    except TypeError:
        print(f"Fehler bei der Hexadezimal-Konvertierung: Ungültiger Typ für Hexadezimalstring: {type(hex_string)}")
        return None


def update_user_nfc_uid(user_id, hex_uid):
    """
    Aktualisiert die NFC-UID eines Benutzers in der Datenbank.

    Args:
        user_id (int): Die ID des Benutzers.
        hex_uid (str): Die Hexadezimaldarstellung der NFC-UID.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. ungültige UID, Datenbankfehler).
    """
    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        binary_uid = hex_to_binary(hex_uid)
        if binary_uid:
            try:
                query = "UPDATE users SET nfc_uid = %s WHERE id = %s"
                cursor.execute(query, (binary_uid, user_id))
                cnx.commit()
                return True
            except mysql.connector.Error as err:
                print(f"Fehler beim Aktualisieren der NFC-UID: {err}")
                cnx.rollback()
                return False
            finally:
                cursor.close()
                close_db_connection(cnx)
        else:
            flash('Ungültige NFC-UID. Bitte überprüfe die Eingabe.', 'error')
            return False
    return False


def delete_user(user_id):
    """
    Löscht einen Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des zu löschenden Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Löschen des Benutzers: {err}")
            cnx.rollback()
            return False
        finally:
            cursor.close()
            close_db_connection(cnx)
    return False


def fetch_user(code):
    """
    Ruft einen Benutzer aus der Datenbank anhand seines Codes ab.

    Args:
        code (str): Der eindeutige Code des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, name, password, is_admin) oder None, falls kein Benutzer gefunden wird.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, code, name, password, is_admin FROM users WHERE code = %s"
            cursor.execute(query, (code,))
            user = cursor.fetchone()
            return user
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen des Benutzers: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return None


def get_user_by_id(user_id):
    """
    Ruft einen Benutzer anhand seiner ID ab und holt die zugehörige NFC-UID.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, name, is_admin, password, nfc_uid)
              oder None, falls kein Benutzer gefunden wird.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, name, is_admin, password, nfc_uid
                FROM users
                WHERE id = %s
            """
            cursor.execute(query, (user_id,))
            user = cursor.fetchone()
            return user
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen des Benutzers: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return None


def get_total_credits_for_user(user_id):
    """
    Berechnet die Summe der Credits für den Benutzer mit der übergebenen user_id.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        int: Die Summe der Credits oder 0, falls kein Benutzer gefunden wird.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "SELECT SUM(credits) FROM transactions WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            total_credits = cursor.fetchone()[0] or 0
            return total_credits
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen der Gesamtcredits: {err}")
            return 0
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return 0


def get_total_credits_by_user():
    """
    Berechnet die Summe der Credits für jeden Benutzer.

    Returns:
        dict: Ein Dictionary, wobei der Schlüssel die Benutzer-ID und der Wert die Summe der Credits ist.
              Enthält alle Benutzer, auch solche ohne Transaktionen (Wert dann 0).
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT u.id, SUM(t.credits) AS total_credits
                FROM users u
                LEFT JOIN transactions t ON u.id = t.user_id
                GROUP BY u.id
            """
            cursor.execute(query)
            credits_by_user = {row['id']: row['total_credits'] or 0 for row in cursor.fetchall()}
            return credits_by_user
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen der Credits pro Benutzer: {err}")
            return {}
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return {}


def get_all_users():
    """
    Ruft alle Benutzer aus der Datenbank ab, sortiert nach Namen, und holt die zugehörige NFC-UID.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benutzer repräsentiert
              (id, code, name, is_admin, nfc_uid).
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, name, is_admin, nfc_uid
                FROM users
                ORDER BY name
            """
            cursor.execute(query)
            users = cursor.fetchall()
            return users
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen aller Benutzer: {err}")
            return []
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return []


def get_user_transactions(user_id):
    """
    Ruft alle Transaktionen für einen bestimmten Benutzer ab, sortiert nach Zeitstempel (neueste zuerst).

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary eine Transaktion repräsentiert
              (id, article, credits, timestamp). Gibt None zurück, falls ein Fehler auftritt.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, article, credits, timestamp FROM transactions WHERE user_id = %s ORDER BY timestamp DESC"
            cursor.execute(query, (user_id,))
            transactions = cursor.fetchall()
            return transactions
        except mysql.connector.Error as err:
            print(f"Datenbankfehler beim Abrufen der Benutzertransaktionen: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return None


def add_transaction(user_id, article, credits_change):
    """
    Fügt eine neue Transaktion für einen Benutzer hinzu.

    Args:
        user_id (int): Die ID des Benutzers.
        article (str): Der Artikel der Transaktion.
        credits (int): Die Anzahl der Credits der Transaktion.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO transactions (user_id, article, credits) VALUES (%s, %s, %s)"
            cursor.execute(query, (user_id, article, credits_change))
            cnx.commit()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Hinzufügen der Transaktion: {err}")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return False


def delete_all_transactions(user_id):
    """
    Löscht alle Transaktionen eines Benutzers.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM transactions WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Löschen der Transaktionen: {err}")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
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

    cnx = get_db_connection()
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "UPDATE users SET password = %s WHERE id = %s"
            cursor.execute(query, (new_password_hash, user_id))
            cnx.commit()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Aktualisieren des Passworts: {err}")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            close_db_connection(cnx)
    return False


@app.route('/', methods=['GET', 'POST'])
def login():
    """
    Verarbeitet den Login eines Benutzers.

    Wenn die Methode POST ist, wird der Benutzercode und das Passwort überprüft.
    Bei erfolgreicher Anmeldung wird der Benutzer in der Session gespeichert und zur Benutzerinformationsseite weitergeleitet.
    Bei fehlgeschlagener Anmeldung wird eine Fehlermeldung angezeigt.

    Returns:
        str: Die gerenderte Login-Seite (login.html) mit optionaler Fehlermeldung.
    """

    if request.method == 'POST':
        code = request.form['code']
        password = request.form['password']
        user = fetch_user(code)
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            print("Redirecting: " + (BASE_URL + url_for('user_info')))
            return redirect(BASE_URL + url_for('user_info'))
        return render_template('login.html', error='Ungültiger Benutzername oder Passwort')
    return render_template('login.html')


@app.route('/user_info', methods=['GET', 'POST'])
def user_info():
    """
    Zeigt die Benutzerinformationen an und verarbeitet die Passwortänderung.

    Wenn die Methode GET ist, werden die Benutzerinformationen, Transaktionen und die Summe der Credits abgerufen und angezeigt.
    Wenn die Methode POST ist und das Passwortänderungsformular abgeschickt wurde, wird das aktuelle Passwort überprüft,
    das neue Passwort validiert, gehasht und in der Datenbank aktualisiert.

    Returns:
        str: Die gerenderte Benutzerinformationsseite (user_info.html).
    """

    user_id = session.get('user_id')
    if not user_id:
        return redirect(BASE_URL + url_for('login'))

    user = get_user_by_id(user_id)
    transactions = get_user_transactions(user_id)
    total_credits = sum(t['credits'] for t in transactions) if transactions else 0

    if request.method == 'POST':
        if 'change_password' in request.form:

            current_password = request.form['current_password']
            new_password = request.form['new_password']
            confirm_new_password = request.form['confirm_new_password']

            print("Passwortänderungsformular wurde abgeschickt.") # Debug-Ausgabe

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
                    return redirect(BASE_URL + url_for('user_info'))
                flash('Fehler beim Ändern des Passworts.', 'error')

    return render_template('user_info.html', user=user, transactions=transactions, total_credits=total_credits)


@app.route('/admin')
def admin_dashboard():
    """
    Zeigt das Admin-Dashboard an, mit einer Übersicht über alle Benutzer und deren Credits.

    Benötigt einen angemeldeten Admin-Benutzer.

    Returns:
        str: Die gerenderte Admin-Dashboard-Seite (admin_dashboard.html) oder eine Weiterleitung zur Login-Seite,
             falls der Benutzer nicht angemeldet oder kein Admin ist.
    """

    user_id = session.get('user_id')
    if user_id:
        admin_user = get_user_by_id(user_id)
        if admin_user and admin_user['is_admin']:
            users = get_all_users()
            credits_by_user = get_total_credits_by_user()
            return render_template('admin_dashboard.html', user=admin_user, users=users, credits_by_user=credits_by_user)
    return redirect(BASE_URL + url_for('login'))


@app.route('/admin/user/<int:user_id>/transactions', methods=['GET', 'POST'])
def admin_user_transactions(user_id):
    """
    Zeigt die Transaktionen eines bestimmten Benutzers an und ermöglicht das Hinzufügen und Löschen von Transaktionen
    sowie das Löschen des Benutzers selbst.  Benötigt einen angemeldeten Admin-Benutzer.

    Args:
        user_id (int): Die ID des Benutzers, dessen Transaktionen angezeigt werden sollen.

    Returns:
        str: Die gerenderte Seite mit den Transaktionen des Benutzers (admin_user_transactions.html)
             oder eine Weiterleitung zur Login-Seite, falls der Benutzer nicht angemeldet oder kein Admin ist.
    """

    logged_in_user_id = session.get('user_id')
    if not logged_in_user_id or not get_user_by_id(logged_in_user_id)['is_admin']:
        return redirect(BASE_URL + url_for('login'))

    target_user = get_user_by_id(user_id)
    transactions = get_user_transactions(user_id)
    total_credits = get_total_credits_for_user(user_id)

    if request.method == 'POST':
        if 'delete_transactions' in request.form:
            if delete_all_transactions(user_id):
                flash('Alle Transaktionen für diesen Benutzer wurden gelöscht.', 'success')
                return redirect(BASE_URL + url_for('admin_user_transactions', user_id=user_id))
            flash('Fehler beim Löschen der Transaktionen.', 'error')
        elif 'add_transaction' in request.form:
            article = request.form['article']
            credits_change = int(request.form['credits'])
            if add_transaction(user_id, article, credits_change):
                flash('Transaktion erfolgreich hinzugefügt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_transactions', user_id=user_id))
        elif 'delete_user' in request.form:
            if delete_user(user_id):
                flash(f'Benutzer "{target_user["name"]}" (ID {user_id}) wurde gelöscht.', 'success')
                return redirect(BASE_URL + url_for('admin_dashboard')) # Zurück zur Benutzerübersicht
            flash(f'Fehler beim Löschen des Benutzers "{target_user["name"]}" (ID {user_id}).', 'error')
        elif 'add_nfc_token' in request.form:
            nfc_uid = request.form['nfc_uid']
            if update_user_nfc_uid(user_id, nfc_uid):
                flash('NFC-Token erfolgreich aktualisiert.', 'success')
                return redirect(BASE_URL + url_for('admin_user_transactions', user_id=user_id))
            flash('Fehler beim Aktualisieren des NFC-Tokens.', 'error')

    return render_template('admin_user_transactions.html', user=target_user, transactions=transactions, total_credits=total_credits)


@app.route('/logout')
def logout():
    """
    Meldet den Benutzer ab, indem die Benutzer-ID aus der Session entfernt wird.

    Returns:
        str: Eine Weiterleitung zur Login-Seite.
    """

    session.pop('user_id', None)
    return redirect(BASE_URL + url_for('login'))


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ['true', '1', 'yes']
    app.run(debug=debug_mode)
