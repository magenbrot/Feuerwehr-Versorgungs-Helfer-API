import binascii
import logging
import secrets

logger = logging.getLogger(__name__)


def generate_api_key_string(length=32):
    """
    Generiert einen sicheren, zufälligen API-Key-String.
    """
    return secrets.token_hex(length)


def hex_to_binary(hex_string):
    """
    Konvertiert einen Hexadezimalstring in Binärdaten.

    Diese Funktion nimmt einen Hexadezimalstring entgegen und wandelt ihn in die entsprechende
    Binärdarstellung um. Sie wird typischerweise verwendet, um NFC-Token Daten zu verarbeiten,
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
        logger.error("Fehler bei der Hexadezimal-Konvertierung: Ungültiger Hexadezimalstring '%s'", hex_string)
        return None
    except TypeError:
        logger.error(
            "Fehler bei der Hexadezimal-Konvertierung: Ungültiger Typ für Hexadezimalstring: %s", type(hex_string)
        )
        return None
