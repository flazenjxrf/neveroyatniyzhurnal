# -*- coding: utf-8 -*-
"""Парсер публикаций журнала «Управление Риском» с ankil.info/lib/3/"""

from __future__ import annotations

import json
import re
import time
import csv
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://ankil.info"
JOURNAL_URL = f"{BASE}/lib/3/"
OUT_DIR = Path(__file__).resolve().parent
JSON_PATH = OUT_DIR / "publications.json"
CSV_PATH = OUT_DIR / "publications.csv"
PROGRESS_PATH = OUT_DIR / "scrape_progress.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

DELAY = 0.4


def clean(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" {2,}", " ", text)
    return text.strip()


def fetch(url: str, retries: int = 3) -> BeautifulSoup:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            time.sleep(DELAY)
            r = SESSION.get(url, timeout=40)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return BeautifulSoup(r.text, "lxml")
        except Exception as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Не удалось загрузить {url}: {last_err}")


def content_cell(soup: BeautifulSoup):
    """Основная ячейка с контентом выпуска/статьи (третья td после архива)."""
    for td in soup.select("td[valign=top]"):
        if td.find("h1") or td.find("h2"):
            # пропускаем сайдбар архива
            if td.find("div", class_="libnum"):
                continue
            return td
    return soup


def parse_issue_heading(text: str) -> dict[str, Any]:
    """«Управление Риском №5 - 2026» -> year, number."""
    text = clean(text)
    m = re.search(r"№\s*(\d+)\s*[-–—]\s*(\d{4})", text)
    if m:
        return {"issue_number": int(m.group(1)), "year": int(m.group(2)), "issue_title": text}
    m = re.search(r"(\d{4}).*?№\s*(\d+)", text)
    if m:
        return {"issue_number": int(m.group(2)), "year": int(m.group(1)), "issue_title": text}
    return {"issue_number": None, "year": None, "issue_title": text}


def collect_issues() -> list[dict[str, Any]]:
    soup = fetch(JOURNAL_URL)
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    libnum = soup.find("div", class_="libnum")
    current_year: int | None = None

    if libnum:
        for node in libnum.descendants:
            if getattr(node, "name", None) == "b" and "darkblue" in (node.get("class") or []):
                y = clean(node.get_text())
                if y.isdigit() and y != "0000":
                    current_year = int(y)
                else:
                    current_year = None
            elif getattr(node, "name", None) == "a" and node.get("href"):
                href = node["href"]
                if not re.match(r"^/lib/3/\d+/?$", href):
                    continue
                url = urljoin(BASE, href)
                if url in seen:
                    continue
                seen.add(url)
                num_text = clean(node.get_text())
                num = int(num_text) if num_text.isdigit() else None
                issues.append(
                    {
                        "url": url,
                        "issue_id": href.strip("/").split("/")[-1],
                        "year": current_year,
                        "issue_number": num,
                        "from_archive": True,
                    }
                )

    # Текущий выпуск на главной странице журнала (может не быть ссылки в архиве)
    cell = content_cell(soup)
    h2 = cell.find("h2") if cell else None
    if h2:
        meta = parse_issue_heading(h2.get_text())
        article_links = cell.find_all("a", href=re.compile(r"^/lib/3/\d+/\d+/?$"))
        issue_id = None
        if article_links:
            issue_id = article_links[0]["href"].strip("/").split("/")[-2]
        current_url = f"{BASE}/lib/3/{issue_id}/" if issue_id else JOURNAL_URL
        if current_url not in seen and issue_id:
            seen.add(current_url)
            issues.insert(
                0,
                {
                    "url": current_url,
                    "issue_id": issue_id,
                    "year": meta["year"],
                    "issue_number": meta["issue_number"],
                    "from_archive": False,
                    "listing_url": JOURNAL_URL,
                },
            )

    return issues


def parse_issue_articles(issue: dict[str, Any]) -> list[dict[str, Any]]:
    url = issue.get("listing_url") or issue["url"]
    soup = fetch(url)
    cell = content_cell(soup)
    h2 = cell.find("h2") if cell else None
    if h2:
        meta = parse_issue_heading(h2.get_text())
        if issue.get("year") is None:
            issue["year"] = meta["year"]
        if issue.get("issue_number") is None:
            issue["issue_number"] = meta["issue_number"]
        issue["issue_title"] = meta["issue_title"]

    articles: list[dict[str, Any]] = []
    section: str | None = None

    # Идём по узлам контента: h3 = рубрика, i = авторы, a = название
    nodes = list(cell.children) if cell else []
    # BeautifulSoup children могут быть NavigableString; удобнее найти все значимые теги по порядку
    tags = cell.find_all(["h3", "i", "a"]) if cell else []

    pending_authors = ""
    for tag in tags:
        if tag.name == "h3":
            section = clean(tag.get_text())
            pending_authors = ""
        elif tag.name == "i":
            txt = clean(tag.get_text())
            if not txt:
                continue
            nxt = tag.find_next(["a", "h3", "h1"])
            if nxt and nxt.name == "a" and re.match(r"^/lib/3/\d+/\d+/?$", nxt.get("href", "")):
                pending_authors = txt
        elif tag.name == "a":
            href = tag.get("href") or ""
            if not re.match(r"^/lib/3/\d+/\d+/?$", href):
                continue
            # пропускаем ссылки-ключевые слова
            if "/lib/search/" in href:
                continue
            parts = href.strip("/").split("/")
            article_id = parts[-1]
            issue_id = parts[-2]
            title = clean(tag.get_text())
            if not title:
                continue
            articles.append(
                {
                    "article_id": article_id,
                    "issue_id": issue_id,
                    "url": urljoin(BASE, href),
                    "title_ru": title,
                    "authors_short": pending_authors,
                    "section": section,
                    "year": issue.get("year"),
                    "issue_number": issue.get("issue_number"),
                    "issue_title": issue.get("issue_title"),
                    "issue_url": issue["url"],
                }
            )
            pending_authors = ""

    return articles


def parse_article_detail(article: dict[str, Any]) -> dict[str, Any]:
    soup = fetch(article["url"])
    cell = content_cell(soup)
    data = dict(article)

    h2 = cell.find("h2") if cell else None
    if h2:
        meta = parse_issue_heading(h2.get_text())
        data["issue_title"] = meta["issue_title"] or data.get("issue_title")
        data["year"] = data.get("year") or meta["year"]
        data["issue_number"] = data.get("issue_number") or meta["issue_number"]

    h3 = cell.find("h3") if cell else None
    if h3:
        data["section"] = clean(h3.get_text()) or data.get("section")

    # Авторы и аффилиации: <i> до <h1> (часто пары имя / аффилиация)
    h1 = cell.find("h1") if cell else None
    authors: list[dict[str, str]] = []
    if h1:
        italics: list[str] = []
        for el in cell.descendants:
            if el is h1:
                break
            if getattr(el, "name", None) == "i":
                t = clean(el.get_text())
                if t:
                    italics.append(t)

        AFF_START = re.compile(
            r"^(кандидат|доктор|профессор|доцент|аспирант|соискатель|"
            r"магистрант|студент|научный|старший|младший|ведущий|"
            r"член[- ]корреспондент|академик|заведующ|директор|"
            r"руководитель|сотрудник|специалист|эксперт)",
            re.I,
        )
        NAME_RE = re.compile(
            r"^[А-ЯЁA-Z][а-яёa-zA-Z\-]*(?:\s+[А-ЯЁA-Z][а-яёa-zA-Z\-]*)*"
            r"(?:\s+[А-ЯЁA-Z]\.?\s*[А-ЯЁA-Z]\.?|\s+[А-ЯЁA-Z]\.)\s*$"
        )
        # несколько авторов в одном <i>: «Иванов И. И., Петров П. П.»
        MULTI_NAME_RE = re.compile(
            r"^(?:[А-ЯЁA-Z][а-яёa-zA-Z\-]*(?:\s+[А-ЯЁA-Z][а-яёa-zA-Z\-]*)*"
            r"(?:\s+[А-ЯЁA-Z]\.?\s*[А-ЯЁA-Z]\.?|\s+[А-ЯЁA-Z]\.)\s*,\s*)+"
            r"[А-ЯЁA-Z][а-яёa-zA-Z\-]*(?:\s+[А-ЯЁA-Z][а-яёa-zA-Z\-]*)*"
            r"(?:\s+[А-ЯЁA-Z]\.?\s*[А-ЯЁA-Z]\.?|\s+[А-ЯЁA-Z]\.)\s*$"
        )

        def looks_like_name(s: str) -> bool:
            s = s.strip()
            if not s or len(s) > 180:
                return False
            if AFF_START.search(s):
                return False
            if NAME_RE.match(s) or MULTI_NAME_RE.match(s):
                return True
            # китайские/иностранные имена без инициалов, короткие
            if len(s) < 60 and "," not in s and not AFF_START.search(s):
                if re.search(r"(университет|кафедра|институт|академи|факультет)", s, re.I):
                    return False
                # «Тай Линтун» и т.п.
                if re.match(r"^[\wА-Яа-яЁё\-]+(?:\s+[\wА-Яа-яЁё\-]+){0,3}$", s):
                    return True
            return False

        i = 0
        while i < len(italics):
            cur = italics[i]
            if looks_like_name(cur):
                aff = ""
                if i + 1 < len(italics) and not looks_like_name(italics[i + 1]):
                    aff = italics[i + 1]
                    i += 2
                else:
                    i += 1
                authors.append({"name": cur, "affiliation": aff})
            else:
                # аффилиация без имени — привяжем к предыдущему автору
                if authors and not authors[-1]["affiliation"]:
                    authors[-1]["affiliation"] = cur
                else:
                    authors.append({"name": "", "affiliation": cur})
                i += 1
        data["authors"] = [a for a in authors if a["name"] or a["affiliation"]]
        if authors and not data.get("authors_short"):
            data["authors_short"] = ", ".join(a["name"] for a in authors if a["name"])

    if h1:
        data["title_ru"] = clean(h1.get_text()) or data.get("title_ru")

    # Аннотации: p[align=justify] — RU затем EN
    abstracts = []
    if cell:
        for p in cell.find_all("p", attrs={"align": "justify"}):
            abstracts.append(clean(p.get_text()))
    data["abstract_ru"] = abstracts[0] if abstracts else ""
    data["abstract_en"] = abstracts[1] if len(abstracts) > 1 else ""

    h4 = cell.find("h4") if cell else None
    data["title_en"] = clean(h4.get_text()) if h4 else ""

    # Ключевые слова: ссылки /lib/search/ до и после английского заголовка
    keywords_ru: list[str] = []
    keywords_en: list[str] = []
    if cell:
        search_links = cell.find_all("a", href=re.compile(r"/lib/search/"))
        for a in search_links:
            kw = clean(a.get_text())
            if not kw:
                continue
            # до h4 — русские, после — английские
            if h4 and a.find_previous("h4") is h4:
                keywords_en.append(kw)
            else:
                keywords_ru.append(kw)
    data["keywords_ru"] = keywords_ru
    data["keywords_en"] = keywords_en

    # prod_id из формы заказа
    prod = soup.find("input", {"name": "prod_id"})
    if prod and prod.get("value"):
        data["product_id"] = prod["value"]

    return data


def save_progress(payload: dict[str, Any]) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def export_csv(publications: list[dict[str, Any]]) -> None:
    fields = [
        "year",
        "issue_number",
        "section",
        "title_ru",
        "title_en",
        "authors_short",
        "authors_full",
        "affiliations",
        "abstract_ru",
        "abstract_en",
        "keywords_ru",
        "keywords_en",
        "url",
        "article_id",
        "issue_id",
        "issue_url",
    ]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for p in publications:
            authors = p.get("authors") or []
            row = {
                "year": p.get("year"),
                "issue_number": p.get("issue_number"),
                "section": p.get("section"),
                "title_ru": p.get("title_ru"),
                "title_en": p.get("title_en"),
                "authors_short": p.get("authors_short"),
                "authors_full": " | ".join(a.get("name", "") for a in authors),
                "affiliations": " | ".join(a.get("affiliation", "") for a in authors),
                "abstract_ru": p.get("abstract_ru"),
                "abstract_en": p.get("abstract_en"),
                "keywords_ru": "; ".join(p.get("keywords_ru") or []),
                "keywords_en": "; ".join(p.get("keywords_en") or []),
                "url": p.get("url"),
                "article_id": p.get("article_id"),
                "issue_id": p.get("issue_id"),
                "issue_url": p.get("issue_url"),
            }
            w.writerow(row)


def main() -> None:
    print("1/3 Сбор списка выпусков...")
    issues = collect_issues()
    print(f"   Найдено выпусков: {len(issues)}")

    print("2/3 Сбор оглавлений выпусков...")
    all_articles: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, issue in enumerate(issues, 1):
        try:
            arts = parse_issue_articles(issue)
            print(
                f"   [{idx}/{len(issues)}] {issue.get('year')}-{issue.get('issue_number')} "
                f"→ {len(arts)} статей ({issue['url']})"
            )
            for a in arts:
                key = a["article_id"]
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                all_articles.append(a)
        except Exception as e:
            print(f"   ! Ошибка выпуска {issue['url']}: {e}")
        save_progress({"stage": "toc", "issues_done": idx, "articles": all_articles})

    print(f"   Всего уникальных статей в оглавлениях: {len(all_articles)}")

    print("3/3 Загрузка карточек статей...")
    publications: list[dict[str, Any]] = []
    # resume if progress has details
    done_ids = set()
    if PROGRESS_PATH.exists():
        try:
            prev = json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
            if prev.get("stage") == "details" and prev.get("publications"):
                publications = prev["publications"]
                done_ids = {p["article_id"] for p in publications if p.get("article_id")}
                print(f"   Продолжаем с уже сохранённых: {len(done_ids)}")
        except Exception:
            pass

    total = len(all_articles)
    for idx, art in enumerate(all_articles, 1):
        if art["article_id"] in done_ids:
            continue
        try:
            detailed = parse_article_detail(art)
            publications.append(detailed)
            if idx % 10 == 0 or idx == total:
                print(f"   [{idx}/{total}] {detailed.get('title_ru', '')[:70]}")
                save_progress(
                    {
                        "stage": "details",
                        "articles": all_articles,
                        "publications": publications,
                    }
                )
        except Exception as e:
            print(f"   ! Ошибка статьи {art['url']}: {e}")
            publications.append({**art, "error": str(e)})

    # сортировка: год desc, номер desc
    publications.sort(
        key=lambda p: (p.get("year") or 0, p.get("issue_number") or 0, p.get("article_id") or ""),
        reverse=True,
    )

    result = {
        "source": JOURNAL_URL,
        "journal": "Управление Риском",
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "issues_count": len(issues),
        "publications_count": len(publications),
        "issues": issues,
        "publications": publications,
    }
    JSON_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    export_csv(publications)
    print(f"\nГотово: {len(publications)} публикаций")
    print(f"  JSON: {JSON_PATH}")
    print(f"  CSV:  {CSV_PATH}")


if __name__ == "__main__":
    main()
