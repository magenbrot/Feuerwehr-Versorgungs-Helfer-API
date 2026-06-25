# Beitragen zur Feuerwehr-Versorgungs-Helfer-API (Backend) 🚒📊⚙️

Vielen Dank, dass du dich für eine Mitarbeit am Backend des Feuerwehr-Versorgungs-Helfers interessierst! Dieses Dokument beschreibt die Richtlinien und Best Practices für Beiträge zu diesem Repository.

---

## 📋 Inhaltsverzeichnis

1. [Verhaltenskodex](#-verhaltenskodex)
2. [Wie kann ich beitragen?](#-wie-kann-ich-beitragen)
   - [Fehler melden (Issues)](#fehler-melden-issues)
   - [Features vorschlagen](#features-vorschlagen)
   - [Code-Beiträge leisten (Pull Requests)](#code-beiträge-leisten-pull-requests)
3. [Lokale Entwicklung & Setup](#-lokale-entwicklung--setup)
   - [Voraussetzungen](#voraussetzungen)
   - [Lokales Setup (Manuell)](#lokales-setup-manuell)
   - [Lokales Setup (Docker - Empfohlen)](#lokales-setup-docker---empfohlen)
4. [Abhängigkeiten verwalten (Requirements)](#-abhängigkeiten-verwalten-requirements)
5. [Tests & Code-Qualität](#-tests--code-qualität)
   - [Code-Style & Linting mit Ruff](#code-style--linting-mit-ruff)
   - [Automatisierte Tests mit pytest](#automatisierte-tests-mit-pytest)
6. [Pull Request Workflow](#-pull-request-workflow)
   - [Branch-Namenskonventionen](#branch-namenskonventionen)
   - [Commit-Nachrichten](#commit-nachrichten)
   - [PR einreichen](#pr-einreichen)

---

## 🤝 Verhaltenskodex

Bitte achte auf einen freundlichen, respektvollen und konstruktiven Umgangston. Wir möchten eine einladende Gemeinschaft für alle Beteiligten schaffen.

---

## 💡 Wie kann ich beitragen?

### Fehler melden (Issues)

Wenn du einen Fehler im Backend findest (z. B. ein fehlerhafter API-Endpunkt oder ein Bug in der Admin-GUI), öffne bitte ein Issue im Repository. Stelle sicher, dass du folgende Informationen angibst:

* Eine präzise Beschreibung des Fehlers und wie man ihn reproduziert.
* Genutzte Softwareversionen (Python-Version, Docker-Version).
* Log-Ausgaben der betroffenen Dienste (API/GUI/Datenbank).
* Das erwartete vs. tatsächliche Verhalten.

### Features vorschlagen

Vorschläge für neue API-Endpunkte, zusätzliche GUI-Funktionen oder Performance-Verbesserungen sind sehr willkommen! Beschreibe deine Idee bitte in einem Issue und erkläre den Nutzen für das System.

### Code-Beiträge leisten (Pull Requests)

1. **Forke** das Repository und erstelle deinen eigenen Entwicklungs-Branch.
2. Nimm deine Änderungen vor und stelle sicher, dass alle Tests weiterhin grün sind.
3. Teste deine Änderungen lokal.
4. Formatiere und linde deinen Code mit `ruff`.
5. Sende einen Pull Request (PR) an den `main`-Branch des Original-Repositories.

---

## 🛠️ Lokale Entwicklung & Setup

### Voraussetzungen

* Python 3.11+ oder Docker / Docker Compose.
* Eine MySQL-Datenbank (lokal installiert oder über Docker).

### Lokales Setup (Manuell)

1. Clone deinen Fork und wechsle in das Verzeichnis:
   ```bash
   git clone https://github.com/DEIN-BENUTZERNAME/Feuerwehr-Versorgungs-Helfer-API.git
   cd Feuerwehr-Versorgungs-Helfer-API
   ```
2. Erstelle eine virtuelle Umgebung und installiere die Abhängigkeiten:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
3. Kopiere die Umgebungsvorlage `.env.dist` nach `.env` und passe sie an.
4. Richte deine lokale MySQL-Datenbank ein und importiere das Schema:
   ```bash
   mysql -u <user> -p <database> < schema.sql
   ```
5. Starte die Anwendungen:
   ```bash
   # GUI starten (läuft standardmäßig auf Port 5001)
   python3 gui.py
   
   # API starten (läuft standardmäßig auf Port 5000)
   python3 api.py
   ```

### Lokales Setup (Docker - Empfohlen)

Wenn du Code-Änderungen direkt in einer isolierten Docker-Umgebung testen möchtest, kannst du das Build-Compose-File nutzen:

1. Kopiere die Vorlagen:
   ```bash
   cp .env.dist .env
   cp docker-compose-build.yml.dist docker-compose-build.yml
   ```
2. Baue und starte die Container:
   ```bash
   docker compose -f docker-compose-build.yml up -d --build
   ```

---

## 📦 Abhängigkeiten verwalten (Requirements)

Wenn du neue Python-Module hinzufügst, verwende bitte **pigar**, um die `requirements.txt` sauber zu generieren und die uWSGI-Annotationen beizubehalten:

```bash
# Stelle sicher, dass die virtuelle Umgebung aktiv ist
pigar generate --question-answer yes --enable-feature requirement-annotations
```

---

## 🧪 Tests & Code-Qualität

### Code-Style & Linting mit Ruff

Wir verwenden **Ruff** als schnellen Linter und Code-Formatter. Vor jedem Commit solltest du Ruff ausführen, um den Code-Style zu prüfen und zu korrigieren:

```bash
# Code formatieren
ruff format .

# Linter ausführen und ggf. Auto-Fixes anwenden
ruff check . --fix
```

Im Github-Action-Workflow wird geprüft, ob der Code korrekt formatiert ist (`ruff format --check .`) und ob alle Linter-Regeln eingehalten werden.

### Automatisierte Tests mit pytest

Wir nutzen **pytest** für Unit- und Integrationstests. Stelle sicher, dass vor dem Einreichen eines PRs alle Tests fehlerfrei durchlaufen:

```bash
pytest
```

Wenn du neue Endpunkte oder Kernlogik hinzufügst, schreibe bitte entsprechende Tests im Ordner `tests/`.

---

## 🚀 Pull Request Workflow

### Branch-Namenskonventionen

Verwende prägnante Namen für deine Entwicklungs-Branches:

* `feature/mein-neues-feature` für neue Funktionen.
* `fix/behebung-eines-bugs` für Bugfixes.
* `docs/doku-anpassung` für Dokumentations-Updates.
* `test/test-hinzufuegen` für zusätzliche Testabdeckung.

### Commit-Nachrichten

Schreibe klare und verständliche Commit-Nachrichten. Verwende idealerweise das folgende Format:

```
[Typ] Kurze Zusammenfassung der Änderungen in der Gegenwartsform

- Detail 1 der Änderung
- Detail 2 der Änderung
```

Beispiele für Typen: `Feat` (Feature), `Fix` (Bugfix), `Docs` (Dokumentation), `Refactor` (Code-Refactoring), `Test` (Tests).

### PR einreichen

* Stelle sicher, dass der Ziel-Branch deines PRs `main` ist.
* Beschreibe im PR kurz, was geändert wurde und warum.
* Verlinke eventuell zugehörige Issues (z. B. `Closes #12`).
* Sobald der PR erstellt ist, laufen die automatisierten GitHub-Actions für Ruff (Linting) und pytest (Tests). Beide müssen erfolgreich durchlaufen, damit der PR gemergt werden kann.
