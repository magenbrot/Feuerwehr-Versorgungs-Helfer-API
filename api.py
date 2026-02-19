"""Dieses Modul ist eine API Middleware für den Feuerwehr-Versorgungs-Helfer"""

import base64
import binascii
import datetime
import json
import logging
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Literal

from flask import Flask, jsonify, render_template, request
from mysql.connector import Error

import config
import db_utils
import email_sender

logging.basicConfig(
    level=config.api_config["log_level"],
    format="%(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["DEBUG"] = config.api_config["flask_debug_mode"]
app.config["JSON_AS_ASCII"] = False

# Konfigurationsprüfungen
required_db_keys = ["host", "port", "user", "password", "database"]
if not all(key in config.db_config and config.db_config[key] is not None for key in required_db_keys):
    logger.critical(
        "Fehler: Nicht alle Datenbank-Konfigurationsvariablen sind gesetzt. Benötigt: %s", ", ".join(required_db_keys)
    )
    sys.exit(1)

try:
    config.db_config["port"] = int(config.db_config["port"])
except ValueError:
    logger.critical("Fehler: Datenbank-Port '%s' ist keine gültige Zahl.", config.db_config.get("port"))
    sys.exit(1)

required_smtp_keys = ["host", "port", "user", "password", "sender"]
if not all(key in config.smtp_config and config.smtp_config[key] is not None for key in required_smtp_keys):
    logger.critical(
        "Fehler: Nicht alle SMTP-Konfigurationsvariablen sind gesetzt. Benötigt: %s", ", ".join(required_smtp_keys)
    )
    sys.exit(1)

try:
    config.smtp_config["port"] = config.smtp_config["port"]
except ValueError:
    logger.critical("Fehler: SMTP_PORT '%s' ist keine gültige Zahl.", config.smtp_config.get("port"))
    sys.exit(1)

# Initialisiere den Datenbank-Pool einmal beim Start der Anwendung # pylint: disable=R0801
if os.environ.get("TESTING") != "True":
    try:
        db_utils.DatabaseConnectionPool.initialize_pool(config.db_config)
    except Error as e:
        logger.info("Kritischer Fehler beim Starten der Datenbankverbindung: %s", e)
        sys.exit(1)

# Lade das Manifest mit Author- und Versionsinfos
try:
    with open("manifest.json", encoding="utf-8") as manifest:
        app.config.update(json.load(manifest))
except FileNotFoundError:
    app.config.update(version="N/A", author="N/A")

logger.info("Feuerwehr-Versorgungs-Helfer API (Version %s) wurde gestartet", app.config.get("version"))


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

    empfaenger_email = email_params.get("empfaenger_email")
    betreff = email_params.get("betreff")
    template_name_html = email_params.get("template_name_html")
    template_name_text = email_params.get("template_name_text")
    template_context = email_params.get("template_context", {})
    logo_dateipfad_str = email_params.get("logo_dateipfad")

    if not all([empfaenger_email, betreff, template_name_html, template_name_text]):
        logger.error(
            "Unvollständige E-Mail-Parameter. Benötigt: empfaenger_email, betreff, template_name_html, template_name_text."
        )
        return False

    # Helfe Pylance mit Assertions, um den Typ zu verstehen
    assert betreff is not None
    assert empfaenger_email is not None
    assert template_name_html is not None
    assert template_name_text is not None

    logo_exists = False
    if logo_dateipfad_str:
        logo_path_obj = Path(logo_dateipfad_str)
        if logo_path_obj.is_file():
            logo_exists = True
        else:
            logger.warning("Logo-Datei nicht gefunden unter: %s", logo_dateipfad_str)

    try:
        template_context_final = template_context.copy()
        template_context_final["logo_exists_fuer_template"] = logo_exists

        with app.app_context():
            final_html_body = render_template(template_name_html, **template_context_final)
            final_text_body = render_template(template_name_text, **template_context_final)

    except Exception as e:  # pylint: disable=W0718
        logger.error("Fehler beim Rendern der E-Mail-Templates für '%s': %s", template_name_html, e, exc_info=True)
        return False

    email_content_dict = {
        "html": final_html_body,
        "text": final_text_body,
        "logo_pfad": logo_dateipfad_str if logo_exists else None,
    }

    return email_sender.sende_formatierte_email(
        empfaenger_email=empfaenger_email, betreff=betreff, content=email_content_dict, smtp_cfg=smtp_cfg
    )


# --- Hilfsfunktionen für Benachrichtigungssystem ---
def get_user_notification_preference(user_id_int: int, event_schluessel: str) -> bool:
    """
    Prüft, ob ein Benutzer eine bestimmte E-Mail-Benachrichtigung aktiviert hat.

    Args:
        user_id_int (int): Die ID des Benutzers.
        event_schluessel (str): Der eindeutige Schlüssel des Benachrichtigungstyps
                                (z.B. 'NEUE_TRANSAKTION').

    Returns:
        bool: True, wenn die Benachrichtigung für den Benutzer aktiviert ist, sonst False.
    """

    query = """
        SELECT bba.email_aktiviert
        FROM benutzer_benachrichtigungseinstellungen bba
        JOIN benachrichtigungstypen bt ON bba.typ_id = bt.id
        WHERE bba.benutzer_id = %s AND bt.event_schluessel = %s
    """
    row = db_utils.fetch_one(query, (user_id_int, event_schluessel), dictionary=True)
    try:
        return bool(row["email_aktiviert"]) if row and row.get("email_aktiviert") is not None else False
    except (KeyError, TypeError):
        return False


def get_system_setting(einstellung_schluessel: str) -> str | None:
    """
    Ruft den Wert einer Systemeinstellung aus der Datenbank ab.

    Args:
        einstellung_schluessel (str): Der Schlüssel der Systemeinstellung (z.B. 'TRANSACTION_SALDO_CHANGE').

    Returns:
        Optional[str]: Der Wert der Einstellung als String, oder None wenn nicht gefunden oder bei Fehler.
    """

    query = "SELECT einstellung_wert FROM system_einstellungen WHERE einstellung_schluessel = %s"
    row = db_utils.fetch_one(query, (einstellung_schluessel,), dictionary=True)
    return row["einstellung_wert"] if row else None


def get_user_details_for_notification(user_id_int: int) -> dict | None:
    """
    Ruft ID, Vorname und E-Mail eines Benutzers für Benachrichtigungszwecke ab.

    Args:
        user_id_int (int): Die ID des Benutzers.

    Returns:
        Optional[dict]: Ein Dictionary mit {'id': int, 'vorname': str, 'email': str} oder None bei Fehler/Nichtgefunden.
    """

    query = "SELECT id, vorname, nachname, email, infomail_user_threshold, infomail_responsible_threshold FROM users WHERE id = %s"
    return db_utils.fetch_one(query, (user_id_int,), dictionary=True)


def _send_saldo_null_benachrichtigung(user_details: dict, aktueller_saldo: float, logo_pfad: str):
    """Hilfsfunktion zum Senden der "Saldo Null" Benachrichtigung."""

    if not get_user_notification_preference(user_details["id"], "SALDO_NULL"):
        return

    email_params = {
        "empfaenger_email": user_details["email"],
        "betreff": "Dein Kontostand hat Null erreicht",
        "template_name_html": "email_saldo_null.html",
        "template_name_text": "email_saldo_null.txt",
        "template_context": {"vorname": user_details["vorname"], "saldo": aktueller_saldo},
        "logo_dateipfad": logo_pfad,
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Saldo-Null Benachrichtigung an %s (ID: %s) gesendet.", user_details["email"], user_details["id"])
    else:
        logger.error(
            "Fehler beim Senden der Saldo-Null Benachrichtigung an %s (ID: %s).",
            user_details["email"],
            user_details["id"],
        )


def _send_user_threshold_benachrichtigung(user_details: dict, aktueller_saldo: int, logo_pfad: str):
    """Hilfsfunktion zum Senden der "Saldowarnung" Benachrichtigung."""

    # Breche ab, wenn der aktuelle Saldo gleich dem gesetzten Limit ist und gleichzeitig größer als das Limit -5
    if not (user_details["infomail_user_threshold"] - 5) < aktueller_saldo <= user_details["infomail_user_threshold"]:
        return

    if not get_user_notification_preference(
        user_details["id"], "THRESHOLD_REMINDER"
    ):  # Guard clause: Wenn User es nicht will, abbrechen
        return

    # Alle Prüfungen bestanden, E-Mail senden
    email_params = {
        "empfaenger_email": user_details["email"],
        "betreff": "Wichtiger Hinweis zu deinem Saldo",
        "template_name_html": "email_info_user_threshold.html",
        "template_name_text": "email_info_user_threshold.txt",
        "template_context": {"vorname": user_details["vorname"], "saldo": aktueller_saldo},
        "logo_dateipfad": logo_pfad,
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Benutzer-Saldowarnung an %s (ID: %s) gesendet.", user_details["email"], user_details["id"])
    else:
        logger.error(
            "Fehler beim Senden der Benutzer-Saldowarnung an %s (ID: %s).", user_details["email"], user_details["id"]
        )


def _send_responsible_threshold_benachrichtigung(user_details: dict, aktueller_saldo: int, logo_pfad: str):
    """Hilfsfunktion zur Information der Verantwortlichen wenn ein Benutzer das System-Limit unterschreitet."""

    # Breche ab, wenn der aktuelle Saldo gleich dem gesetzten Limit ist und gleichzeitig größer als das Limit -5
    if (
        not (user_details["infomail_responsible_threshold"] - 5)
        < aktueller_saldo
        <= user_details["infomail_responsible_threshold"]
    ):
        return

    # Alle Prüfungen bestanden, E-Mail senden
    email_params = {
        "empfaenger_email": config.api_config["responsible_email"],
        "betreff": f"{user_details['vorname']} {user_details['nachname']} hat das Saldo-Info-Limit erreicht",
        "template_name_html": "email_info_responsible_threshold.html",
        "template_name_text": "email_info_responsible_threshold.txt",
        "template_context": {
            "vorname": user_details["vorname"],
            "nachname": user_details["nachname"],
            "infomail_responsible_threshold": user_details["infomail_responsible_threshold"],
            "app_name": config.app_name,
        },
        "logo_dateipfad": logo_pfad,
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info(
            "Verantwortliche-Saldowarnung (%s %s) an Verantwortliche (%s)  gesendet.",
            user_details["vorname"],
            user_details["nachname"],
            config.api_config["responsible_email"],
        )
    else:
        logger.error(
            "Fehler beim Senden der Verantwortliche-Saldowarnung (%s %s) an Verantwortliche (%s).",
            user_details["vorname"],
            user_details["nachname"],
            config.api_config["responsible_email"],
        )


def _aktuellen_saldo_pruefen(
    target_user_id: int, saldo_aenderung: float = 0
) -> Literal[True] | tuple[Literal[False], float, int] | Literal[False]:
    """
    Prüft den aktuellen Saldo eines Benutzers vor einer Transaktion.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Saldo geprüft werden soll.
        saldo_aenderung (float, optional): Die geplante Änderung des Saldos (z.B. -1 für Abbuchung). Default: 0

    Returns:
        True: Wenn der Saldo nach der Änderung ausreichend ist.
        tuple[Literal[False], float, int]: Ein Tupel (False, aktueller_saldo, max_negativ_saldo),
                                            wenn der Saldo das Limit unterschreitet.
                                            aktueller_saldo ist der tatsächliche Saldo vor Änderung.
        False: Im Falle eines Datenbank- oder Konfigurationsfehlers.
    """

    max_negativ_saldo = 0

    query = "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s"
    row = db_utils.fetch_one(query, (target_user_id,), dictionary=True)
    try:
        aktueller_saldo = float(row["saldo"]) if row and row.get("saldo") is not None else 0
    except (TypeError, ValueError) as e:
        logger.error("Fehler beim Parsen des Saldo für User %s: %s", target_user_id, e)
        return False

    neuer_saldo = aktueller_saldo + saldo_aenderung
    if neuer_saldo < max_negativ_saldo:
        return (False, aktueller_saldo, max_negativ_saldo)
    return True


def aktuellen_saldo_pruefen_und_benachrichtigen(target_user_id: int):
    """
    Prüft den aktuellen Saldo eines Benutzers nach einer Transaktion und versendet ggf.
    E-Mail-Benachrichtigungen an den Benutzer oder die Verantwortlichen,
    basierend auf den Benutzereinstellungen und Systemeinstellungen.

    Args:
        target_user_id (int): Die ID des Benutzers, dessen Saldo geprüft werden soll.
    """

    user_details = get_user_details_for_notification(target_user_id)
    if not user_details:
        logger.warning(
            "Benutzerdetails für ID %s nicht gefunden in aktuellen_saldo_pruefen_und_benachrichtigen.", target_user_id
        )
        return

    if not user_details.get("email"):
        logger.info(
            "Benutzer %s hat keine E-Mail-Adresse hinterlegt. Keine Saldo-Benachrichtigungen möglich.", target_user_id
        )
        return

    query = "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s"
    row = db_utils.fetch_one(query, (target_user_id,), dictionary=True)
    aktueller_saldo = row["saldo"] if row and row.get("saldo") is not None else 0

    logo_pfad_str = str(Path("static/logo/logo-80x109.png"))

    if aktueller_saldo == 0:
        _send_saldo_null_benachrichtigung(user_details, aktueller_saldo, logo_pfad_str)

    _send_user_threshold_benachrichtigung(user_details, aktueller_saldo, logo_pfad_str)

    _send_responsible_threshold_benachrichtigung(user_details, aktueller_saldo, logo_pfad_str)


def get_user_by_api_key(api_key_value: str) -> tuple[int, str] | None:
    """
    Ruft den Benutzer anhand des API-Schlüssels aus der Datenbank ab.

    Args:
        api_key_value (str): Der API-Schlüssel des Benutzers.

    Returns:
        Optional[tuple[int, str]]: Ein Tupel mit (user_id, username) oder None.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    try:
        with cnx.cursor() as cursor:  # Kein dictionary=True nötig, da Indizes verwendet werden
            cursor.execute(
                "SELECT u.id, u.username FROM api_users u JOIN api_keys ak ON u.id = ak.user_id WHERE ak.api_key = %s",
                (api_key_value,),
            )
            user = cursor.fetchone()
            return (user[0], user[1]) if user else None
    except Error as err:
        logger.error("Fehler beim Abrufen des Benutzers anhand des API-Schlüssels: %s.", err)
        return None
    finally:
        if cnx:
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
        api_key_header = request.headers.get("X-API-Key")
        if not api_key_header:
            logger.warning("API-Zugriff ohne API-Schlüssel.")
            return jsonify({"message": "API-Schlüssel fehlt!"}), 401

        user_data = get_user_by_api_key(api_key_header)  # user_id, username
        if not user_data:
            logger.warning("API-Zugriff mit ungültigem API-Schlüssel: %s", api_key_header)
            return jsonify({"message": "Ungültiger API-Schlüssel!"}), 401

        # user_data[0] ist user_id, user_data[1] ist username
        return f(user_data[0], user_data[1], *args, **kwargs)

    return decorated


def finde_benutzer_zu_nfc_token(token_base64: str) -> dict | None:
    """
    Findet einen Benutzer in der Datenbank anhand der Base64-kodierten Daten eines NFC-Tokens.
    Beinhaltet jetzt auch die E-Mail-Adresse des Benutzers.

    Args:
        token_base64 (str): Die Base64-kodierte NFC-Daten des Tokens.

    Returns:
        Optional[dict]: Ein Dictionary mit den Benutzerdaten (id, nachname, vorname, email, is_locked, token_id)
                        oder None, falls kein Benutzer gefunden wird.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            try:
                token_bytes = base64.b64decode(token_base64)
            except binascii.Error:
                logger.error("Ungültiger Base64-String in finde_benutzer_zu_nfc_token: %s", token_base64)
                return None

            query = """
                SELECT u.id AS id, u.nachname AS nachname, u.vorname AS vorname, u.email AS email, u.is_locked AS is_locked, t.token_id as token_id
                FROM nfc_token AS t
                INNER JOIN users AS u ON t.user_id = u.id
                WHERE t.token_daten = %s
            """
            cursor.execute(query, (token_bytes,))
            user = cursor.fetchone()
            if user:
                logger.info(
                    "Benutzer via NFC gefunden: ID %s - %s %s (TokenID: %s, Email: %s)",
                    user["id"],
                    user["vorname"],
                    user["nachname"],
                    user["token_id"],
                    user.get("email"),
                )
            return user
    except Error as err:
        logger.error("DB-Fehler in finde_benutzer_zu_nfc_token: %s", err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


def _send_new_transaction_email(user_details: dict[str, Any], transaction_details: dict[str, Any]):
    """
    Hilfsfunktion zum Senden der "Neue Transaktion" E-Mail.
    Nimmt Benutzer- und Transaktionsdetails als Dictionaries entgegen.

    Args:
        user_details (Dict[str, Any]): Enthält 'email', 'vorname', 'id' des Benutzers.
        transaction_details (Dict[str, Any]): Enthält 'beschreibung', 'saldo_aenderung', 'neuer_saldo'.
    """

    email_params = {
        "empfaenger_email": user_details["email"],
        "betreff": "Neue Transaktion auf deinem Konto",
        "template_name_html": "email_neue_transaktion.html",
        "template_name_text": "email_neue_transaktion.txt",
        "template_context": {
            "vorname": user_details["vorname"],
            "beschreibung_transaktion": transaction_details["beschreibung"],
            "saldo_aenderung": transaction_details["saldo_aenderung"],
            "neuer_saldo": transaction_details["neuer_saldo"],
            "datum": transaction_details["datum"],
            "uhrzeit": transaction_details["uhrzeit"],
        },
        "logo_dateipfad": str(Path("static/logo/logo-80x109.png")),
    }
    if prepare_and_send_email(email_params, config.smtp_config):
        logger.info("Neue Transaktion E-Mail an %s (ID: %s) gesendet.", user_details["email"], user_details["id"])
    else:
        logger.error(
            "Fehler beim Senden der Neue Transaktion E-Mail an %s (ID: %s).", user_details["email"], user_details["id"]
        )


# ------------* FLASK ROUTEN *------------
@app.route("/version", methods=["GET"])
@api_key_required
def get_version_route(api_user_id: int, api_username: str):
    """
    Gibt die aktuelle Version der Anwendung zurück (nur für authentifizierte Benutzer).

    Returns:
        flask.Response: Eine JSON-Antwort mit der aktuellen Version.
    """

    logger.debug("API-Benutzer authentifiziert: ID %s - %s", api_user_id, api_username)
    return jsonify({"version": app.config.get("version")})


@app.route("/health", methods=["GET"])
def health_unprotected_route():
    """
    Healthcheck liefert nur ein OK zurück.

    Returns:
        flask.Response: Eine JSON-Antwort mit OK.
    """

    logger.debug("Anonymer Healthcheck-Aufruf.")
    return jsonify({"message": "Healthcheck OK!"})


@app.route("/health-protected", methods=["GET"])
@api_key_required
def health_protected_route(api_user_id: int, api_username: str):
    """
    Healthcheck gegen die Datenbank (nur für authentifizierte Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Healthcheck-Status und Benutzerinformationen.
    """

    logger.debug("API-Benutzer authentifiziert: ID %s - %s", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        logger.error("Datenbankverbindung fehlgeschlagen im Healthcheck.")
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500

    try:
        with cnx.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        logger.debug(
            "Datenbankverbindung erfolgreich für Healthcheck. Authentifizierter API-Benutzer: ID %s - %s",
            api_user_id,
            api_username,
        )
        return jsonify(
            {"message": f"Healthcheck OK! Authentifizierter API-Benutzer ID {api_user_id} ({api_username})."}
        )
    except Error as err:
        logger.error("Datenbankfehler während Healthcheck: %s", err)
        return jsonify({"error": "Datenbankfehler während Healthcheck."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/users", methods=["GET"])
@api_key_required
def get_all_users(api_user_id: int, api_username: str):
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

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe alle Benutzer ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500

    try:
        with cnx.cursor(dictionary=True) as cursor:
            query = "SELECT code, nachname, vorname FROM users ORDER BY nachname, vorname;"
            cursor.execute(query)
            users_list = cursor.fetchall()
        logger.info("%s Benutzer erfolgreich aus der Datenbank abgerufen.", len(users_list))
        return jsonify(users_list), 200
    except Error as err:
        logger.error("Fehler beim Abrufen aller Benutzer aus der Datenbank: %s", err)
        return jsonify({"error": "Ein interner Fehler ist aufgetreten."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/nfc-transaktion", methods=["PUT"])
@api_key_required
def nfc_transaction(api_user_id_auth: int, api_username_auth: str):
    """
    Verarbeitet eine NFC-Transaktion. Ordnet die Tokendaten einem Benutzer zu,
    verbucht -1 Saldo und löst ggf. E-Mail-Benachrichtigungen aus.

    Args:
        api_user_id_auth (int): Die ID des authentifizierten API-Benutzers.
        api_username_auth (str): Der Benutzername des authentifizierten API-Benutzers.
    Body (JSON): {"token": "BASE64_TOKEN", "beschreibung": "text"}
    Returns: flask.Response
    """

    daten = request.get_json()
    logger.info(
        "NFC-Transaktion Anfrage zu Token '%s' von API-Benutzer: ID %s - %s.",
        daten["token"],
        api_user_id_auth,
        api_username_auth,
    )
    if not daten or "token" not in daten or "beschreibung" not in daten:
        return jsonify({"error": "Ungültige Anfrage. Token und Beschreibung sind erforderlich."}), 400

    benutzer_info = finde_benutzer_zu_nfc_token(daten["token"])
    if not benutzer_info:
        return jsonify({"error": f"Kein Benutzer mit dem Token {daten['token']} gefunden."}), 404

    if benutzer_info.get("is_locked") == 1:
        return jsonify(
            {
                "error": f"Hallo {benutzer_info['vorname']}, leider ist dein Benutzer gesperrt. Bitte wende dich an einen Verantwortlichen!"
            }
        ), 403

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500

    neuer_saldo = 0
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "UPDATE nfc_token SET last_used = NOW() WHERE token_id = %s", (int(benutzer_info["token_id"]),)
            )

            trans_saldo_aenderung_str = get_system_setting("TRANSACTION_SALDO_CHANGE")
            if trans_saldo_aenderung_str is None:
                logger.info(
                    "TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User %s.",
                    benutzer_info["id"],
                )
                return jsonify(
                    {
                        "error": f"TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User {benutzer_info['id']} möglich."
                    }
                ), 400

            try:
                trans_saldo_aenderung = int(trans_saldo_aenderung_str)
            except ValueError:
                logger.error(
                    "Ungültiger Wert für TRANSACTION_SALDO_CHANGE ('%s') in system_einstellungen.",
                    trans_saldo_aenderung_str,
                )
                return jsonify(
                    {
                        "error": f"Ungültiger Wert für TRANSACTION_SALDO_CHANGE ('{trans_saldo_aenderung_str}') in system_einstellungen."
                    }
                ), 400

            saldo_pruefung = _aktuellen_saldo_pruefen(benutzer_info["id"], trans_saldo_aenderung)
            if isinstance(saldo_pruefung, tuple):
                logger.warning(
                    "Transaktion für User %s blockiert, da das Guthaben von %s nicht ausreichend ist",
                    benutzer_info["id"],
                    saldo_pruefung[1],
                )
                return jsonify(
                    {
                        "message": f"Hey {benutzer_info['vorname']}, dein Guthaben beträgt {saldo_pruefung[1]} € und "
                        "unterschreitet das Limit. Bitte lade dein Konto wieder auf.",
                        "action": "block",
                    }
                ), 200
            if saldo_pruefung is False:
                logger.error("Fehler bei der Saldoprüfung für Benutzer %s. Aktion blockiert.", benutzer_info["id"])
                return jsonify(
                    {
                        "message": f"Hey {benutzer_info['vorname']}, es gab ein technisches Problem bei der Überprüfung deines Saldos. "
                        "Bitte versuche es später erneut oder kontaktiere einen Verantwortlichen.",
                        "action": "error",
                    }
                ), 200

            cursor.execute(
                "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)",
                (benutzer_info["id"], daten["beschreibung"], trans_saldo_aenderung),
            )
            cnx.commit()
            cursor.execute(
                "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (benutzer_info["id"],)
            )

            saldo_row = cursor.fetchone()
            neuer_saldo = saldo_row["saldo"] if saldo_row and saldo_row["saldo"] is not None else 0
            logger.info(
                "Transaktion für %s (ID: %s), '%s', Saldo: %s = %s erfolgreich erstellt.",
                benutzer_info["vorname"],
                benutzer_info["id"],
                daten["beschreibung"],
                trans_saldo_aenderung,
                neuer_saldo,
            )

        # Außerhalb des 'with cursor' Blocks, da DB Operationen darin abgeschlossen sein sollten.
        if benutzer_info.get("email") and get_user_notification_preference(benutzer_info["id"], "NEUE_TRANSAKTION"):
            jetzt = datetime.datetime.now()
            user_details_for_email = {
                "email": benutzer_info["email"],
                "vorname": benutzer_info.get("vorname", ""),
                "id": benutzer_info["id"],
            }
            transaction_details_for_email = {
                "beschreibung": daten["beschreibung"],
                "saldo_aenderung": trans_saldo_aenderung,
                "neuer_saldo": neuer_saldo,
                "datum": jetzt.strftime("%d.%m.%Y"),
                "uhrzeit": jetzt.strftime("%H:%M"),
            }
            _send_new_transaction_email(user_details_for_email, transaction_details_for_email)
        aktuellen_saldo_pruefen_und_benachrichtigen(benutzer_info["id"])

        return jsonify(
            {
                "message": f"Prost {benutzer_info['vorname']}! Dein aktueller Kontostand beträgt: {neuer_saldo} €.",
                "saldo": neuer_saldo,
            }
        ), 200

    except Error as err:
        if cnx.is_connected():  # Nur rollback wenn Verbindung noch besteht
            cnx.rollback()
        logger.error("Fehler bei NFC-Transaktion für User %s: %s", benutzer_info.get("id", "Unbekannt"), err)
        return jsonify({"error": "Fehler bei der Transaktionsverarbeitung."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/person/<string:code>/transaktion", methods=["PUT"])
@api_key_required
def person_transaktion_erstellen(api_user_id_auth: int, api_username_auth: str, code: str):
    """
    Erstellt eine Transaktion für einen Benutzer anhand seines Codes.
    Löst ggf. E-Mail-Benachrichtigungen aus.

    Args:
        api_user_id_auth (int): Die ID des authentifizierten API-Benutzers.
        api_username_auth (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der Person.

    Body (JSON): {"beschreibung": "text", "saldo_aenderung": int (optional), "saldo": int (optional), "vorname": str (optional)}

    Returns: flask.Response
    """

    logger.info("Transaktion für Code %s von API-Benutzer: ID %s - %s.", code, api_user_id_auth, api_username_auth)
    daten = request.get_json()
    if not daten or "beschreibung" not in daten:
        return jsonify({"error": "Ungültige Anfrage. Beschreibung ist erforderlich."}), 400

    user_info = get_user_details_by_code(code)
    if not user_info:
        return jsonify({"error": f"Person mit Code {code} nicht gefunden."}), 404
    if user_info.get("is_locked") == 1:
        return jsonify(
            {
                "message": f"Hallo {user_info['vorname']}, leider ist dein Benutzer gesperrt. "
                "Bitte melde dich bei einem Verantwortlichen.",
                "action": "locked",
            }
        ), 200

    trans_saldo_aenderung_str = get_system_setting("TRANSACTION_SALDO_CHANGE")
    if trans_saldo_aenderung_str is None:
        logger.info("TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User %s.", user_info["id"])
        return jsonify(
            {
                "error": f"TRANSACTION_SALDO_CHANGE nicht konfiguriert, keine Saldo-Änderung für User {user_info['id']} möglich."
            }
        ), 400

    try:
        trans_saldo_aenderung = int(trans_saldo_aenderung_str)
    except ValueError:
        logger.error(
            "Ungültiger Wert für TRANSACTION_SALDO_CHANGE ('%s') in system_einstellungen.", trans_saldo_aenderung_str
        )
        return jsonify(
            {
                "error": f"Ungültiger Wert für TRANSACTION_SALDO_CHANGE ('{trans_saldo_aenderung_str}') in system_einstellungen."
            }
        ), 400

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500

    saldo_pruefung = _aktuellen_saldo_pruefen(user_info["id"], trans_saldo_aenderung)
    if isinstance(saldo_pruefung, tuple):
        logger.warning(
            "Transaktion für User %s blockiert, da das Guthaben von %s nicht ausreichend ist (Limit %s)",
            user_info["id"],
            saldo_pruefung[1],
            saldo_pruefung[2],
        )
        return jsonify(
            {
                "message": f"Hey {user_info['vorname']}, dein Guthaben beträgt {saldo_pruefung[2]} € und "
                "unterschreitet das Limit. Bitte lade dein Konto wieder auf.",
                "action": "block",
            }
        ), 200
    if saldo_pruefung is False:
        logger.error("Fehler bei der Saldoprüfung für Benutzer %s. Aktion blockiert.", user_info["id"])
        return jsonify(
            {
                "message": f"Hey {user_info['vorname']}, es gab ein technisches Problem bei der Überprüfung deines Saldos. "
                "Bitte versuche es später erneut oder kontaktiere einen Verantwortlichen.",
                "action": "error",
            }
        ), 200

    neuer_saldo = 0
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "INSERT INTO transactions (user_id, beschreibung, saldo_aenderung) VALUES (%s, %s, %s)",
                (user_info["id"], daten["beschreibung"], trans_saldo_aenderung),
            )
            cnx.commit()
            logger.info(
                "Transaktion für %s (ID: %s, Code: %s), '%s', Saldo: %s erfolgreich erstellt.",
                user_info["vorname"],
                user_info["id"],
                code,
                daten["beschreibung"],
                trans_saldo_aenderung,
            )

            cursor.execute(
                "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s", (user_info["id"],)
            )
            saldo_row = cursor.fetchone()
            neuer_saldo = saldo_row["saldo"] if saldo_row and saldo_row["saldo"] is not None else 0

        # Außerhalb des 'with cursor' Blocks
        if user_info.get("email") and get_user_notification_preference(user_info["id"], "NEUE_TRANSAKTION"):
            jetzt = datetime.datetime.now()
            user_details_for_email = {
                "email": user_info["email"],
                "vorname": user_info.get("vorname", ""),
                "id": user_info["id"],
            }
            transaction_details_for_email = {
                "beschreibung": daten["beschreibung"],
                "saldo_aenderung": trans_saldo_aenderung,
                "neuer_saldo": neuer_saldo,
                "datum": jetzt.strftime("%d.%m.%Y"),
                "uhrzeit": jetzt.strftime("%H:%M"),
            }
            _send_new_transaction_email(user_details_for_email, transaction_details_for_email)
        aktuellen_saldo_pruefen_und_benachrichtigen(user_info["id"])

        return jsonify(
            {
                "message": f"Prost {user_info['vorname']}! Dein aktueller Kontostand beträgt: {neuer_saldo} €.",
                "saldo": neuer_saldo,
                "vorname": user_info["vorname"],
            }
        ), 200

    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        logger.error("Fehler bei Transaktion für Code %s: %s", code, err)
        return jsonify({"error": "Fehler beim Erstellen der Transaktion."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


def get_user_details_by_code(code_val: str) -> dict | None:
    """
    Ruft ID, Vorname, E-Mail und Accountstatus (gesperrt/nicht gesperrt) eines Benutzers anhand seines Codes ab.

    Args:
        code_val (str): Der Benutzercode.

    Returns:
        Optional[dict]: Ein Dictionary mit {'id': int, 'vorname': str, 'email': str, 'is_locked': int} oder None.
    """

    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        logger.error("DB-Verbindungsfehler in get_user_details_by_code für Code %s", code_val)
        return None
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute("SELECT id, vorname, email, is_locked FROM users WHERE code = %s", (code_val,))
            return cursor.fetchone()
    except Error as err:
        logger.error("DB-Fehler in get_user_details_by_code für Code %s: %s", code_val, err)
        return None
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/saldo-alle", methods=["GET"])
@api_key_required
def get_alle_summe(api_user_id: int, api_username: str):
    """
    Gibt das Saldo aller Personen in der Datenbank zurück (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste von Benutzern und ihrem Saldo.
    """

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe Saldo aller Personen ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT u.id, u.nachname AS nachname, u.vorname AS vorname, SUM(t.saldo_aenderung) AS saldo "
                "FROM users AS u LEFT JOIN transactions AS t ON u.id = t.user_id GROUP BY u.id, u.nachname, u.vorname ORDER BY saldo DESC, u.nachname, u.vorname;"
            )
            personen_saldo = cursor.fetchall()
        logger.info("Saldo aller Personen wurde ermittelt (%s Einträge).", len(personen_saldo))
        return jsonify(personen_saldo)
    except Error as err:
        logger.error("Fehler beim Lesen der Saldo-Daten: %s", err)
        return jsonify({"error": "Fehler beim Lesen der Daten."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/transaktionen", methods=["GET"])
@api_key_required
def get_alle_transaktionen(api_user_id: int, api_username: str):
    """
    Gibt alle Transaktionen in der Datenbank zurück, angereichert mit Benutzerinformationen
    (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Liste aller Transaktionen mit Benutzerinformationen.
    """

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Rufe alle Transaktionen ab.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500
    try:
        with cnx.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT t.id, u.nachname AS nachname, u.vorname AS vorname, t.beschreibung, t.timestamp FROM transactions AS t INNER JOIN users AS u ON t.user_id = u.id ORDER BY t.timestamp DESC;"
            )
            transaktionen_liste = cursor.fetchall()
        logger.info("Alle Transaktionen wurden ermittelt (%s Einträge).", len(transaktionen_liste))
        return jsonify(transaktionen_liste)
    except Error as err:
        logger.error("Fehler beim Lesen der Transaktionsdaten: %s", err)
        return jsonify({"error": "Fehler beim Lesen der Daten."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/transaktionen", methods=["DELETE"])
@api_key_required
def reset_transaktionen(api_user_id: int, api_username: str):
    """
    Löscht die Transaktionen für alle hinterlegten Personen (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Lösche alle Transaktionen.", api_user_id, api_username)
    cnx = db_utils.DatabaseConnectionPool.get_connection(config.db_config)
    if not cnx:
        return jsonify({"error": "Datenbankverbindung fehlgeschlagen."}), 500
    try:
        with cnx.cursor() as cursor:
            sql = "TRUNCATE TABLE transactions;"
            cursor.execute(sql)
            cnx.commit()
        logger.info("Alle Transaktionen wurden gelöscht.")
        return jsonify({"message": "Alle Transaktionen wurden gelöscht."}), 200
    except Error as err:
        if cnx.is_connected():
            cnx.rollback()
        logger.error("Fehler beim Leeren der Tabelle transactions: %s", err)
        return jsonify({"error": "Fehler beim Leeren der Tabelle transactions."}), 500
    finally:
        if cnx:
            db_utils.DatabaseConnectionPool.close_connection(cnx)


@app.route("/person", methods=["POST"])
@api_key_required
def create_person(api_user_id: int, api_username: str):
    """
    Fügt eine neue Person zur Datenbank hinzu (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
    Body (JSON): {"code": "...", "nachname": "...", "vorname": "...", "password": "..."}
    Returns: flask.Response
    """

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Erstelle neue Person.", api_user_id, api_username)
    daten = request.get_json()
    if not daten or "code" not in daten or "nachname" not in daten or "vorname" not in daten:
        return jsonify(
            {"error": "Ungültige oder unvollständige Daten. Code, Nachname, Vorname sind erforderlich."}
        ), 400

    code_val = daten["code"]
    nachname_val = daten["nachname"]
    vorname_val = daten["vorname"]
    password_val = daten.get("password", "")  # Passwort ist optional, default leer

    if not isinstance(code_val, str) or len(code_val) != 10 or not code_val.isdigit():
        return jsonify({"error": "Der Code muss ein 10-stelliger Zahlencode sein."}), 400
    if (
        not isinstance(nachname_val, str)
        or not nachname_val.strip()
        or not isinstance(vorname_val, str)
        or not vorname_val.strip()
    ):
        return jsonify({"error": "Vorname und Nachname dürfen nicht leer sein."}), 400

    sql = "INSERT IGNORE INTO users (code, nachname, vorname, password) VALUES (%s, %s, %s, %s)"
    werte = (code_val, nachname_val, vorname_val, password_val)
    success, _ = db_utils.execute_commit(sql, werte)
    if success:
        logger.info("Person mit Code %s erfolgreich hinzugefügt.", code_val)
        return jsonify({"message": f"Person mit Code {code_val} erfolgreich hinzugefügt."}), 200
    logger.error("Fehler beim Hinzufügen der Person mit Code %s.", code_val)
    return jsonify({"error": "Fehler beim Hinzufügen der Person."}), 500


@app.route("/person/<string:code>", methods=["DELETE"])
@api_key_required
def delete_person(api_user_id: int, api_username: str, code: str):
    """
    Person aus der Datenbank löschen (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der zu löschenden Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    logger.info("API-Benutzer authentifiziert: ID %s - %s. Lösche Person mit Code %s.", api_user_id, api_username, code)
    sql = "DELETE FROM users WHERE code = %s"
    success, _ = db_utils.execute_commit(sql, (code,))
    if success:
        logger.info("Person mit Code %s erfolgreich gelöscht.", code)
        return jsonify({"message": f"Person mit Code {code} erfolgreich gelöscht."}), 200
    logger.warning("Keine Person mit dem Code %s zum Löschen gefunden oder Fehler.", code)
    return jsonify({"error": f"Keine Person mit dem Code {code} gefunden oder Fehler."}), 404


@app.route("/person/existent/<string:code>", methods=["GET"])
@api_key_required
def person_exists_by_code(api_user_id: int, api_username: str, code: str):
    """
    Prüft anhand ihres 10-stelligen Codes, ob eine Person existiert (nur für authentifizierte API-Benutzer).

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit dem Namen der Person oder einem Fehler.
    """

    logger.info(
        "API-Benutzer authentifiziert: ID %s - %s. Prüfe Existenz von Person mit Code %s.",
        api_user_id,
        api_username,
        code,
    )
    query = "SELECT nachname, vorname FROM users WHERE code = %s"
    person = db_utils.fetch_one(query, (code,), dictionary=True)
    if person:
        logger.info("Person mit Code %s gefunden: %s, %s", code, person["nachname"], person["vorname"])
        return jsonify(person)
    logger.info("Person mit Code %s nicht gefunden.", code)
    return jsonify({"error": "Person nicht gefunden."}), 404


@app.route("/person/<string:code>", methods=["GET"])
@api_key_required
def get_person_by_code(api_user_id: int, api_username: str, code: str):
    """
    Gibt Daten einer Person anhand ihres 10-stelligen Codes zurück (nur für authentifizierte API-Benutzer).
    Beinhaltet Name, Vorname und aktuellen Saldo.

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der gesuchten Person.

    Returns:
        flask.Response: Eine JSON-Antwort mit den Personendaten (Name, Vorname, Saldo) oder einem Fehler.
    """

    logger.info("Abfrage für Person mit Code %s von API-Benutzer: ID %s - %s.", code, api_user_id, api_username)
    person_info = db_utils.fetch_one(
        "SELECT id, nachname, vorname FROM users WHERE code = %s", (code,), dictionary=True
    )
    if not person_info:
        logger.info("Person mit Code %s nicht gefunden.", code)
        return jsonify({"error": "Person nicht gefunden."}), 404

    saldo_data = db_utils.fetch_one(
        "SELECT SUM(saldo_aenderung) AS saldo FROM transactions WHERE user_id = %s",
        (person_info["id"],),
        dictionary=True,
    )
    aktueller_saldo = saldo_data["saldo"] if saldo_data and saldo_data["saldo"] is not None else 0

    response_data = {"nachname": person_info["nachname"], "vorname": person_info["vorname"], "saldo": aktueller_saldo}
    logger.info(
        "Person mit Code %s gefunden: %s, %s - Saldo %s",
        code,
        response_data["nachname"],
        response_data["vorname"],
        response_data["saldo"],
    )
    return jsonify(response_data)


@app.route("/person/transaktionen/<string:code>", methods=["DELETE"])
@api_key_required
def person_transaktionen_loeschen(api_user_id: int, api_username: str, code: str):
    """
    Ermittelt eine Person anhand des übermittelten Codes und löscht die verknüpften Transaktionen.

    Args:
        api_user_id (int): Die ID des authentifizierten API-Benutzers.
        api_username (str): Der Benutzername des authentifizierten API-Benutzers.
        code (str): Der 10-stellige Code der Person, deren Transaktionen gelöscht werden sollen.

    Returns:
        flask.Response: Eine JSON-Antwort mit einer Erfolgsmeldung oder einem Fehler.
    """

    logger.info(
        "API-Benutzer authentifiziert: ID %s - %s. Lösche Transaktionen für Code %s.", api_user_id, api_username, code
    )
    user_data_row = db_utils.fetch_one("SELECT id FROM users WHERE code = %s", (code,), dictionary=False)
    if not user_data_row:
        logger.warning("Person mit Code %s nicht gefunden, keine Transaktionen zum Löschen.", code)
        return jsonify({"error": "Person mit diesem Code nicht gefunden."}), 404

    target_user_id_for_delete = user_data_row[0]
    success, _ = db_utils.execute_commit("DELETE FROM transactions WHERE user_id = %s", (target_user_id_for_delete,))
    if success:
        logger.info(
            "Transaktionen für Benutzer mit Code %s (ID: %s) erfolgreich gelöscht.", code, target_user_id_for_delete
        )
        return jsonify({"message": "Transaktionen erfolgreich gelöscht."}), 200
    logger.error("Fehler beim Löschen der Transaktionen für Code %s (User ID: %s)", code, target_user_id_for_delete)
    return jsonify({"error": "Fehler beim Löschen der Transaktion."}), 500


if __name__ == "__main__":
    app.run(host=config.api_config["host"], port=config.api_config["port"], debug=config.api_config["flask_debug_mode"])
