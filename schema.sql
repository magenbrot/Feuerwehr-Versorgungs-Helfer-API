SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
SET time_zone = "+00:00";

CREATE TABLE api_keys (
  id int NOT NULL,
  user_id int NOT NULL,
  api_key varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE api_users (
  id int NOT NULL,
  username varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL
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
  code varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  nachname varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  vorname varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  password varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  email varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  kommentar varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  is_locked tinyint(1) NOT NULL DEFAULT '0',
  is_admin tinyint(1) NOT NULL DEFAULT '0'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


ALTER TABLE api_keys
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY api_key (api_key),
  ADD KEY user_id (user_id);

ALTER TABLE api_users
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY username (username);

ALTER TABLE transactions
  ADD PRIMARY KEY (id),
  ADD KEY user_id (user_id);

ALTER TABLE users
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY code (code);


ALTER TABLE api_keys
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE api_users
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE transactions
  MODIFY id int NOT NULL AUTO_INCREMENT;

ALTER TABLE users
  MODIFY id int NOT NULL AUTO_INCREMENT;


ALTER TABLE api_keys
  ADD CONSTRAINT api_keys_ibfk_1 FOREIGN KEY (user_id) REFERENCES api_users (id);

ALTER TABLE transactions
  ADD CONSTRAINT transactions_ibfk_1 FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE ON UPDATE RESTRICT;

INSERT INTO `users` (`id`, `code`, `nachname`, `vorname`, `password`, `email`, `kommentar`, `is_locked`, `is_admin`) VALUES
(1, '9999999999', 'Administrator', 'Admin', 'scrypt:32768:8:1$ggOvLlu4mzw7kF1u$2d353529e952fa9793f794c9570146f0226f4b2d7222d1b76d984234c144c39326321ed6fc122c14e1c31d11903cee7289c5f3bd4cd54d6eed46048ae41dfa4d', '', 'Admin', 0, 1);
