"""Verwaltet den Datenbankverbindungspool für die Anwendung."""
import logging
import sys
import mysql.connector
from mysql.connector import pooling, Error  # Error hier importiert

logger = logging.getLogger(__name__)

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
    def initialize_pool(cls, database_config):
        """
        Initialisiert den Datenbankverbindungspool.

        Diese Klassenmethode erstellt einen Pool von Datenbankverbindungen basierend auf
        der übergebenen Konfiguration. Sie sollte einmalig beim Start der Anwendung aufgerufen
        werden.

        Args:
            database_config (dict): Ein Dictionary, das die Konfigurationsparameter für die
                             Datenbankverbindung enthält (z.B. host, user, password, database).

        Raises:
            mysql.connector.Error: Wenn beim Initialisieren des Pools ein Fehler auftritt.
        """

        if cls._connection_pool is None:
            try:
                cls._connection_pool = pooling.MySQLConnectionPool(
                    pool_name="dbpool", pool_size=3, **database_config
                )
                logger.info("Datenbankverbindungspool erfolgreich initialisiert.")
            except mysql.connector.Error as e:
                logger.error(
                    f"Fehler beim Initialisieren des Datenbankverbindungspools: {e}"
                )
                raise  # Wirf den Fehler weiter, damit die Anwendung reagieren kann


    @classmethod
    def get_connection(cls, database_config=None):
        """
        Ruft eine Datenbankverbindung aus dem Pool ab.
        Initialisiert den Pool bei Bedarf.

        Diese Klassenmethode ruft eine freie Datenbankverbindung aus dem Pool ab.
        Wenn der Pool noch nicht initialisiert wurde, wird er initialisiert, falls eine
        Datenbankkonfiguration übergeben wird.

        Args:
            database_config (dict, optional): Ein Dictionary mit den Datenbankkonfigurationsparametern.
                                        Wird benötigt, um den Pool zu initialisieren, wenn er noch nicht
                                        initialisiert ist. Defaults to None.

        Returns:
            mysql.connector.connection_cext.CMySQLConnection: Eine Datenbankverbindung,
                                                            falls erfolgreich. None, falls kein Pool initialisiert
                                                            werden konnte und auch keine Verbindung abgerufen werden konnte.

        Raises:
            RuntimeError: Wenn der Datenbankverbindungspool nicht initialisiert wurde und kein
                          database_config übergeben wurde.
            mysql.connector.Error: Wenn beim Abrufen einer Verbindung ein Fehler auftritt.
        """

        if cls._connection_pool is None and database_config:
            try:
                cls.initialize_pool(database_config)
            except Error:  # Hier Error verwenden
                logger.critical("Fehler beim Initialisieren des Pools in get_connection")
                sys.exit(1)  # Kritischer Fehler: Anwendung beenden
        if cls._connection_pool is None:
            raise RuntimeError(
                "Datenbankverbindungspool wurde nicht initialisiert."
            )  # Fehler, wenn Pool nicht initialisiert
        try:
            cnx = cls._connection_pool.get_connection()
            return cnx
        except mysql.connector.Error as e:
            logger.error(f"Fehler beim Abrufen einer Verbindung aus dem Pool: {e}")
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
