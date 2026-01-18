# --- BASE STAGE ---
FROM python:3.11-slim AS base

RUN groupadd --system fvh && useradd --system --gid fvh fvh

WORKDIR /app

# System-Abhängigkeiten (Pillow benötigt libjpeg/zlib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    fonts-hack-ttf \
    fonts-dejavu-core \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Abhängigkeiten installieren + gunicorn hinzufügen
COPY --chown=fvh:fvh requirements.txt requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=fvh:fvh . .
USER fvh

# --- STAGE API ---
FROM base AS api
EXPOSE 5000
# Gunicorn startet die api.py (Variable 'app')
# --bind: Port im Container
# --workers: Faustregel (2 x CPU-Kerne) + 1
CMD ["gunicorn", "--config", "gunicorn_config.py", "api:app"]

# --- STAGE GUI ---
FROM base AS gui
EXPOSE 5001
# Gunicorn startet die gui.py (Variable 'app')
CMD ["gunicorn", "--config", "gunicorn_config.py", "--bind", "0.0.0.0:5001", "gui:app"]
