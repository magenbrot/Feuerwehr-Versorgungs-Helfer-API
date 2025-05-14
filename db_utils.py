"""Verwaltet den Datenbankverbindungspool für die Anwendung."""
import mysql.connector
from mysql.connector import pooling

class DatabaseConnectionPool:
    """
    Verwaltet den Datenbankverbindungspool für die Anwendung.

    Diese Klasse stellt Methoden zum Initialisieren des Pools, Abrufen von Verbindungen
    aus dem Pool und Freigeben von Verbindungen bereit. Sie kapselt die Details der
    Datenbankverbindungsverwaltung, um die Wiederverwendung von Verbindungen zu optimieren
    und die Leistung der Anwendung zu verbessern.
    """

    _connection_pool = None  # Klassenvariable zur Speicherung des Verbindungspools


    @classmethod
    def initialize_pool(cls, db_config):
        """
        Initialisiert den Datenbankverbindungspool.

        Diese Klassenmethode erstellt einen Pool von Datenbankverbindungen basierend auf
        der übergebenen Konfiguration. Sie sollte einmalig beim Start der Anwendung aufgerufen
        werden.

        Args:
            db_config (dict): Ein Dictionary, das die Konfigurationsparameter für die
                             Datenbankverbindung enthält (z.B. host, user, password, database).

        Raises:
            mysql.connector.Error: Wenn beim Initialisieren des Pools ein Fehler auftritt.
        """
        if cls._connection_pool is None:
            try:
                cls._connection_pool = pooling.MySQLConnectionPool(
                    pool_name="dbpool", pool_size=5, **db_config
                )
                print("Datenbankverbindungspool erfolgreich initialisiert (db_utils).")
            except mysql.connector.Error as e:
                print(
                    f"Fehler beim Initialisieren des Datenbankverbindungspools (db_utils): {e}"
                )
                raise  # Wirf den Fehler weiter, damit die Anwendung reagieren kann


    @classmethod
    def get_connection(cls):
        """
        Ruft eine Datenbankverbindung aus dem Pool ab.

        Diese Klassenmethode ruft eine freie Datenbankverbindung aus dem Pool ab.
        Wenn der Pool noch nicht initialisiert wurde, wird eine Exception ausgelöst.

        Returns:
            mysql.connector.connection_cext.CMySQLConnection: Eine Datenbankverbindung,
                                                            falls erfolgreich.

        Raises:
            RuntimeError: Wenn der Datenbankverbindungspool nicht initialisiert wurde.
            mysql.connector.Error: Wenn beim Abrufen einer Verbindung ein Fehler auftritt.
        """
        if cls._connection_pool is None:
            raise RuntimeError("Datenbankverbindungspool wurde nicht initialisiert.")  # Verwende RuntimeError
        try:
            cnx = cls._connection_pool.get_connection()
            return cnx
        except mysql.connector.Error as e:
            print(f"Fehler beim Abrufen einer Verbindung aus dem Pool (db_utils): {e}")
            return None


    @classmethod
    def close_connection(cls, cnx):
        """
        Gibt eine Datenbankverbindung an den Pool zurück.

        Diese Klassenmethode gibt eine zuvor abgerufene Datenbankverbindung an den Pool zurück.
        Es ist wichtig, diese Methode aufzurufen, wenn die Verbindung nicht mehr benötigt wird,
        um sicherzustellen, dass sie von anderen Teilen der Anwendung wiederverwendet werden kann.

        Args:
            cnx (mysql.connector.connection_cext.CMySQLConnection): Die Datenbankverbindung,
                                                                    die an den Pool zurückgegeben
                                                                    werden soll. Wenn None übergeben
                                                                    wird, wird die Methode beendet.
        """
        if cnx:
            cnx.close()
