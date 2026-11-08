# MAX-бот «Мои достижения»

Бот работает через MAX Bot API в режиме Long Polling. В проекте сохранены профиль пользователя, поиск и выдача документов, портфолио, кабинет методиста и административная панель.

## Структура

- `main.py` — запуск Long Polling.
- `handlers.py` — меню, профиль, поиск, портфолио, кабинет методиста и админ-панель.
- `database.py` — SQLite и мягкие миграции существующей базы.
- `documents.py` — безопасные пути и импорт документов из CSV.
- `max_api.py` — асинхронный клиент MAX Bot API.
- `data/` — постоянная SQLite-база.
- `documents/` — загруженные документы.
- `logs/` — файл логов.
- `tests/` — автоматические тесты.

## Требования

- Docker Desktop с поддержкой Docker Compose.
- Токен MAX-бота.
- Числовые MAX ID администраторов.

Открытый входящий порт не нужен: бот сам получает обновления через Long Polling.

### Установка Docker Desktop

В Windows скачайте Docker Desktop с [официальной страницы](https://www.docker.com/products/docker-desktop/), установите вариант с WSL 2 и перезапустите Docker Desktop. Проверьте установку:

```powershell
docker --version
docker compose version
```

В Linux установите Docker Engine и Compose Plugin по инструкции для своего дистрибутива в [официальной документации Docker](https://docs.docker.com/engine/install/).

## Настройка

1. Скопируйте шаблон настроек:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Заполните `.env`:

   ```dotenv
   MAX_BOT_TOKEN=ваш_токен
   ADMIN_USER_IDS=123456789
   ```

   Несколько администраторов указываются через запятую. Файл `.env` нельзя добавлять в GitHub.

Значения `DATABASE_PATH=data/my_achievements.sqlite3`, `DOCUMENTS_DIR=documents` и `LOG_FILE=logs/bot.log` подходят для запуска через Compose и сохраняются на хосте.

## Запуск в Docker

Из корня проекта:

```powershell
docker compose build
docker compose up -d
docker compose logs -f max-bot
```

Остановка:

```powershell
docker compose stop
```

Полное удаление контейнера без удаления данных:

```powershell
docker compose down
```

После изменения Python-кода пересоберите образ:

```powershell
docker compose up -d --build
```

## Локальный запуск без Docker

PowerShell в Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Импорт CSV:

```powershell
python import_documents.py documents_template.csv
```

## Данные и резервное копирование

Compose монтирует `data/`, `documents/` и `logs/` с хоста в контейнер. Поэтому перезапуск или пересоздание контейнера не удаляет базу, документы и логи.

Остановите бота перед копированием базы и создайте архив:

```powershell
docker compose stop
Compress-Archive -Path data,documents,logs -DestinationPath "backup-$(Get-Date -Format yyyyMMdd-HHmmss).zip"
docker compose start
```

Не публикуйте этот архив, SQLite-файл, пользовательские документы или логи в открытом репозитории.

## Проверки

```powershell
python -m pytest -q
```

Проверка конфигурации и импорта модулей:

```powershell
python -m py_compile config.py database.py documents.py handlers.py import_documents.py main.py max_api.py security.py
```

Проверка Docker выполняется на машине, где установлен и запущен Docker Desktop:

```powershell
docker compose config
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=100 max-bot
docker compose down
```

Для проверки сохранения данных создайте тестовую запись или загрузите документ, выполните `docker compose down`, затем снова `docker compose up -d` и убедитесь, что данные доступны. Не используйте для этого реальные пользовательские данные в публикуемом репозитории.

## Публикация

Перед публикацией проверьте, что в коммит не попали `.env`, `data/*.sqlite3`, содержимое `documents/`, `doc/`, `logs/*.log` и `.venv/`.

Сборка образа для реестра:

```powershell
docker build -t REGISTRY_USER/max-achievements-bot:latest .
docker login
docker push REGISTRY_USER/max-achievements-bot:latest
```

Токен не передаётся через `Dockerfile`, `docker build` или тег образа. На сервере создайте `.env` отдельно и запускайте Compose с этим файлом.
