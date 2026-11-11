# MySQL для журнала «Управление Риском»

После импорта **источник правды — MySQL**. Файл `publications.csv` нужен только один раз, чтобы залить данные.

## Таблицы

- `journals` — журнал
- `issues` — выпуски (`year`, `issue_number`)
- `articles` — статьи

Схема: [`schema.sql`](schema.sql)

## Переменные окружения

Скопируй [`.env.example`](.env.example) в `db/.env` или задай переменные в Railway:

| Переменная | Пример |
|---|---|
| `MYSQL_HOST` | ` maglev.proxy.rlwy.net` |
| `MYSQL_PORT` | `3306` |
| `MYSQL_USER` | `root` |
| `MYSQL_PASSWORD` | `...` |
| `MYSQL_DATABASE` | `railway` / `ankil` |

Либо один URL: `MYSQL_URL` / `DATABASE_URL` = `mysql://user:pass@host:3306/db`

## Локально

```bash
pip install -r requirements-db.txt
# поднять MySQL и создать БД (или дать права на CREATE DATABASE)
cp db/.env.example db/.env
# заполни пароль в db/.env
python db/import_csv.py
```

Скрипт сам применит `schema.sql` и сделает upsert выпусков/статей.

## Railway

1. Добавь сервис **MySQL** в проект.
2. В сервис приложения / one-off job пропиши переменные из MySQL-плагина (`MYSQLHOST` → `MYSQL_HOST` и т.п., либо `DATABASE_URL`).
3. Один раз запусти:

```bash
pip install -r requirements-db.txt
python db/import_csv.py
```

Повторный запуск безопасен: строки обновляются по `source_issue_id` / `source_article_id`.

## Перенос на российский сервер

Тот же MySQL 8:

1. Создай БД и пользователя.
2. Пропиши те же `MYSQL_*`.
3. `python db/import_csv.py` — если CSV ещё есть; иначе сделай `mysqldump` с Railway и восстанови на новом хосте.
