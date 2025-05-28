"""Definiert gemeinsam genutzte Konfigurationen."""

import os
from dotenv import load_dotenv

load_dotenv()

db_config = {
    'host': os.getenv("MYSQL_HOST"),
    'port': os.getenv("MYSQL_PORT"),
    'user': os.getenv("MYSQL_USER"),
    'password': os.getenv("MYSQL_PASSWORD"),
    'database': os.getenv("MYSQL_DB"),
}

smtp_config = {
    'host': os.getenv("SMTP_HOST"),
    'port': os.getenv("SMTP_PORT"),
    'user': os.getenv("SMTP_USER"),
    'password': os.getenv("SMTP_PASSWORD"),
    'sender': os.getenv("SMTP_SENDER"),
}

saldo_grenzwert = int(os.getenv("SALDO_GRENZWERT"))
