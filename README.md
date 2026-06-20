[![Publish Docker images](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/docker-image.yml/badge.svg)](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/docker-image.yml)
[![Ruff](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/ruff.yml/badge.svg)](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/ruff.yml)
[![CodeQL Advanced](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/codeql.yml/badge.svg)](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/codeql.yml)

# Feuerwehr-Versorgungs-Helfer-API (Backend) 🚒📊

## Übersicht ℹ️

Dies ist das Backend für die digitale Strichlisten-Anwendung "Feuerwehr-Versorgungs-Helfer". Die Anwendung dient dazu, Guthaben von Benutzern zentral zu verwalten, die beispielsweise bei einem Verein oder einer Organisation eingezahlt wurden. Über eine separate Client-Anwendung können Benutzer dann digital "Striche machen", d.h. es wird ein vordefinierter Betrag (z.B. 1 Guthabenpunkt) von ihrem Konto abgebucht.

Das Backend stellt eine Weboberfläche (GUI) für Administratoren und Benutzer sowie eine API für die Client-Anwendung bereit. Die Client-Anwendungen sind in diesem [Repository](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer) zu finden.

## Funktionen des Backends ⚙️

### Admin-Weboberfläche (GUI) 🧑‍💻🛡️

Die webbasierte GUI ermöglicht Administratoren eine umfassende Verwaltung:

* **Benutzerverwaltung** 👥:
  * Anlegen, Bearbeiten und Löschen von regulären Benutzern (Frontend-Benutzer).
  * Jedem Benutzer wird ein eindeutiger Code zugewiesen (manuell oder automatisch generiert).
  * Verwaltung von Benutzerdetails wie Name, Passwort (gehasht gespeichert), E-Mail und internen Kommentaren.
  * Benutzerkonten können gesperrt oder entsperrt werden.
  * Benutzern können Admin-Rechte zugewiesen oder entzogen werden.
* **Transaktions- und Guthabenverwaltung** 💰🧾:
  * Manuelles Hinzufügen von Transaktionen für Benutzer (z.B. Einzahlung von Guthaben, Korrekturbuchungen).
  * Übersicht über alle Transaktionen im System oder gefiltert pro Benutzer.
  * Anzeige des aktuellen Saldos für jeden Benutzer.
  * Möglichkeit, alle Transaktionen eines bestimmten Benutzers oder alle Transaktionen im gesamten System zurückzusetzen/löschen.
* **NFC-Token-Verwaltung** 💳📲:
  * Jedem Benutzer können ein oder mehrere NFC-Tokens (z.B. Chipkarten, Schlüsselanhänger oder die NFC-ID eines Smartphones) zugewiesen werden.
  * Die NFC-Token-Daten werden in Hexadezimalform hinterlegt.
* **API-Benutzerverwaltung** 🔑🤖:
  * Anlegen und Löschen von API-Benutzern, die für die authentifizierte Kommunikation mit der Client-Anwendung benötigt werden.
  * Generieren und Verwalten von API-Schlüsseln für jeden API-Benutzer.

### Benutzer-Weboberfläche (GUI) 👤

Reguläre (nicht-administrative) Benutzer können nach dem Login:

* Ihre persönlichen Informationen einsehen.
* Ihre Transaktionshistorie und ihr aktuelles Guthaben überprüfen.
* Ihr Passwort ändern.
* Ihre hinterlegten NFC-Tokens einsehen.

### API-Endpunkte 🔌🚀

Die API dient als Schnittstelle für die Client-Anwendung und bietet unter anderem folgende Funktionalitäten (Authentifizierung via API-Key erforderlich):

* **NFC-Transaktion**: Nimmt Base64-kodierte NFC-Token-Daten entgegen, identifiziert den zugehörigen Benutzer und verbucht eine Standard-Abbuchung (z.B. -1 Guthabenpunkt). Aktualisiert den "last_used" Zeitstempel des Tokens. Wird ein nicht registrierter Token gescannt, antwortet die API mit dem HTTP-Status 404 und benachrichtigt die Administratoren per E-Mail (sofern SMTP konfiguriert ist).
* **Saldo-Abfragen**: Abrufen des Gesamtsaldos aller Benutzer oder des Saldos spezifischer Benutzer.
* **Transaktionslisten**: Abrufen von Transaktionslisten.
* **Benutzerdaten-Abfragen**: Überprüfen der Existenz eines Benutzers anhand seines Codes und Abrufen von Benutzerdetails.
* **Gesundheitscheck**: Ein geschützter Endpunkt zur Überprüfung der Datenbankverbindung.

## Client-Anwendung 📱🔗

Die zugehörige Client-Anwendung, mit der die Endbenutzer dann tatsächlich ihre "Striche machen" (also Guthaben abbuchen), indem sie z.B. einen QR-Code scannen oder ihr Handy bzw. einen anderen NFC-Token an ein Lesegerät halten, findest du im folgenden Repository:
[https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer)

## Technische Hinweise 💡

* Die Anwendung ist in Python mit Flask geschrieben.
* Für die Datenbankverbindung wird `mysql.connector` verwendet, wobei ein Verbindungspool genutzt wird.
* Passwörter werden mittels `werkzeug.security` gehasht.
* **Produktivbetrieb**: Die Anwendung wird in Docker-Umgebungen über **Gunicorn** als WSGI-Server betrieben.
* Die API und GUI sind als separate Docker-Images verfügbar, können aber über eine einzige `docker-compose.yml` orchestriert werden.

---

## Installation und Setup 🔧

### 1. Installation via Docker (Empfohlen) 🐳

Dies ist der einfachste Weg, um das komplette System inklusive Datenbank in Betrieb zu nehmen.

1. **Repository clonen**:

    ```bash
    git clone [https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API.git](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API.git)
    cd Feuerwehr-Versorgungs-Helfer-API
    ```

2. **Docker-Konfiguration**:
    * Kopiere die Vorlage: `cp docker-compose.yml.dist docker-compose.yml`.
    * *Hinweis*: Falls du eine **externe Datenbank** nutzt, kommentiere den Service `fvh-db` aus. Das Schema (`schema.sql`) muss dann manuell in die externe Instanz geladen werden.

3. **Umgebungsvariablen**:
    * Kopiere die Vorlage: `cp .env.dist .env`.
    * Passe die Zugangsdaten an. Achte darauf, dass `MYSQL_HOST=fvh-db` gesetzt ist, wenn du die interne Docker-DB nutzt (siehe Details im Abschnitt [Konfiguration](#konfiguration) unten).

4. **Container starten**:

    ```bash
    docker compose up -d
    ```

    Die Images für API und GUI werden automatisch von Docker Hub bezogen.

---

### 2. Manuelle Installation (lokale Entwicklung) 🐍

1. **Venv und Requirements**:

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

2. **Datenbank-Setup**:
    * Erstelle manuell eine MySQL-Datenbank.
    * Schema importieren: `mysql -u <user> -p <database> < schema.sql`

3. **Starten**:
    * GUI: `python3 gui.py`
    * API: `python3 api.py`

### 2.1 Lokalen Docker-Build verwenden 🐳🔨

Alternativ zur manuellen Python-Installation kannst du die Container auch lokal bauen und starten, ohne die Images von Docker Hub zu ziehen. Dies ist nützlich, wenn du Änderungen am Code vorgenommen hast und diese sofort im Container testen möchtest.

1.  **Konfiguration**:
    *   Stelle sicher, dass `.env` und `docker-compose-build.yml` (ggf. von `.dist` kopieren) vorhanden sind.

2.  **Container bauen und starten**:
    ```bash
    docker compose -f docker-compose-build.yml up -d --build
    ```

---

### 3. Installation als systemd-Dienst (Legacy) ⚙️

Für Umgebungen ohne Docker können die Dienste via systemd verwaltet werden:

1. Kopiere die Dateien aus `installation/systemd/` nach `/etc/systemd/system/` und passe die Pfade an.
2. Dienste aktivieren:

    ```bash
    systemctl daemon-reload
    systemctl enable --now fvh-api.service fvh-gui.service
    ```

---

## Konfiguration ⚙️

Die Anwendung wird über Umgebungsvariablen (in der `.env`-Datei oder direkt in der System-/Docker-Umgebung) konfiguriert. Eine Vorlage findest du unter `.env.dist`.

### Datenbank (MySQL)
| Variable | Beschreibung | Standardwert |
|---|---|---|
| `MYSQL_HOST` | Hostname oder IP-Adresse des MySQL-Servers. Bei Docker-Nutzung: `fvh-db` | `fvh-db` |
| `MYSQL_PORT` | Port des MySQL-Servers | `3306` |
| `MYSQL_ROOT_PASSWORD` | Root-Passwort der MySQL-Datenbank | |
| `MYSQL_USER` | Benutzername für die Datenbankverbindung | `fvh` |
| `MYSQL_PASSWORD` | Passwort des Datenbankbenutzers | |
| `MYSQL_DB` | Name der MySQL-Datenbank | `fvh` |
| `MYSQL_POOL_SIZE` | Größe des Verbindungspools zur Datenbank | `10` |

### E-Mail- & Benachrichtigungseinstellungen (SMTP)
*Diese Einstellungen sind wichtig, damit die API E-Mails an die Administratoren senden kann (z. B. wenn ein nicht registrierter NFC-Token gescannt wird).*
| Variable | Beschreibung | Standardwert |
|---|---|---|
| `SMTP_HOST` | Postausgangsserver (SMTP-Server) | |
| `SMTP_PORT` | Port des SMTP-Servers (z. B. `587` für TLS) | `587` |
| `SMTP_USER` | Benutzername für den SMTP-Server | |
| `SMTP_PASSWORD` | Passwort des SMTP-Benutzers | |
| `SMTP_SENDER` | E-Mail-Adresse des Absenders | |
| `RESPONSIBLE_EMAIL` | E-Mail-Adresse des Administrators (Empfänger von Benachrichtigungen) | |

### App-Einstellungen (GUI & API)
| Variable | Beschreibung | Standardwert |
|---|---|---|
| `APP_NAME` | Name der Anwendung (wird in der GUI angezeigt) | `FVH` |
| `APP_SLOGAN` | Optionaler Slogan, der in der GUI angezeigt wird | |
| `APP_SECRET` | Ein sicherer, zufälliger String für Flask-Session-Verschlüsselung | |
| `STATIC_URL_PREFIX` | Optionales Prefix für statische Web-Assets | |

### Debugging & Logging
| Variable | Beschreibung | Standardwert |
|---|---|---|
| `API_DEBUG` | Aktiviert den Flask Debug-Modus für die API | `False` |
| `API_LOG_LEVEL` | Log-Level der API (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) | `INFO` |
| `GUI_DEBUG` | Aktiviert den Flask Debug-Modus für die GUI | `False` |
| `GUI_LOG_LEVEL` | Log-Level der GUI (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) | `INFO` |

---

## Erste Schritte & Login 🌐

Nach dem Start ist die GUI unter **<http://localhost:5001>** erreichbar.

* **Default-User**: `9876543210`
* **Default-Passwort**: `changeme`

**WICHTIG**: Erstelle nach dem ersten Login sofort einen eigenen Administrator-Account und lösche den Default-User!

## API-Endpunkte 🔌

Die API erfordert einen `X-API-Key` im Header. Wichtige Endpunkte:

* `PUT /nfc-transaktion`: Verarbeitet Abbuchungen via NFC-Token.
* `GET /saldo-alle`: Übersicht über alle Kontostände.
* `GET /person/<code>`: Einzelabfrage eines Benutzers.

---

## Entwicklung 🛠️

### Anforderungen aktualisieren

Es wird `pigar` für die `requirements.txt` verwendet. Um uWSGI-Annotationen beizubehalten:

```bash
pigar generate --question-answer yes --enable-feature requirement-annotations
```

### Tests & Code-Qualität 🧪

Das Projekt verwendet `pytest` für Tests und `ruff` für Linting.

1.  **Entwicklungsumgebung einrichten**:
    ```bash
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    ```

2.  **Tests ausführen**:
    ```bash
    pytest
    ```

3.  **Linting prüfen**:
    ```bash
    ruff check .
    ```
