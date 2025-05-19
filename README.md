# Feuerwehr-Versorgungs-Helfer-API

Hier handelt es sich um den serverseitigen Teil der Applikation. Sie stellt die API für die entfernten Clients und die WebGUI bereit.

Der Code für den QR-Code- und NFC-Scanner ist [hier](https://github.com/magenbrot/Feuerwehr-Versorgungs-Helfer) zu finden.

## Update requirements.txt correctly

I am using pigar to create the requirements.txt. Since running in a local dev environment does not require a uWSGI service pigar does not add this to the list of needed packages. But pigar can read comments in the .py files where I noted that we need the uWSGI package.

To enable this feature use the following command:
```
pigar generate --question-answer yes --enable-feature requirement-annotations
```

## Installation API als nginx UWSGI Dienst mittels systemd
