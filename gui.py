"""WebGUI für den Feuerwehr-Versorgungs-Helfer"""

import os
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__, static_url_path=os.environ.get('STATIC_URL_PREFIX', '/static'))
app.config['SECRET_KEY'] = os.urandom(24)

app.config['MYSQL_HOST'] = os.getenv("MYSQL_HOST")
app.config['MYSQL_USER'] = os.getenv("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.getenv("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.getenv("MYSQL_DB")


def get_db_connection():
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


def delete_user(user_id):
    """
    Löscht einen Benutzer anhand seiner ID.

    Args:
        user_id (int): Die ID des zu löschenden Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            query = "DELETE FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Löschen des Benutzers: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return False
    return False


def fetch_user(code):
    """
    Ruft einen Benutzer aus der Datenbank anhand seines Codes ab.

    Args:
        code (str): Der eindeutige Code des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, name, password, is_admin) oder None, falls kein Benutzer gefunden wird.
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT id, code, name, password, is_admin FROM users WHERE code = %s"
        cursor.execute(query, (code,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user
    return None


def get_user_by_id(user_id):
    """
    Ruft einen Benutzer aus der Datenbank anhand seiner ID ab.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        dict: Ein Dictionary mit den Benutzerdaten (id, code, name, is_admin, password) oder None, falls kein Benutzer gefunden wird.
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT id, code, name, is_admin, password FROM users WHERE id = %s"
        cursor.execute(query, (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user
    return None


def get_total_credits_for_user(user_id):
    """
    Berechnet die Summe der Credits für den Benutzer mit der übergebenen user_id.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        int: Die Summe der Credits oder 0, falls kein Benutzer gefunden wird.
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        query = "SELECT SUM(credits) FROM transactions WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        total_credits = cursor.fetchone()[0] or 0
        cursor.close()
        conn.close()
        return total_credits
    return 0


def get_total_credits_by_user():
    """
    Berechnet die Summe der Credits für jeden Benutzer.

    Returns:
        dict: Ein Dictionary, wobei der Schlüssel die Benutzer-ID und der Wert die Summe der Credits ist.
              Enthält alle Benutzer, auch solche ohne Transaktionen (Wert dann 0).
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT u.id, SUM(t.credits) AS total_credits
            FROM users u
            LEFT JOIN transactions t ON u.id = t.user_id
            GROUP BY u.id
        """
        cursor.execute(query)
        credits_by_user = {row['id']: row['total_credits'] or 0 for row in cursor.fetchall()}
        cursor.close()
        conn.close()
        return credits_by_user
    return {}


def get_all_users():
    """
    Ruft alle Benutzer aus der Datenbank ab, sortiert nach Namen.

    Returns:
        list: Eine Liste von Dictionaries, wobei jedes Dictionary einen Benutzer repräsentiert
              (id, code, name, is_admin).
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT id, code, name, is_admin FROM users ORDER BY name"
        cursor.execute(query)
        users = cursor.fetchall()
        cursor.close()
        conn.close()
        return users
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

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        query = "SELECT id, article, credits, timestamp FROM transactions WHERE user_id = %s ORDER BY timestamp DESC"
        cursor.execute(query, (user_id,))
        transactions = cursor.fetchall()
        cursor.close()
        conn.close()
        return transactions
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

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        query = "INSERT INTO transactions (user_id, article, credits) VALUES (%s, %s, %s)"
        try:
            cursor.execute(query, (user_id, article, credits_change))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Hinzufügen der Transaktion: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return False
    return False


def delete_all_transactions(user_id):
    """
    Löscht alle Transaktionen eines Benutzers.

    Args:
        user_id (int): Die ID des Benutzers.

    Returns:
        bool: True bei Erfolg, False bei Fehler.
    """

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        query = "DELETE FROM transactions WHERE user_id = %s"
        try:
            cursor.execute(query, (user_id,))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Löschen der Transaktionen: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return False
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

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            query = "UPDATE users SET password = %s WHERE id = %s"
            cursor.execute(query, (new_password_hash, user_id))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except mysql.connector.Error as err:
            print(f"Fehler beim Aktualisieren des Passworts: {err}")
            conn.rollback()
            cursor.close()
            conn.close()
            return False
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
            return redirect(url_for('user_info'))
        else:
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
        return redirect(url_for('login'))

    user = get_user_by_id(user_id)
    transactions = get_user_transactions(user_id)
    total_credits = sum(t['credits'] for t in transactions) if transactions else 0

    if request.method == 'POST':
        if 'change_password' in request.form:

            current_password = request.form['current_password']
            new_password = request.form['new_password']
            confirm_new_password = request.form['confirm_new_password']

            print(f"Aktuell: {current_password}, Neu: {new_password}, Bestätigung: {confirm_new_password}") # Debug-Ausgabe

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
                    return redirect(url_for('user_info'))
                else:
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
    return redirect(url_for('login'))


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
        return redirect(url_for('login'))

    target_user = get_user_by_id(user_id)
    transactions = get_user_transactions(user_id)
    total_credits = get_total_credits_for_user(user_id)

    if request.method == 'POST':
        if 'delete_transactions' in request.form:
            if delete_all_transactions(user_id):
                flash('Alle Transaktionen für diesen Benutzer wurden gelöscht.', 'success')
                return redirect(url_for('admin_user_transactions', user_id=user_id))
            else:
                flash('Fehler beim Löschen der Transaktionen.', 'error')
        elif 'add_transaction' in request.form:
            article = request.form['article']
            credits_change = int(request.form['credits'])
            if add_transaction(user_id, article, credits_change):
                flash('Transaktion erfolgreich hinzugefügt.', 'success')
                return redirect(url_for('admin_user_transactions', user_id=user_id))
        elif 'delete_user' in request.form:
            if delete_user(user_id):
                flash(f'Benutzer "{target_user["name"]}" (ID {user_id}) wurde gelöscht.', 'success')
                return redirect(url_for('admin_dashboard')) # Zurück zur Benutzerübersicht
            else:
                flash(f'Fehler beim Löschen des Benutzers "{target_user["name"]}" (ID {user_id}).', 'error')

    return render_template('admin_user_transactions.html', user=target_user, transactions=transactions, total_credits=total_credits)


@app.route('/logout')
def logout():
    """
    Meldet den Benutzer ab, indem die Benutzer-ID aus der Session entfernt wird.

    Returns:
        str: Eine Weiterleitung zur Login-Seite.
    """

    session.pop('user_id', None)
    return redirect(url_for('login'))


if __name__ == '__main__':
    app.run(debug=True)
