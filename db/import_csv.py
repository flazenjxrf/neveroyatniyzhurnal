#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed MySQL from publications.csv (idempotent upsert).

After import, MySQL is the source of truth — CSV is optional.
"""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import mysql.connector
    from mysql.connector import errorcode
except ImportError:
    print("Install deps first: pip install -r requirements-db.txt", file=sys.stderr)
    raise

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
DEFAULT_CSV = PROJECT_ROOT / "publications.csv"
JOURNAL_SLUG = "upravlenie-riskom"
JOURNAL_TITLE = "Управление Риском"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_mysql_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql2"}:
        raise ValueError(f"Unsupported DB URL scheme: {parsed.scheme}")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/") or "ankil",
    }


def mysql_config() -> dict[str, Any]:
    url = os.environ.get("MYSQL_URL") or os.environ.get("DATABASE_URL")
    if url:
        cfg = parse_mysql_url(url)
    else:
        cfg = {
            "host": os.environ.get("MYSQL_HOST", "localhost"),
            "port": int(os.environ.get("MYSQL_PORT", "3306")),
            "user": os.environ.get("MYSQL_USER", "root"),
            "password": os.environ.get("MYSQL_PASSWORD", ""),
            "database": os.environ.get("MYSQL_DATABASE", "ankil"),
        }
    cfg["charset"] = "utf8mb4"
    cfg["use_unicode"] = True
    cfg["autocommit"] = False
    return cfg


def clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def to_int(value: str | None, field: str) -> int:
    text = clean(value)
    if text is None:
        raise ValueError(f"Missing integer field: {field}")
    return int(text)


def split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    for part in sql.split(";"):
        lines = [
            ln
            for ln in part.splitlines()
            if ln.strip() and not ln.strip().startswith("--")
        ]
        chunk = "\n".join(lines).strip()
        if chunk:
            statements.append(chunk)
    return statements


def connect(cfg: dict[str, Any]) -> mysql.connector.MySQLConnection:
    database = cfg["database"]
    server_cfg = {k: v for k, v in cfg.items() if k != "database"}

    # Best-effort create DB locally; on Railway the DB already exists.
    try:
        bootstrap = mysql.connector.connect(**server_cfg)
        cur = bootstrap.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        bootstrap.commit()
        cur.close()
        bootstrap.close()
    except mysql.connector.Error:
        pass

    return mysql.connector.connect(**cfg)


def ensure_schema(conn: mysql.connector.MySQLConnection) -> None:
    sql = (ROOT / "schema.sql").read_text(encoding="utf-8")
    cur = conn.cursor()
    for statement in split_sql(sql):
        cur.execute(statement)
    conn.commit()
    cur.close()


def upsert_journal(cur: Any) -> int:
    cur.execute(
        """
        INSERT INTO journals (slug, title)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE title = VALUES(title)
        """,
        (JOURNAL_SLUG, JOURNAL_TITLE),
    )
    cur.execute("SELECT id FROM journals WHERE slug = %s", (JOURNAL_SLUG,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Failed to upsert journal")
    return int(row[0])


def upsert_issue(
    cur: Any,
    journal_id: int,
    source_issue_id: int,
    year: int,
    issue_number: int,
    url: str | None,
) -> int:
    title = f"{JOURNAL_TITLE} №{issue_number} — {year}"
    cur.execute(
        """
        INSERT INTO issues (
          journal_id, source_issue_id, year, issue_number, title, url
        ) VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
          journal_id = VALUES(journal_id),
          year = VALUES(year),
          issue_number = VALUES(issue_number),
          title = VALUES(title),
          url = VALUES(url)
        """,
        (journal_id, source_issue_id, year, issue_number, title, url),
    )
    cur.execute(
        "SELECT id FROM issues WHERE source_issue_id = %s",
        (source_issue_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"Failed to upsert issue {source_issue_id}")
    return int(row[0])


def upsert_article(cur: Any, issue_db_id: int, row: dict[str, str]) -> None:
    cur.execute(
        """
        INSERT INTO articles (
          issue_id, source_article_id, section,
          title_ru, title_en,
          authors_short, authors_full, affiliations,
          abstract_ru, abstract_en,
          keywords_ru, keywords_en, url
        ) VALUES (
          %s, %s, %s,
          %s, %s,
          %s, %s, %s,
          %s, %s,
          %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
          issue_id = VALUES(issue_id),
          section = VALUES(section),
          title_ru = VALUES(title_ru),
          title_en = VALUES(title_en),
          authors_short = VALUES(authors_short),
          authors_full = VALUES(authors_full),
          affiliations = VALUES(affiliations),
          abstract_ru = VALUES(abstract_ru),
          abstract_en = VALUES(abstract_en),
          keywords_ru = VALUES(keywords_ru),
          keywords_en = VALUES(keywords_en),
          url = VALUES(url)
        """,
        (
            issue_db_id,
            to_int(row.get("article_id"), "article_id"),
            clean(row.get("section")),
            clean(row.get("title_ru")) or "",
            clean(row.get("title_en")),
            clean(row.get("authors_short")),
            clean(row.get("authors_full")),
            clean(row.get("affiliations")),
            clean(row.get("abstract_ru")),
            clean(row.get("abstract_en")),
            clean(row.get("keywords_ru")),
            clean(row.get("keywords_en")),
            clean(row.get("url")),
        ),
    )


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise RuntimeError(f"No rows in {csv_path}")
    return rows


def import_rows(
    conn: mysql.connector.MySQLConnection, rows: list[dict[str, str]]
) -> tuple[int, int]:
    cur = conn.cursor()
    journal_id = upsert_journal(cur)
    issue_cache: dict[int, int] = {}
    article_count = 0

    for row in rows:
        source_issue_id = to_int(row.get("issue_id"), "issue_id")
        if source_issue_id not in issue_cache:
            issue_cache[source_issue_id] = upsert_issue(
                cur,
                journal_id=journal_id,
                source_issue_id=source_issue_id,
                year=to_int(row.get("year"), "year"),
                issue_number=to_int(row.get("issue_number"), "issue_number"),
                url=clean(row.get("issue_url")),
            )
        upsert_article(cur, issue_cache[source_issue_id], row)
        article_count += 1

    conn.commit()
    cur.close()
    return len(issue_cache), article_count


def main() -> int:
    load_dotenv(ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env")

    csv_path = Path(os.environ.get("CSV_PATH", str(DEFAULT_CSV)))
    if not csv_path.is_absolute():
        csv_path = (ROOT / csv_path).resolve()
    if not csv_path.is_file():
        print(f"Seed file not found: {csv_path}", file=sys.stderr)
        return 1

    cfg = mysql_config()
    print(
        f"Connecting to {cfg['user']}@{cfg['host']}:{cfg['port']}/{cfg['database']} ..."
    )

    try:
        conn = connect(cfg)
        ensure_schema(conn)
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            print("Access denied — check MYSQL_USER / MYSQL_PASSWORD", file=sys.stderr)
        else:
            print(f"MySQL error: {err}", file=sys.stderr)
        return 1

    try:
        rows = read_rows(csv_path)
        issues, articles = import_rows(conn, rows)
        print(f"OK: upserted {issues} issues, {articles} articles")
        print("MySQL is now the source of truth.")
        return 0
    except Exception as err:
        conn.rollback()
        print(f"Import failed: {err}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
