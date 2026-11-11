-- Portable MySQL 8 schema for «Управление Риском»
-- Apply against an existing database (Railway provides one; locally create it first).

CREATE TABLE IF NOT EXISTS journals (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug VARCHAR(64) NOT NULL,
  title VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_journals_slug (slug)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS issues (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  journal_id INT UNSIGNED NOT NULL,
  source_issue_id INT UNSIGNED NOT NULL,
  year SMALLINT UNSIGNED NOT NULL,
  issue_number TINYINT UNSIGNED NOT NULL,
  title VARCHAR(255) NULL,
  url VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_issues_source (source_issue_id),
  UNIQUE KEY uq_issues_journal_year_number (journal_id, year, issue_number),
  KEY idx_issues_year_number (year, issue_number),
  CONSTRAINT fk_issues_journal
    FOREIGN KEY (journal_id) REFERENCES journals (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS articles (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  issue_id INT UNSIGNED NOT NULL,
  source_article_id INT UNSIGNED NOT NULL,
  section VARCHAR(128) NULL,
  title_ru TEXT NOT NULL,
  title_en TEXT NULL,
  authors_short TEXT NULL,
  authors_full TEXT NULL,
  affiliations TEXT NULL,
  abstract_ru MEDIUMTEXT NULL,
  abstract_en MEDIUMTEXT NULL,
  keywords_ru TEXT NULL,
  keywords_en TEXT NULL,
  url VARCHAR(512) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_articles_source (source_article_id),
  KEY idx_articles_issue (issue_id),
  CONSTRAINT fk_articles_issue
    FOREIGN KEY (issue_id) REFERENCES issues (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
