"""Verwaltet den Datenbankverbindungspool für die Anwendung."""

import contextlib
import logging
import sys
import threading
import time

import mysql.connector
from mysql.connector import Error, pooling

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
                cls._connection_pool = pooling.MySQLConnectionPool(pool_name="dbpool", **database_config)
                logger.info("Datenbankverbindungspool erfolgreich initialisiert.")
            except mysql.connector.Error as e:
                logger.error("Fehler beim Initialisieren des Datenbankverbindungspools: %s", e)
                raise  # Wirf den Fehler weiter, damit die Anwendung reagieren kann

    @classmethod
    def _health_check_loop(cls):
        """
        Prüft periodisch die Verbindung des Datenbankpools zur Datenbank

        Alle 30 Sekunden wird ein "SELECT 1" ausgeführt, um die Verbindung
        zum Datenbankpool zu testen und die Verbindung am Leben zu halten
        and verify pool status.
        """

        logger.info("Datenbank Health-Check gestartet (Interval: 30s).")
        while True:
            if cls._connection_pool is None:
                logger.warning("Health-Check: Pool wurde noch nicht initialisiert. Warte 30 Sekunden.")
                time.sleep(30)
                continue

            cnx = None
            try:
                # Get connection from pool
                cnx = cls.get_connection()

                if cnx:
                    # Perform a simple query
                    with cnx.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        cursor.fetchone()
                    logger.debug("Datenbank Health-Check erfolgreich.")
                else:
                    logger.warning(
                        "Datenbank Health-Check nicht erfolgreich. Konnte keine Verbindung aus dem Pool bekommen."
                    )

            except Error as err:
                # Error from mysql.connector (e.g., connection lost)
                logger.error("Datenbank Health-Check Query fehlgeschlagen: %s", err)
            except RuntimeError as e:
                # This might happen if pool is None and get_connection raises it
                logger.error("Datenbank Health-Check runtime error (pool not init?): %s", e)
            except Exception as e:  # pylint: disable=W0718
                # Catch other potential unexpected errors
                logger.error("Unerwarteter Fehler beim Datenbank Health-Check: %s", e)

            finally:
                # Always release the connection back to the pool
                if cnx:
                    cls.close_connection(cnx)

            # wait for 30 seconds
            time.sleep(30)

    @classmethod
    def start_health_check_thread(cls):
        """
        Startet den Health-Check im Hintergrund
        """

        if cls._connection_pool is None:
            logger.error("Konnte den Health-Check nicht starten, da der Pool noch nicht initialisiert ist!")
            return

        try:
            health_thread = threading.Thread(target=cls._health_check_loop, daemon=True)
            health_thread.start()
        except Exception as e:  # pylint: disable=W0718
            logger.critical("Unbekannter Fehler beim Starten des Datenbank Health-Check Threads: %s", e)

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
            logger.error("Fehler beim Abrufen einer Verbindung aus dem Pool: %s", e)
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

    @classmethod
    @contextlib.contextmanager
    def connection_manager(cls, database_config=None):
        """
        Kontextmanager, der eine Verbindung aus dem Pool bereitstellt und
        beim Verlassen automatisch wieder schliesst.

        Verwendung:
            with DatabaseConnectionPool.connection_manager(config.db_config) as cnx:
                with cnx.cursor(dictionary=True) as cursor:
                    cursor.execute(...)
        """
        cnx = None
        try:
            cnx = cls.get_connection(database_config)
            yield cnx
        finally:
            if cnx:
                cls.close_connection(cnx)

    @classmethod
    def fetch_all(cls, query, params=None, dictionary=True):
        """Führt eine SELECT-Abfrage aus und gibt alle Zeilen zurück.

        Gibt eine leere Liste bei Fehlern zurück.
        """
        try:
            with cls.connection_manager(database_config=None) as cnx:
                if not cnx:
                    return []
                with cnx.cursor(dictionary=dictionary) as cursor:
                    cursor.execute(query, params or ())
                    return cursor.fetchall()
        except Error as e:
            logger.error("fetch_all Fehler: %s | Query: %s | Params: %s", e, query, params)
            return []

    @classmethod
    def fetch_one(cls, query, params=None, dictionary=True):
        """Führt eine SELECT-Abfrage aus und gibt die erste Zeile zurück oder None bei Fehlern."""
        try:
            with cls.connection_manager(database_config=None) as cnx:
                if not cnx:
                    return None
                with cnx.cursor(dictionary=dictionary) as cursor:
                    cursor.execute(query, params or ())
                    return cursor.fetchone()
        except Error as e:
            logger.error("fetch_one Fehler: %s | Query: %s | Params: %s", e, query, params)
            return None

    @classmethod
    def execute_commit(cls, query, params=None):
        """Führt ein INSERT/UPDATE/DELETE aus, committet und gibt Cursor-Infos zurück.

        Rückgabe: (True, lastrowid) bei Erfolg, (False, None) bei Fehler.
        """
        cnx = None
        try:
            with cls.connection_manager(database_config=None) as cnx:
                if not cnx:
                    return False, None
                with cnx.cursor() as cursor:
                    cursor.execute(query, params or ())
                    cnx.commit()
                    return True, getattr(cursor, "lastrowid", None)
        except Error as e:
            logger.error("execute_commit Fehler: %s | Query: %s | Params: %s", e, query, params)
            if cnx:
                try:
                    cnx.rollback()
                except Error as rb_err:
                    logger.debug("Rollback fehlgeschlagen: %s", rb_err)
            return False, None
        except Exception as e:  # pylint: disable=W0718
            logger.error("execute_commit Unerwarteter Fehler: %s | Query: %s | Params: %s", e, query, params)
            return False, None


# Exportiere die wichtigsten Methoden als Modulattribute
fetch_one = DatabaseConnectionPool.fetch_one
fetch_all = DatabaseConnectionPool.fetch_all
execute_commit = DatabaseConnectionPool.execute_commit
