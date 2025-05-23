"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

import binascii
import os
import random
import secrets
import string
import sys
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash # pigar: required-packages=uWSGI
from werkzeug.security import check_password_hash, generate_password_hash
from mysql.connector import Error, IntegrityError # IntegrityError für Unique-Constraint-Fehler hinzugefügt
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

# Initialisiere den Pool einmal beim Start der Anwendung # pylint: disable=R0801
try:
    db_utils.DatabaseConnectionPool.initialize_pool(config.db_config)
except Error:
    print("Fehler beim Starten der Datenbankverbindung.")
    sys.exit(1)


def generate_api_key_string(length=32):
    """Generiert einen sicheren, zufälligen API-Key-String."""
    return secrets.token_hex(length)


def hex_to_binary(hex_string):
    """
    Konvertiert einen Hexadezimalstring in Binärdaten.

    Diese Funktion nimmt einen Hexadezimalstring entgegen und wandelt ihn in die entsprechende
    Binärdarstellung um.  Sie wird typischerweise verwendet, um NFC-Token Daten zu verarbeiten,
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
                print(f"Fehler beim Hinzufügen des NFC-Tokens: {err}")
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
            flash('Ungültige NFC-Token Daten. Bitte überprüfe die Eingabe.', 'error')
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
            print(f"Fehler beim Ändern des Admin-Modes für den Benutzers: {err}")
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


def update_user_comment(user_id, comment):
    """
    Ändert den Kommentar eines Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des zu sperrenden Benutzers.
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
            print(f"Fehler beim Ändern des Kommentars für den Benutzers: {err}")
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
        user_id (int): Die ID des zu sperrenden Benutzers.
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
            print(f"Fehler beim Ändern der Emailadresse für den Benutzers: {err}")
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
            query = "SELECT id, code, nachname, vorname, password, is_admin, is_locked FROM users WHERE code = %s"
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
    Ruft einen Benutzer anhand seiner ID ab.

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
                SELECT id, code, nachname, vorname, email, kommentar, is_locked, is_admin, password
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
    Ruft alle Benutzer aus der Datenbank ab, sortiert nach Namen.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benutzer repräsentiert
              (id, code, nachname, vorname, is_locked, is_admin).
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor(dictionary=True)
        try:
            query = """
                SELECT id, code, nachname, vorname, email, kommentar, is_locked, is_admin
                FROM users
                ORDER BY nachname, vorname
            """ # Sortierung erweitert
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


def get_all_api_users():
    """
    Ruft alle API-Benutzer aus der Datenbank ab, sortiert nach Username.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen API-Benutzer repräsentiert
              (id, username).
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
            print(f"Datenbankfehler beim Abrufen aller API-Benutzer: {err}")
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
            print(f"Datenbankfehler beim Abrufen des API-Benutzers: {err}")
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
            print(f"Datenbankfehler beim Abrufen der API-Keys für API-Benutzer {api_user_id}: {err}")
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
              (token_id, token_name, token_daten, last_used). Gibt None zurück, falls ein Fehler auftritt.
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
            print(f"Datenbankfehler beim Abrufen der Benutzer NFC Tokens: {err}")
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
              (id, beschreibung, saldo_aendung, timestamp). Gibt None zurück, falls ein Fehler auftritt.
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
            print(f"Datenbankfehler beim Abrufen der Benutzertransaktionen: {err}")
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

def add_regular_user_db(code, nachname, vorname, password, email, kommentar, is_admin):
    """
    Fügt einen neuen regulären Benutzer der Datenbank hinzu.

    Args:
        code (str): Eindeutiger Code des Benutzers.
        nachname (str): Nachname des Benutzers.
        vorname (str): Vorname des Benutzers.
        password (str): Passwort des Benutzers (Klartext, wird hier gehasht).
        email (str, optional): E-Mail-Adresse des Benutzers.
        kommentar (str, optional): Kommentar zum Benutzer.
        is_admin (bool): Gibt an, ob der Benutzer Admin-Rechte hat.

    Returns:
        bool: True bei Erfolg, False bei Fehler (z.B. Datenbankfehler, doppelter Code).
    """
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if cnx:
        cursor = cnx.cursor()
        hashed_password = generate_password_hash(password)
        try:
            query = """
                INSERT INTO users (code, nachname, vorname, password, email, kommentar, is_admin, is_locked)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            """
            cursor.execute(query, (code, nachname, vorname, hashed_password, email, kommentar, 1 if is_admin else 0))
            cnx.commit()
            return True
        except IntegrityError:
            flash(f"Benutzercode '{code}' existiert bereits oder ein anderes eindeutiges Feld ist doppelt.", 'error')
            cnx.rollback()
            return False
        except Error as err:
            print(f"Fehler beim Hinzufügen des regulären Benutzers: {err}")
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
            print(f"Fehler beim Hinzufügen des API-Benutzers: {err}")
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
            print(f"Fehler beim Hinzufügen des API-Keys für API-Benutzer {api_user_id}: {err}")
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
            print(f"Fehler beim Löschen des API-Keys {api_key_id}: {err}")
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
            print(f"Fehler beim Löschen des API-Benutzers {api_user_id} und seiner Keys: {err}")
            flash("Datenbankfehler beim Löschen des API-Benutzers.", 'error')
            cnx.rollback()
            return False
        finally:
            cursor.close()
            db_utils.DatabaseConnectionPool.close_connection(cnx)
    return False

# --- Flask Routen ---

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
    if not user:
        session.pop('user_id', None)
        flash('Benutzer nicht gefunden oder Sitzung abgelaufen.', 'error')
        return redirect(BASE_URL + url_for('login'))

    if user.get('is_locked'): # Erneut prüfen, falls Sperrung während Session erfolgt
        session.pop('user_id', None)
        flash('Ihr Konto wurde gesperrt. Bitte kontaktieren Sie einen Administrator.', 'error')
        return redirect(BASE_URL + url_for('login'))

    nfc_tokens = get_user_nfc_tokens(user_id)
    transactions = get_user_transactions(user_id)
    saldo = sum(t['saldo_aenderung'] for t in transactions) if transactions else 0

    if request.method == 'POST':
        if 'change_password' in request.form:
            current_password = request.form['current_password']
            new_password = request.form['new_password']
            confirm_new_password = request.form['confirm_new_password']

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
                    user['password'] = new_password_hash
                else:
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
    if not user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info')) # Zur User-Info statt Login, falls kein Admin

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    users = get_all_users()
    saldo_by_user = get_saldo_by_user()
    return render_template('admin_dashboard.html', user=admin_user, users=users, saldo_by_user=saldo_by_user)


@app.route('/admin/add_user', methods=['GET', 'POST'])
def add_user():
    """
    Verarbeitet das Hinzufügen eines neuen regulären Benutzers (Frontend-Benutzer).

    Diese Route ist nur für Administratoren zugänglich. Bei einer GET-Anfrage wird das
    Formular zum Hinzufügen eines Benutzers angezeigt. Bei einer POST-Anfrage werden
    die Formulardaten validiert und versucht, den neuen Benutzer in der Datenbank
    zu speichern. Das Passwort wird vor dem Speichern gehasht.

    Returns:
        werkzeug.wrappers.response.Response: Bei GET das gerenderte Template
        `add_user.html`. Bei POST eine Weiterleitung zum Admin-Dashboard bei Erfolg
        oder zurück zum Formular mit Fehlermeldungen bei Misserfolg.
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

    if request.method == 'POST':
        code_input = request.form.get('code')
        nachname = request.form.get('nachname')
        vorname = request.form.get('vorname')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        email = request.form.get('email')
        kommentar = request.form.get('kommentar')
        is_admin_form = 'is_admin' in request.form

        # Validierungen für POST
        error_occurred = False
        if not all([code_input, nachname, vorname, password, confirm_password]):
            flash("Bitte füllen Sie alle Pflichtfelder aus (Code, Nachname, Vorname, Passwort).", "error")
            error_occurred = True
        if password != confirm_password:
            flash("Die Passwörter stimmen nicht überein.", "error")
            error_occurred = True
        if len(password) < 8 and password: # Nur prüfen, wenn Passwort nicht leer ist (wird schon oben geprüft)
            flash('Das Passwort muss mindestens 8 Zeichen lang sein.', 'error')
            error_occurred = True

        # Zusätzliche Prüfung, ob der manuell eingegebene oder geänderte Code beim POST schon existiert
        # Dies ist wichtig, falls der Benutzer den vorab generierten Code ändert.
        # Die add_regular_user_db hat bereits eine Unique-Constraint-Prüfung,
        # aber eine frühere Prüfung hier kann die UX verbessern.
        existing_user_with_code = fetch_user(code_input)
        if existing_user_with_code:
            flash(f"Der Code '{code_input}' wird bereits verwendet. Bitte wählen Sie einen anderen.", "error")
            error_occurred = True

        if not error_occurred:
            if add_regular_user_db(code_input, nachname, vorname, password, email, kommentar, is_admin_form):
                flash(f"Benutzer '{vorname} {nachname}' erfolgreich hinzugefügt.", "success")
                return redirect(BASE_URL + url_for('admin_dashboard'))
            # Fehlerbehandlung (z.B. doppelter Code durch Race Condition) wird in add_regular_user_db gemacht und geflasht
            # Dies würde bedeuten, dass das Formular erneut angezeigt wird.

        # Wenn ein Fehler beim POST auftrat, das Formular mit den eingegebenen Daten erneut anzeigen
        # und den Code behalten, den der Benutzer eingegeben/gesehen hat.
        return render_template('add_user.html',
                               user=admin_user,
                               current_code=code_input, # Den vom User eingegebenen Code wiederverwenden
                               # Die anderen Felder werden im Template via request.form gefüllt, falls vorhanden
                               form_data=request.form
                              )

    # GET Request: Neuen, garantiert eindeutigen zufälligen Code generieren
    generated_code = None
    attempts = 0
    max_attempts = 100 # Sicherheitslimit, um eine Endlosschleife zu verhindern (extrem unwahrscheinlich)

    while attempts < max_attempts:
        potential_code = ''.join(random.choices(string.digits, k=10))
        if not fetch_user(potential_code): # fetch_user prüft, ob der Code existiert
            generated_code = potential_code
            break
        attempts += 1

    if not generated_code:
        # Fallback, falls nach max_attempts kein eindeutiger Code gefunden wurde
        # (Dies sollte praktisch nie passieren mit 10^10 Möglichkeiten)
        flash("Konnte keinen eindeutigen Code generieren. Bitte versuchen Sie es manuell oder später erneut.", "error")
        # Optional: einen leeren Code oder einen Platzhalter übergeben
        generated_code = ""

    return render_template('add_user.html', user=admin_user, current_code=generated_code, form_data=None)


@app.route('/admin/api_users', methods=['GET', 'POST'])
def admin_manage_api_users():
    """
    Verwaltet API-Benutzer, zeigt eine Liste an und erlaubt das Hinzufügen neuer.

    Diese Route ist nur für Administratoren zugänglich. Bei einer GET-Anfrage
    wird eine Seite mit einer Liste aller API-Benutzer und einem Formular zum
    Hinzufügen eines neuen API-Benutzers angezeigt. Bei einer POST-Anfrage (aus
    dem Hinzufügen-Formular) wird versucht, den neuen API-Benutzer zu erstellen.

    Returns:
        werkzeug.wrappers.response.Response: Bei GET das gerenderte Template
        `admin_manage_api_users.html`. Bei POST eine Weiterleitung zurück zur
        gleichen Seite (`admin_manage_api_users`) mit entsprechenden
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
        return redirect(BASE_URL + url_for('admin_manage_api_users')) # Nach POST zur gleichen Seite zurück

    api_users = get_all_api_users()
    return render_template('admin_manage_api_users.html', user=admin_user, api_users=api_users)


@app.route('/admin/api_user/<int:api_user_id>')
def admin_api_user_detail(api_user_id):
    """
    Zeigt die Detailansicht für einen spezifischen API-Benutzer inklusive seiner API-Keys.

    Diese Route ist nur für Administratoren zugänglich. Sie prüft, ob der
    anfragende Benutzer ein eingeloggter, aktiver Administrator ist.
    Die Details des API-Benutzers und seiner zugehörigen API-Keys werden aus
    der Datenbank geladen und im Template `admin_api_user_detail.html` dargestellt.

    Args:
        api_user_id (int): Die ID des anzuzeigenden API-Benutzers.

    Returns:
        werkzeug.wrappers.response.Response: Das gerenderte Template
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

    target_api_user = get_api_user_by_id(api_user_id)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_manage_api_users'))

    api_keys = get_api_keys_for_api_user(api_user_id)
    return render_template('admin_api_user_detail.html', user=admin_user, api_user=target_api_user, api_keys=api_keys)


@app.route('/admin/api_user/<int:api_user_id>/generate_key', methods=['POST'])
def admin_generate_api_key_for_user(api_user_id):
    """
    Generiert einen neuen API-Key für einen spezifischen API-Benutzer.

    Diese Route ist nur für Administratoren zugänglich und erfordert eine POST-Anfrage.
    Sie prüft, ob der anfragende Benutzer ein eingeloggter, aktiver Administrator ist.
    Der API-Benutzer, für den ein Key generiert wird, wird durch `api_user_id`
    identifiziert. Der neu generierte Key wird einmalig per Flash-Nachricht
    angezeigt und muss vom Administrator sofort kopiert werden.

    Args:
        api_user_id (int): Die ID des API-Benutzers, für den ein Key generiert werden soll.

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

    target_api_user = get_api_user_by_id(api_user_id)
    if not target_api_user:
        flash("API-Benutzer nicht gefunden, für den ein Key generiert werden soll.", "error")
        return redirect(BASE_URL + url_for('admin_manage_api_users'))

    new_key_string = generate_api_key_string()
    if add_api_key_for_user_db(api_user_id, new_key_string):
        # WICHTIG: Den Key nur dieses eine Mal anzeigen!
        flash(f"Neuer API-Key für '{target_api_user['username']}' generiert: {new_key_string}. Bitte sofort sicher kopieren!", "success")
    else:
        # Fehler wurde bereits in add_api_key_for_user_db geflasht
        pass

    return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id=api_user_id))


@app.route('/admin/api_key/<int:api_key_id>/delete', methods=['POST'])
def admin_delete_api_key(api_key_id):
    """
    Löscht einen spezifischen API-Key.

    Diese Route ist nur für Administratoren zugänglich und erfordert eine POST-Anfrage.
    Sie prüft, ob der anfragende Benutzer ein eingeloggter, aktiver Administrator ist.
    Der zu löschende API-Key wird durch `api_key_id` identifiziert.
    Die ID des zugehörigen API-Benutzers (`api_user_id_for_redirect`) wird aus dem
    Formular erwartet, um korrekt zur Detailseite des API-Benutzers zurückleiten
    zu können.

    Args:
        api_key_id (int): Die ID des zu löschenden API-Keys.

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

    if delete_api_key_db(api_key_id):
        flash(f"API-Key (ID: {api_key_id}) erfolgreich gelöscht.", "success")
    else:
        # Fehler wurde bereits in delete_api_key_db geflasht, oder der Key existierte nicht
        flash(f"API-Key (ID: {api_key_id}) konnte nicht gelöscht werden oder wurde nicht gefunden.", "warning")

    if api_user_id_for_redirect:
        return redirect(BASE_URL + url_for('admin_api_user_detail', api_user_id=api_user_id_for_redirect))
    # Fallback, falls die api_user_id nicht ermittelt werden konnte
    return redirect(BASE_URL + url_for('admin_manage_api_users'))


@app.route('/admin/api_user/<int:api_user_id>/delete', methods=['POST']) # Nur POST für Löschaktionen
def admin_delete_api_user(api_user_id):
    """
    Löscht einen API-Benutzer und alle zugehörigen API-Keys.

    Diese Route ist nur für Administratoren zugänglich und erfordert eine POST-Anfrage.
    Vor dem Löschen wird geprüft, ob der anfragende Benutzer ein eingeloggter,
    aktiver Administrator ist. Der zu löschende API-Benutzer wird anhand der
    `api_user_id` identifiziert. Nach erfolgreichem Löschen oder bei Fehlern
    erfolgt eine Weiterleitung zur API-Benutzerverwaltungsseite mit einer
    entsprechenden Flash-Nachricht.

    Args:
        api_user_id (int): Die ID des zu löschenden API-Benutzers.

    Returns:
        werkzeug.wrappers.response.Response: Eine Weiterleitung zur
        API-Benutzerverwaltungsseite (`admin_manage_api_users`) oder zur Login- bzw.
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

    api_user_to_delete = get_api_user_by_id(api_user_id)
    if not api_user_to_delete:
        flash("Zu löschender API-Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_manage_api_users'))

    if delete_api_user_and_keys_db(api_user_id):
        flash(f"API-Benutzer '{api_user_to_delete['username']}' und zugehörige API-Keys wurden gelöscht.", "success")
    else:
        flash(f"Fehler beim Löschen des API-Benutzers '{api_user_to_delete['username']}'.", "error") # Genauere Fehlermeldung kommt von DB-Funktion

    return redirect(BASE_URL + url_for('admin_manage_api_users'))


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
    if not logged_in_user_id:
        flash("Bitte zuerst einloggen.", "info")
        return redirect(BASE_URL + url_for('login'))

    admin_user = get_user_by_id(logged_in_user_id)
    if not (admin_user and admin_user['is_admin']):
        flash("Zugriff verweigert. Admin-Rechte erforderlich.", "error")
        return redirect(BASE_URL + url_for('user_info'))

    if admin_user.get('is_locked'):
        session.pop('user_id', None)
        flash('Ihr Administratorkonto wurde gesperrt.', 'error')
        return redirect(BASE_URL + url_for('login'))

    target_user = get_user_by_id(user_id)
    if not target_user:
        flash("Benutzer nicht gefunden.", "error")
        return redirect(BASE_URL + url_for('admin_dashboard'))

    nfc_tokens = get_user_nfc_tokens(user_id)
    transactions = get_user_transactions(user_id)
    saldo = get_saldo_for_user(user_id)

    if request.method == 'POST':
        if 'delete_transactions' in request.form:
            if delete_all_transactions(user_id):
                flash('Alle Transaktionen für diesen Benutzer wurden gelöscht.', 'success')
            else:
                flash('Fehler beim Löschen der Transaktionen.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'add_transaction' in request.form:
            beschreibung = request.form.get('beschreibung', '')
            saldo_aenderung_str = request.form.get('saldo_aenderung')
            if not beschreibung:
                flash('Beschreibung für Transaktion darf nicht leer sein.', 'error')
            elif saldo_aenderung_str is None:
                flash('Saldoänderung für Transaktion darf nicht leer sein.', 'error')
            else:
                try:
                    saldo_aenderung = int(saldo_aenderung_str)
                    if add_transaction(user_id, beschreibung, saldo_aenderung):
                        flash('Transaktion erfolgreich hinzugefügt.', 'success')
                    # Fehler wird in add_transaction geflasht
                except ValueError:
                    flash('Ungültiger Wert für Saldoänderung. Es muss eine Zahl sein.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'lock_user' in request.form:
            if toggle_user_lock(user_id, True):
                flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {user_id}) wurde gesperrt.', 'success')
            else:
                flash('Fehler beim Sperren des Benutzers.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'unlock_user' in request.form:
            if toggle_user_lock(user_id, False):
                flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {user_id}) wurde entsperrt.', 'success')
            else:
                flash('Fehler beim Entsperren des Benutzers.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'promote_user' in request.form:
            if toggle_user_admin(user_id, True):
                flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {user_id}) wurde zum Admin befördert.', 'success')
            else:
                flash('Fehler beim Befördern des Benutzers.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'demote_user' in request.form:
            if toggle_user_admin(user_id, False):
                flash(f'Admin "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {user_id}) wurde zum Benutzer degradiert.', 'success')
            else:
                flash('Fehler beim Degradieren des Admins.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'delete_user' in request.form:
            # Sicherheitsabfrage, ob der Admin sich selbst löschen will
            if user_id == logged_in_user_id:
                flash("Sie können sich nicht selbst löschen.", "warning")
                return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

            if delete_user(user_id): # delete_user löscht auch Transaktionen durch DB CASCADE
                flash(f'Benutzer "{target_user.get("nachname", "")}, {target_user.get("vorname", "")}" (ID {user_id}) wurde gelöscht.', 'success')
                return redirect(BASE_URL + url_for('admin_dashboard'))
            flash('Fehler beim Löschen des Benutzers.', 'error')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'add_user_nfc_token' in request.form:
            nfc_token_name = request.form.get('nfc_token_name')
            nfc_token_daten = request.form.get('nfc_token_daten') # HEX Format erwartet
            if not nfc_token_name or not nfc_token_daten:
                flash('Token Name und Token Daten (HEX) dürfen nicht leer sein.', 'error')
            elif add_user_nfc_token(user_id, nfc_token_name, nfc_token_daten): # Fehlerbehandlung in Funktion
                flash('NFC-Token erfolgreich hinzugefügt.', 'success')
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

        if 'update_user_comment' in request.form:
            comment = request.form.get('kommentar')
            if not comment:
                flash('Kommentar darf nicht leer sein.', 'error')
            elif update_user_comment(user_id, comment):
                flash('Kommentar erfolgreich aktualisiert.', 'success')

        if 'update_user_email' in request.form:
            email = request.form.get('email')
            if not email:
                flash('Emailadresse darf nicht leer sein.', 'error')
            elif update_user_email(user_id, email):
                flash('Emailadresse erfolgreich aktualisiert.', 'success')

        if 'delete_user_nfc_token' in request.form:
            nfc_token_id = request.form.get('nfc_token_id')
            if not nfc_token_id:
                flash('Keine Token ID zum Löschen übergeben.', 'error')
            elif delete_user_nfc_token(user_id, nfc_token_id):
                flash('NFC-Token erfolgreich entfernt.', 'success')
            # Fehler in Funktion
            return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))
        flash('Ungültige oder fehlende Aktion.', 'error')
        return redirect(BASE_URL + url_for('admin_user_modification', user_id=user_id))

    return render_template('admin_user_modification.html', user=target_user, nfc_tokens=nfc_tokens, transactions=transactions, saldo=saldo, admin_user=admin_user)


@app.route('/logout')
def logout():
    """
    Meldet den Benutzer ab, indem die Benutzer-ID aus der Session entfernt wird.

    Returns:
        str: Eine Weiterleitung zur Login-Seite.
    """

    session.pop('user_id', None)
    flash("Erfolgreich abgemeldet.", "info")
    return redirect(BASE_URL + url_for('login'))


if __name__ == '__main__':
    debug_mode = os.getenv('FLASK_DEBUG', 'False').lower() in ['true', '1', 'yes']
    app.run(host='127.0.0.1', port=5001, debug=debug_mode)
