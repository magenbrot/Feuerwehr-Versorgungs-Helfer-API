"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

import binascii
import os
import sys
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash # pigar: required-packages=uWSGI
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error
import config
import db_utils

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

# Initialisiere den Pool einmal beim Start deiner Anwendung
try:
    db_utils.DatabaseConnectionPool.initialize_pool(config.db_config)
except Error:
    print("Fehler beim Starten der Datenbankverbindung.")
    sys.exit(1)


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


def add_user_nfc_token(user_id, token_name, hex_uid):
    """
    Fügt einen neuen NFC-Token der Datenbank hinzu.

    Args:
        user_id (int): Die ID des Benutzers.
        hex_uid (str): Die Hexadezimaldarstellung der NFC-UID.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. ungültige UID, Datenbankfehler).
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        binary_uid = hex_to_binary(hex_uid)
        if binary_uid:
            try:
                query = "INSERT INTO nfc_token SET user_id = %s, token_name = %s, token_uid = %s, last_used = NOW()"
                cursor.execute(query, (user_id, token_name, binary_uid))
                cnx.commit()
                return True
            except Error as err:
                print(f"Fehler beim Hinzufügen des NFC-Tokens: {err}")
                cnx.rollback()
                return False
            finally:
                cursor.close()
                db_utils.DatabaseConnectionPool.close_connection(cnx)
        else:
            flash('Ungültige NFC-UID. Bitte überprüfe die Eingabe.', 'error')
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
                print(f"Lösche NFC-Tokens: {token_id} von Benutzer {user_id}")
                query = "DELETE FROM nfc_token WHERE token_id = %s AND user_id = %s"
                cursor.execute(query, (token_id, user_id))
                cnx.commit()
                return True
            except Error as err:
                print(f"Fehler beim Entfernen des NFC-Tokens: {err}")
                cnx.rollback()
                return False
            finally:
                cursor.close()
                db_utils.DatabaseConnectionPool.close_connection(cnx)
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

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "DELETE FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            cnx.commit()
            return True
        except Error as err:
            print(f"Fehler beim Löschen des Benutzers: {err}")
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False


def toggle_user_lock(user_id, lock_state):
    """
    Sperrt einen Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des zu sperrenden Benutzers.
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
            print(f"Fehler beim Ändern des Locks für den Benutzers: {err}")
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
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, password, is_admin) oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, code, nachname, vorname, password, is_admin FROM users WHERE code = %s"
            cursor.execute(query, (code,))
            user = cursor.fetchone()
            return user
        except Error as err:
            print(f"Datenbankfehler beim Abrufen des Benutzers: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def get_user_by_id(user_id):
    """
    Ruft einen Benutzer anhand seiner ID ab und holt die zugehörige NFC-UID.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, nachname, vorname, is_locked, is_admin, password)
              oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, nachname, vorname, is_locked, is_admin, password
                FROM users
                WHERE id = %s
            """
            cursor.execute(query, (user_id,))
            user = cursor.fetchone()
            return user
        except Error as err:
            print(f"Datenbankfehler beim Abrufen des Benutzers: {err}")
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
        int: Das Saldo oder 0, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "SELECT SUM(saldo_aenderung) FROM transactions WHERE user_id = %s"
            cursor.execute(query, (user_id,))
            saldo = cursor.fetchone()[0] or 0
            return saldo
        except Error as err:
            print(f"Datenbankfehler beim Abrufen des Saldos: {err}")
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
            print(f"Datenbankfehler beim Abrufen des Saldos pro Benutzer: {err}")
            return {}
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return {}


def get_all_users():
    """
    Ruft alle Benutzer aus der Datenbank ab, sortiert nach Namen, und holt die zugehörige NFC-UID.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benutzer repräsentiert
              (id, code, nachname, vorname, is_locked, is_admin).
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, nachname, vorname, is_locked, is_admin
                FROM users
                ORDER BY nachname
            """
            cursor.execute(query)
            users = cursor.fetchall()
            return users
        except Error as err:
            print(f"Datenbankfehler beim Abrufen aller Benutzer: {err}")
            return []
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return []

def get_user_nfc_tokens(user_id):
    """
    Ruft alle Tokens eines Benutzer ab, absteigend sortiert nach dem Zeitpunkt der letzten Verwendung.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Token repräsentiert
              (token_id, token_name, token_uid, last_used). Gibt None zurück, falls ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT token_id, token_name, token_uid, last_used FROM nfc_token WHERE user_id = %s ORDER BY last_used DESC"
            cursor.execute(query, (user_id,))
            transactions = cursor.fetchall()
            return transactions
        except Error as err:
            print(f"Datenbankfehler beim Abrufen der Benutzertransaktionen: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None

def get_user_transactions(user_id):
    """
    Ruft alle Transaktionen für einen bestimmten Benutzer ab, sortiert nach Zeitstempel (neueste zuerst).

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary eine Transaktion repräsentiert
              (id, article, saldo_aendung, timestamp). Gibt None zurück, falls ein Fehler auftritt.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = "SELECT id, article, saldo_aenderung, timestamp FROM transactions WHERE user_id = %s ORDER BY timestamp DESC"
            cursor.execute(query, (user_id,))
            transactions = cursor.fetchall()
            return transactions
        except Error as err:
            print(f"Datenbankfehler beim Abrufen der Benutzertransaktionen: {err}")
            return None
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return None


def add_transaction(user_id, article, saldo_aenderung):
    """
    Fügt eine neue Transaktion für einen Benutzer hinzu.

    Args:
        user_id (int): Die ID des Benutzers.
        article (str): Der Artikel der Transaktion.
        saldo_aenderung (int): Die Änderung im Saldo der Transaktion.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        try:
            query = "INSERT INTO transactions (user_id, article, saldo_aenderung) VALUES (%s, %s, %s)"
            cursor.execute(query, (user_id, article, saldo_aenderung))
            cnx.commit()
            return True
        except Error as err:
            print(f"Fehler beim Hinzufügen der Transaktion: {err}")
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
            print(f"Fehler beim Löschen der Transaktionen: {err}")
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
            print(f"Fehler beim Aktualisieren des Passworts: {err}")
            cnx.rollback()
            return False
        finally:
            if cursor:
                cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
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

    Wenn die Methode GET ist, werden die Benutzerinformationen, Transaktionen und der Saldo abgerufen und angezeigt.
    Wenn die Methode POST ist und das Passwortänderungsformular abgeschickt wurde, wird das aktuelle Passwort überprüft,
    das neue Passwort validiert, gehasht und in der Datenbank aktualisiert.

    Returns:
        str: Die gerenderte Benutzerinformationsseite (user_info.html).
    """

    user_id = session.get('user_id')
    if not user_id:
        return redirect(BASE_URL + url_for('login'))

    user = get_user_by_id(user_id)
    nfc_tokens = get_user_nfc_tokens(user_id)
    transactions = get_user_transactions(user_id)
    saldo = sum(t['saldo_aenderung'] for t in transactions) if transactions else 0

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

    return render_template('user_info.html', user=user, nfc_tokens=nfc_tokens, transactions=transactions, saldo=saldo)


@app.route('/admin')
def admin_dashboard():
    """
    Zeigt das Admin-Dashboard an, mit einer Übersicht über alle Benutzer und deren Saldo.

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
            saldo_by_user = get_saldo_by_user()
            return render_template('admin_dashboard.html', user=admin_user, users=users, saldo_by_user=saldo_by_user)
    return redirect(BASE_URL + url_for('login'))


@app.route('/admin/user/<int:user_id>/transactions', methods=['GET', 'POST'])
def admin_user_modification(user_id):
    """
    Zeigt die Transaktionen eines bestimmten Benutzers an und ermöglicht das Hinzufügen und Löschen von Transaktionen
    sowie das Löschen des Benutzers selbst.  Benötigt einen angemeldeten Admin-Benutzer.

    Args:
        user_id (int): Die ID des Benutzers, dessen Transaktionen angezeigt werden sollen.

    Returns:
        str: Die gerenderte Seite mit den Transaktionen des Benutzers (admin_user_modification.html)
             oder eine Weiterleitung zur Login-Seite, falls der Benutzer nicht angemeldet oder kein Admin ist.
    """

    logged_in_user_id = session.get('user_id')
    if not logged_in_user_id or not get_user_by_id(logged_in_user_id)['is_admin']:
        return redirect(BASE_URL + url_for('login'))

    target_user = get_user_by_id(user_id)
    nfc_tokens = get_user_nfc_tokens(user_id)
    transactions = get_user_transactions(user_id)
    saldo = get_saldo_for_user(user_id)

    if request.method == 'POST':
        if 'delete_transactions' in request.form:
            if delete_all_transactions(user_id):
                flash('Alle Transaktionen für diesen Benutzer wurden gelöscht.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
            flash('Fehler beim Löschen der Transaktionen.', 'error')
        elif 'add_transaction' in request.form:
            article = request.form['article']
            saldo_aenderung = int(request.form['saldo_aenderung'])
            if add_transaction(user_id, article, saldo_aenderung):
                flash('Transaktion erfolgreich hinzugefügt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
        elif 'lock_user' in request.form:
            if toggle_user_lock(user_id, True):
                flash(f'Benutzer "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}) wurde gesperrt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
            flash(f'Fehler beim Sperren des Benutzers "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}).', 'error')
        elif 'unlock_user' in request.form:
            if toggle_user_lock(user_id, False):
                flash(f'Benutzer "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}) wurde entsperrt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
            flash(f'Fehler beim Entsperren des Benutzers "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}).', 'error')
        elif 'delete_user' in request.form:
            if delete_user(user_id):
                flash(f'Benutzer "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}) wurde gelöscht.', 'success')
                return redirect(BASE_URL + url_for('admin_dashboard')) # Zurück zur Benutzerübersicht
            flash(f'Fehler beim Löschen des Benutzers "{target_user["nachname"]}, {target_user["vorname"]}" (ID {user_id}).', 'error')
        elif 'add_user_nfc_token' in request.form:
            nfc_token_name = request.form['nfc_token_name']
            nfc_token_uid = request.form['nfc_token_uid']
            if add_user_nfc_token(user_id, nfc_token_name, nfc_token_uid):
                flash('NFC-Token erfolgreich hinzugefügt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
            flash('Fehler beim Hinzufügen des NFC-Tokens.', 'error')
        elif 'delete_user_nfc_token' in request.form:
            nfc_token_id = request.form['nfc_token_id']
            if delete_user_nfc_token(user_id, nfc_token_id):
                flash('NFC-Token erfolgreich entfernt.', 'success')
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
            flash('Fehler beim Entfernen des NFC-Tokens.', 'error')
        else:
            flash('Ungültige Anfrage.', 'error')

    return render_template('admin_user_modification.html', user=target_user, nfc_tokens=nfc_tokens, transactions=transactions, saldo=saldo)


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
    app.run(port=5001, debug=debug_mode)
