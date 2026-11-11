#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build db/seed.sql from publications.csv for Railway MySQL console import."""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
CSV_PATH = PROJECT / "publications.csv"
OUT_PATH = ROOT / "seed.sql"
SCHEMA_PATH = ROOT / "schema.sql"

JOURNAL_SLUG = "upravlenie-riskom"
JOURNAL_TITLE = "Управление Риском"


def sql_str(value: str | None) -> str:
    if value is None:
        return "NULL"
    text = value.strip()
    if not text:
        return "NULL"
    esc = (
        text.replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\x00", "")
    )
    return "'" + esc + "'"


def sql_int(value: str | None, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise ValueError(f"Missing {field}")
    return str(int(text))


def main() -> None:
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))

    parts: list[str] = []
    parts.append("-- Auto-generated seed for Railway MySQL console")
    parts.append("SET NAMES utf8mb4;")
    parts.append("SET FOREIGN_KEY_CHECKS=0;")
    parts.append("")
    parts.append(SCHEMA_PATH.read_text(encoding="utf-8").strip())
    parts.append("")
    parts.append(
        "INSERT INTO journals (slug, title) VALUES "
        f"({sql_str(JOURNAL_SLUG)}, {sql_str(JOURNAL_TITLE)}) "
        "ON DUPLICATE KEY UPDATE title=VALUES(title);"
    )
    parts.append(
        f"SET @journal_id := (SELECT id FROM journals WHERE slug={sql_str(JOURNAL_SLUG)});"
    )
    parts.append("")

    issues: dict[str, dict[str, str]] = {}
    for row in rows:
        iid = row["issue_id"].strip()
        if iid not in issues:
            issues[iid] = row

    for iid, row in sorted(issues.items(), key=lambda x: int(x[0])):
        year = sql_int(row["year"], "year")
        num = sql_int(row["issue_number"], "issue_number")
        title = f"{JOURNAL_TITLE} №{row['issue_number'].strip()} — {row['year'].strip()}"
        parts.append(
            "INSERT INTO issues "
            "(journal_id, source_issue_id, year, issue_number, title, url) VALUES ("
            f"@journal_id, {sql_int(iid, 'issue_id')}, {year}, {num}, "
            f"{sql_str(title)}, {sql_str(row.get('issue_url'))}"
            ") ON DUPLICATE KEY UPDATE "
            "year=VALUES(year), issue_number=VALUES(issue_number), "
            "title=VALUES(title), url=VALUES(url);"
        )

    parts.append("")

    batch: list[str] = []
    batch_size = 25

    def flush() -> None:
        nonlocal batch
        if not batch:
            return
        parts.append(
            "INSERT INTO articles ("
            "issue_id, source_article_id, section, title_ru, title_en, "
            "authors_short, authors_full, affiliations, "
            "abstract_ru, abstract_en, keywords_ru, keywords_en, url"
            ") VALUES\n"
            + ",\n".join(batch)
            + "\nON DUPLICATE KEY UPDATE "
            "issue_id=VALUES(issue_id), section=VALUES(section), "
            "title_ru=VALUES(title_ru), title_en=VALUES(title_en), "
            "authors_short=VALUES(authors_short), authors_full=VALUES(authors_full), "
            "affiliations=VALUES(affiliations), abstract_ru=VALUES(abstract_ru), "
            "abstract_en=VALUES(abstract_en), keywords_ru=VALUES(keywords_ru), "
            "keywords_en=VALUES(keywords_en), url=VALUES(url);"
        )
        parts.append("")
        batch = []

    for row in rows:
        issue_id = sql_int(row["issue_id"], "issue_id")
        article_id = sql_int(row["article_id"], "article_id")
        title_ru = sql_str(row.get("title_ru"))
        if title_ru == "NULL":
            title_ru = "''"
        values = (
            f"((SELECT id FROM issues WHERE source_issue_id={issue_id}), "
            f"{article_id}, "
            f"{sql_str(row.get('section'))}, "
            f"{title_ru}, "
            f"{sql_str(row.get('title_en'))}, "
            f"{sql_str(row.get('authors_short'))}, "
            f"{sql_str(row.get('authors_full'))}, "
            f"{sql_str(row.get('affiliations'))}, "
            f"{sql_str(row.get('abstract_ru'))}, "
            f"{sql_str(row.get('abstract_en'))}, "
            f"{sql_str(row.get('keywords_ru'))}, "
            f"{sql_str(row.get('keywords_en'))}, "
            f"{sql_str(row.get('url'))})"
        )
        batch.append(values)
        if len(batch) >= batch_size:
            flush()
    flush()

    parts.append("SET FOREIGN_KEY_CHECKS=1;")
    OUT_PATH.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes), rows={len(rows)}, issues={len(issues)}")


if __name__ == "__main__":
    main()
