#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flask app: journal site backed by MySQL (Railway-ready)."""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import mysql.connector
from flask import Flask, abort, redirect, render_template, send_from_directory, url_for

ROOT = Path(__file__).resolve().parent
JOURNAL_SLUG = "upravlenie-riskom"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv(ROOT / "db" / ".env")
load_dotenv(ROOT / ".env")


def parse_mysql_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql2"}:
        raise ValueError(f"Unsupported DB URL scheme: {parsed.scheme}")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/") or "railway",
    }


def mysql_config() -> dict[str, Any]:
    # Railway private vars first, then public/.env names, then URL.
    host = os.environ.get("MYSQLHOST") or os.environ.get("MYSQL_HOST")
    if host:
        cfg = {
            "host": host,
            "port": int(
                os.environ.get("MYSQLPORT")
                or os.environ.get("MYSQL_PORT")
                or "3306"
            ),
            "user": os.environ.get("MYSQLUSER")
            or os.environ.get("MYSQL_USER")
            or "root",
            "password": os.environ.get("MYSQLPASSWORD")
            or os.environ.get("MYSQL_PASSWORD")
            or os.environ.get("MYSQL_ROOT_PASSWORD")
            or "",
            "database": os.environ.get("MYSQLDATABASE")
            or os.environ.get("MYSQL_DATABASE")
            or "railway",
        }
    else:
        url = os.environ.get("MYSQL_URL") or os.environ.get("DATABASE_URL")
        if url:
            cfg = parse_mysql_url(url)
        else:
            cfg = {
                "host": "localhost",
                "port": 3306,
                "user": "root",
                "password": "",
                "database": "railway",
            }
    cfg["charset"] = "utf8mb4"
    cfg["use_unicode"] = True
    cfg["ssl_disabled"] = True
    return cfg


def get_db():
    return mysql.connector.connect(**mysql_config())


def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = list(cur.fetchall())
        cur.close()
        return rows
    finally:
        conn.close()


def fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


app = Flask(__name__, template_folder="templates")


@app.route("/css/<path:filename>")
def css_files(filename: str):
    return send_from_directory(ROOT / "css", filename)


@app.route("/assets/<path:filename>")
def asset_files(filename: str):
    return send_from_directory(ROOT / "assets", filename)


@app.route("/")
def index():
    return render_template("index.html", active="home")


@app.route("/about")
@app.route("/about.html")
def about():
    return render_template("about.html", active="about")


@app.route("/journals")
@app.route("/journals.html")
def journals():
    return render_template("journals.html", active="journals")


@app.route("/journal")
@app.route("/journal.html")
def journal():
    latest = fetch_one(
        """
        SELECT id, year, issue_number, title, url, source_issue_id
        FROM issues
        ORDER BY year DESC, issue_number DESC
        LIMIT 1
        """
    )
    return render_template(
        "journal.html",
        active="journals",
        latest=latest,
    )


@app.route("/archive")
@app.route("/archive.html")
def archive():
    latest = fetch_one(
        """
        SELECT id FROM issues
        ORDER BY year DESC, issue_number DESC
        LIMIT 1
        """
    )
    latest_id = latest["id"] if latest else None
    if latest_id:
        issues = fetch_all(
            """
            SELECT id, year, issue_number, title, url, source_issue_id
            FROM issues
            WHERE id <> %s
            ORDER BY year DESC, issue_number DESC
            """,
            (latest_id,),
        )
    else:
        issues = fetch_all(
            """
            SELECT id, year, issue_number, title, url, source_issue_id
            FROM issues
            ORDER BY year DESC, issue_number DESC
            """
        )

    by_year: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        by_year[int(issue["year"])].append(issue)
    years = sorted(by_year.keys(), reverse=True)
    return render_template(
        "archive.html",
        active="journals",
        years=years,
        by_year=by_year,
    )


@app.route("/issue/<int:issue_id>")
def issue(issue_id: int):
    issue_row = fetch_one(
        """
        SELECT id, year, issue_number, title, url, source_issue_id
        FROM issues
        WHERE id = %s
        """,
        (issue_id,),
    )
    if not issue_row:
        abort(404)
    articles = fetch_all(
        """
        SELECT id, section, title_ru, title_en, authors_short, url, source_article_id
        FROM articles
        WHERE issue_id = %s
        ORDER BY id ASC
        """,
        (issue_id,),
    )
    return render_template(
        "issue.html",
        active="journals",
        issue=issue_row,
        articles=articles,
    )


# Legacy stub filename
@app.route("/issue.html")
def issue_legacy():
    latest = fetch_one(
        """
        SELECT id FROM issues
        ORDER BY year DESC, issue_number DESC
        LIMIT 1
        """
    )
    if not latest:
        abort(404)
    return redirect(url_for("issue", issue_id=latest["id"]))


@app.route("/health")
def health():
    try:
        fetch_one("SELECT 1 AS ok")
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
