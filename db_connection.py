"""Definiert gemeinsam genutzte Funktionen für DB-Verbindungen."""

import mysql.connector


def get_db_connection(host, user, password, database):
    """
    Stellt eine Verbindung zur MySQL-Datenbank her.

    Args:
        host (str): Der Hostname oder die IP-Adresse des MySQL-Servers.
        user (str): Der Benutzername für die Datenbankverbindung.
        password (str): Das Passwort für den angegebenen Benutzer.
        database (str): Der Name der Datenbank, mit der verbunden werden soll.

    Returns:
        mysql.connector.MySQLConnection or None: Das Datenbankverbindungsobjekt oder None bei einem Fehler.
    """

    try:
        mydb = mysql.connector.connect(host=host,
                                       user=user,
                                       password=password,
                                       database=database)
        print("Datenbankverbindung hergestellt")
        return mydb
    except mysql.connector.Error as err:
        print(f"Fehler bei der Verbindung zur Datenbank: {err}")
        return None


def close_db_connection(mydb):
    """
    Schließt die Datenbankverbindung.

    Args:
        mydb (mysql.connector.MySQLConnection): Das Datenbankverbindungsobjekt.
    """

    if mydb and mydb.is_connected():
        print("Datenbankverbindung geschlossen")
        mydb.close()
