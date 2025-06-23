SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";

CREATE TABLE api_keys (
  id int NOT NULL,
  user_id int NOT NULL,
  api_key_name varchar(256) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  api_key varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE api_users (
  id int NOT NULL,
  username varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE benachrichtigungstypen (
  id int NOT NULL,
  event_schluessel varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  beschreibung varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE benutzer_benachrichtigungseinstellungen (
  benutzer_id int NOT NULL,
  typ_id int NOT NULL,
  email_aktiviert tinyint(1) NOT NULL DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE nfc_token (
  token_id int NOT NULL,
  user_id int NOT NULL,
  token_name varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  token_daten varbinary(20) NOT NULL,
  last_used datetime DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE password_reset_tokens (
  id int NOT NULL,
  user_id int NOT NULL,
  token varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  expires_at datetime NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE system_einstellungen (
  einstellung_schluessel varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  einstellung_wert varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  beschreibung text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE transactions (
  id int NOT NULL,
  user_id int NOT NULL,
  beschreibung varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  saldo_aenderung int NOT NULL DEFAULT '1',
  timestamp datetime NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE users (
  id int NOT NULL,
  code varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '10-stelliger eindeutiger Zahlencode (für den QR-Code und Login)',
  nachname varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  vorname varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  password varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  email varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  kommentar varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'wird nur den Admins angezeigt',
  acc_duties tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Buchungs und Mitwirkungspflicht akzeptiert',
  acc_privacy_policy tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Datenschutzerklärung akzeptiert',
  is_locked tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Benutzer gesperrt',
  is_admin tinyint(1) NOT NULL DEFAULT '0' COMMENT 'Benutzer ist Admin'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


ALTER TABLE api_keys
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY api_key (api_key),
  ADD KEY user_id (user_id);

ALTER TABLE api_users
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY username (username);

ALTER TABLE benachrichtigungstypen
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY event_schluessel (event_schluessel);

ALTER TABLE benutzer_benachrichtigungseinstellungen
  ADD PRIMARY KEY (benutzer_id,typ_id),
  ADD KEY typ_id (typ_id);

ALTER TABLE nfc_token
  ADD PRIMARY KEY (token_id),
  ADD UNIQUE KEY token_daten (token_daten),
  ADD KEY user_id (user_id);

ALTER TABLE password_reset_tokens
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY token_UNIQUE (token),
  ADD KEY fk_user_id_idx (user_id);

ALTER TABLE system_einstellungen
  ADD PRIMARY KEY (einstellung_schluessel);

ALTER TABLE transactions
  ADD PRIMARY KEY (id),
  ADD KEY user_id (user_id);

ALTER TABLE users
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY code (code),
  ADD UNIQUE KEY unique_email (email);

ALTER TABLE api_keys
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE api_users
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE benachrichtigungstypen
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE nfc_token
  MODIFY token_id int NOT NULL AUTO_INCREMENT;

ALTER TABLE password_reset_tokens
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE transactions
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE users
  MODIFY id int NOT NULL AUTO_INCREMENT;


ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_ibfk_1 FOREIGN KEY (user_id) REFERENCES api_users (id);

ALTER TABLE benutzer_benachrichtigungseinstellungen
  ADD CONSTRAINT benutzer_benachrichtigungseinstellungen_ibfk_1 FOREIGN KEY (benutzer_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE RESTRICT,
  ADD CONSTRAINT benutzer_benachrichtigungseinstellungen_ibfk_2 FOREIGN KEY (typ_id) REFERENCES benachrichtigungstypen (id) ON DELETE CASCADE ON UPDATE RESTRICT;

ALTER TABLE nfc_token
  ADD CONSTRAINT nfc_token_ibfk_1 FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;

ALTER TABLE password_reset_tokens
  ADD CONSTRAINT fk_password_reset_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE;

ALTER TABLE transactions
  ADD CONSTRAINT transactions_ibfk_1 FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE RESTRICT;

INSERT INTO `users` (`id`, `code`, `nachname`, `vorname`, `password`, `email`, `kommentar`, `acc_duties`, `acc_privacy_policy`, `is_locked`, `is_admin`) VALUES
(1, '9876543210', 'Admin', 'Admin', 'scrypt:32768:8:1$bcfcz3jpgHWmlN7L$6b6bddb744712e0a8291d9688288aaed470b0fed7c22c4e1be2b8fe0aa4a6ef1d05f1cf2090ed25c678a827309b9d8f33652440f40d83472c9d2629eb015aaed', '', '', 1, 1, 0, 1);
