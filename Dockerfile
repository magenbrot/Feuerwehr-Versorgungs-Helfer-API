# --- BASE STAGE ---
FROM python:3.11-slim AS base

WORKDIR /app

# System-Abhängigkeiten (Pillow benötigt libjpeg/zlib)
RUN apt-get update && apt-get install -y \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren + gunicorn hinzufügen
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# --- STAGE API ---
FROM base AS api
EXPOSE 5000
# Gunicorn startet die api.py (Variable 'app')
# --bind: Port im Container
# --workers: Faustregel (2 x CPU-Kerne) + 1
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "api:app"]

# --- STAGE GUI ---
FROM base AS gui
EXPOSE 5001
# Gunicorn startet die gui.py (Variable 'app')
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "gui:app"]
