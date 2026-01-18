[![Pylint](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/pylint.yml/badge.svg)](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API/actions/workflows/pylint.yml)

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

* **NFC-Transaktion**: Nimmt Base64-kodierte NFC-Token-Daten entgegen, identifiziert den zugehörigen Benutzer und verbucht eine Standard-Abbuchung (z.B. -1 Guthabenpunkt). Aktualisiert den "last_used" Zeitstempel des Tokens.
* **Saldo-Abfragen**: Abrufen des Gesamtsaldos aller Benutzer oder des Saldos spezifischer Benutzer.
* **Transaktionslisten**: Abrufen von Transaktionslisten.
* **Benutzerdaten-Abfragen**: Überprüfen der Existenz eines Benutzers anhand seines Codes und Abrufen von Benutzerdetails.
* **Gesundheitscheck**: Ein geschützter Endpunkt zur Überprüfung der Datenbankverbindung.

## Client-Anwendung 📱🔗

Die zugehörige Client-Anwendung, mit der die Endbenutzer dann tatsächlich ihre "Striche machen" (also Guthaben abbuchen), indem sie z.B. einen QR-Code scannen oder ihr Handy bzw. einen anderen NFC-Token an ein Lesegerät halten, finden Sie im folgenden Repository:
[https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer)

## Technische Hinweise 💡

* Die Anwendung ist in Python mit Flask geschrieben.
* Für die Datenbankverbindung wird `mysql.connector` verwendet, wobei ein Verbindungspool genutzt wird.
* Passwörter werden mittels `werkzeug.security` gehasht.
* API-Keys werden sicher generiert.
* Das `pigar`-Tool wird erwähnt im Zusammenhang mit der Erstellung der `requirements.txt`, insbesondere um `uWSGI` als Abhängigkeit zu inkludieren, auch wenn es in lokalen Entwicklungsumgebungen nicht zwingend läuft.

## requirements.txt korrekt aktualisieren

Ich verwende pigar, um die requirements.txt zu erstellen. Da für den Betrieb in einer lokalen Entwicklungsumgebung kein uWSGI-Dienst erforderlich ist, fügt pigar dieses nicht zur Liste der benötigten Pakete hinzu. Pigar kann jedoch Kommentare in den .py-Dateien lesen, in denen ich vermerkt habe, dass wir das uWSGI-Paket benötigen.

Um diese Funktion zu aktivieren, verwende den folgenden Befehl:

```bash
pigar generate --question-answer yes --enable-feature requirement-annotations
```

## Installation und Update 🔧

### Checkout, venv und requirements installieren

```bash
git clone https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer-API.git
cd Feuerwehr-Versorgungs-Helfer-API
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### MySQL-Datenbank erstellen und Schema anlegen

1. Datenbank und Benutzer anlegen, passende Rechte vergeben
2. Schema anlegen mit ```mysql -h <host> -u <user> -p <database> < schema.sql```

### Konfiguration

```bash
cp .env.dist .env
vi .env
# Variablen setzen und Datei speichern
```

### Erstmalig manuell starten

In einer Shell die API starten:

```bash
# venv aktivieren, falls nocht nicht gemacht
source venv/bin/activate
python3 api.py
```

In einer anderen Shell die GUI starten:

```bash
# venv aktivieren, falls nocht nicht gemacht
source venv/bin/activate
python3 gui.py
```

### GUI im Browser öffnen

Bei lokalem Debugging ist die GUI unter [http://127.0.0.1:5000/](http://127.0.0.1:5000/) erreichbar. Die Listen-IP und der Port können in der .env Datei konfiguriert werden. Für den Produktivbetrieb sollte die Applikation über uWSGI gestartet und hinter einen Webserver wie nginx gelegt werden.

Für den ersten Login ist der Benutzer "9876543210" mit dem Passwort "changeme" angelegt. Bitte nach dem Login gleich einen eigenen Benutzer registrieren oder anlegen und den Default-User löschen.

### Installation API+GUI als nginx uWSGI Dienst mittels systemd

1. Die Applikationen sollten bereits lauffähig sein (also ein Python3 venv existieren und die benötigten Module installiert sein).
2. Die Dateien aus installation/systemd nach /etc/systemd/system/ kopieren und anpassen.
3. Systemd reloaden ```systemd daemon-reload```
4. Die beiden Services aktivieren: ```systemd enable --now fvh-api.service; systemd enable --now fvh-gui.service```
5. Logfiles prüfen:
   * ```journalctl -u fvh-api.service```
   * ```journalctl -u fvh-gui.service```

### Aktuelle Version installieren

Ich lasse den Code durch eine deploy-Action mit einem Github-Runner auf dem Server aktualisieren. Die Action startet, sobald es Änderungen am main-Branch gibt. Der Runner pullt dann den neuen Code, installiert ggf. neu benötigte Module und startet dann die systemd-Services neu.

Ohne den Runner lässt sich das natürlich auch einfach manuell erledigen (git pull + Restart der Services).
