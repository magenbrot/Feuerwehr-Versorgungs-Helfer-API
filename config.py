"""Definiert gemeinsam genutzte Konfigurationen."""

import os
from dotenv import load_dotenv

load_dotenv()

db_config = {
    'host': os.getenv("MYSQL_HOST", "127.0.0.1"),
    'port': int(os.getenv("MYSQL_PORT", "3306")),
    'user': os.getenv("MYSQL_USER"),
    'password': os.getenv("MYSQL_PASSWORD"),
    'database': os.getenv("MYSQL_DB"),
    'pool_size': int(os.getenv("MYSQL_POOL_SIZE", "10")),
}

smtp_config = {
    'host': os.getenv("SMTP_HOST"),
    'port': os.getenv("SMTP_PORT"),
    'user': os.getenv("SMTP_USER"),
    'password': os.getenv("SMTP_PASSWORD"),
    'sender': os.getenv("SMTP_SENDER"),
}

# nur relevant wenn nicht über uWSGI gestartet
api_config = {
    'host': os.getenv("API_HOST", "127.0.0.1"),
    'port': os.getenv("API_PORT", "5000"),
    'debug_mode': os.getenv('API_DEBUG', 'False').lower() in ['true', '1', 'yes'],
}

# nur relevant wenn nicht über uWSGI gestartet
gui_config = {
    'host': os.getenv("GUI_HOST", "127.0.0.1"),
    'port': os.getenv("GUI_PORT", "5001"),
    'debug_mode': os.getenv('GUI_DEBUG', 'False').lower() in ['true', '1', 'yes'],
    'static_url_prefix': os.getenv("STATIC_URL_PREFIX"),
}

app_name = os.getenv("APP_NAME")
app_slogan = os.getenv("APP_SLOGAN")
