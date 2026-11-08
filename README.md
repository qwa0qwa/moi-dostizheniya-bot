# MAX-бот «Мои достижения»

MAX-бот для работы с достижениями и документами пользователей. Бот работает через MAX Bot API в режиме Long Polling.

В проекте реализованы профиль пользователя, поиск и выдача документов, портфолио, кабинет методиста и административная панель.

## Возможности

- Работа через MAX Bot API.
- Получение обновлений в режиме Long Polling.
- Профиль пользователя.
- Поиск и выдача документов.
- Портфолио пользователя.
- Кабинет методиста.
- Административная панель.
- Хранение данных в SQLite.
- Импорт документов из CSV.
- Сохранение базы данных и документов между перезапусками контейнера.

## Структура проекта

- `main.py` — запуск бота и Long Polling.
- `handlers.py` — обработчики команд, меню, профиля, поиска, портфолио и административной панели.
- `database.py` — работа с SQLite и миграции базы данных.
- `documents.py` — работа с документами и безопасными путями.
- `max_api.py` — клиент MAX Bot API.
- `config.py` — настройки приложения.
- `security.py` — функции безопасности.
- `import_documents.py` — импорт документов из CSV.
- `documents_template.csv` — шаблон CSV для импорта документов.
- `Dockerfile` — сборка Docker-образа.
- `compose.yaml` — конфигурация Docker Compose.
- `requirements.txt` — зависимости Python.
- `.env.example` — пример файла настроек.
- `data/` — постоянное хранение базы SQLite.
- `documents/` — загруженные документы.
- `logs/` — файлы логов.
- `russian_root_ca.cer` — корневой сертификат.
- `Russian_Trusted_Sub_CA.cer` — промежуточный сертификат.
- `Russian_Trusted_Sub_CA_2024.cer` — промежуточный сертификат.
- `max-achievements-bot.tar` — Готовый Docker-образ бота.

## Требования

- Windows, Linux или macOS.
- Docker Desktop с поддержкой Docker Compose либо Docker Engine и Compose Plugin.
- Токен MAX-бота.
- Числовые MAX ID администраторов.

Для работы бота не требуется открывать входящий порт: обновления получаются через Long Polling.

## Установка Docker

Для Windows скачайте и установите [Docker Desktop](https://www.docker.com/products/docker-desktop/). Рекомендуется использовать WSL 2.

После установки откройте PowerShell и проверьте:

```powershell
docker --version
docker compose version
```

## Настройка

Скопируйте шаблон настроек:

```powershell
Copy-Item .env.example .env
```

Откройте `.env` и укажите параметры:

```env
MAX_BOT_TOKEN=ваш_токен
ADMIN_USER_IDS=123456789
```

Если администраторов несколько, укажите их MAX ID через запятую:

```env
ADMIN_USER_IDS=123456789,987654321
```

Файл `.env` содержит секретные данные. Не загружайте его в GitHub и не передавайте третьим лицам.

## Запуск через Docker Compose

Откройте PowerShell в корневой папке проекта.

Соберите Docker-образ:

```powershell
docker compose build
```

Запустите бота:

```powershell
docker compose up -d
```

Проверьте состояние контейнера:

```powershell
docker compose ps
```

Просмотр логов:

```powershell
docker compose logs -f max-bot
```

Остановка бота:

```powershell
docker compose stop
```

Повторный запуск:

```powershell
docker compose start
```

После изменения Python-кода пересоберите и перезапустите контейнер:

```powershell
docker compose up -d --build
```

## Локальный запуск без Docker

Создайте виртуальное окружение:

```powershell
py -3.11 -m venv .venv
```

Активируйте его:

```powershell
.\.venv\Scripts\Activate.ps1
```

Установите зависимости:

```powershell
python -m pip install -r requirements.txt
```

Создайте `.env` из шаблона и заполните настройки:

```powershell
Copy-Item .env.example .env
```

Запустите бота:

```powershell
python main.py
```

## Импорт документов

Для импорта документов из CSV используйте:

```powershell
python import_documents.py documents_template.csv
```

Структура CSV должна соответствовать шаблону `documents_template.csv`.

## Хранение данных

Для постоянного хранения используются следующие каталоги:

- `data/` — база данных SQLite.
- `documents/` — документы пользователей.
- `logs/` — журналы работы бота.

Docker Compose подключает эти каталоги с хост-машины к контейнеру. Поэтому данные сохраняются при перезапуске и пересоздании контейнера.

## Резервное копирование

Перед созданием резервной копии остановите бота:

```powershell
docker compose stop
```

Создайте архив:

```powershell
Compress-Archive -Path data,documents,logs -DestinationPath "backup-$(Get-Date -Format yyyyMMdd-HHmmss).zip"
```

После копирования снова запустите бота:

```powershell
docker compose start
```

Не публикуйте резервные копии, базу данных, пользовательские документы и логи в открытом репозитории.

## Проверка конфигурации и запуск

Проверка конфигурации Docker Compose:

```powershell
docker compose config
```

Сборка образа:

```powershell
docker compose build
```

Запуск:

```powershell
docker compose up -d
```

Проверка контейнера:

```powershell
docker compose ps
```

Просмотр последних логов:

```powershell
docker compose logs --tail=100 max-bot
```

## Публикация Docker-образа

При необходимости образ можно собрать и отправить в Docker Hub:

```powershell
docker build -t REGISTRY_USER/max-achievements-bot:latest .
```

Войдите в Docker Hub:

```powershell
docker login
```

Отправьте образ:

```powershell
docker push REGISTRY_USER/max-achievements-bot:latest
```

Замените `REGISTRY_USER` на имя своего аккаунта Docker Hub.

Токен MAX-бота не должен передаваться через Dockerfile, команды сборки или тег образа. На сервере файл `.env` создаётся отдельно.

## Безопасность

Перед публикацией проекта убедитесь, что в репозитории отсутствуют:

- `.env` с токеном MAX-бота.
- Файлы базы данных SQLite с пользовательскими данными.
- Загруженные пользователями документы.
- Логи с конфиденциальной информацией.
- Виртуальное окружение `.venv`.

Секретные настройки должны храниться отдельно от исходного кода.
