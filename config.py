import os
import ssl
from dataclasses import dataclass
from pathlib import Path
import truststore
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

@dataclass(frozen=True)
class Settings:
    token: str
    api_url: str
    poll_timeout: int
    database: Path
    documents: Path
    admins: set[int]
    log_level: str
    log_file: Path

def load_settings() -> Settings:
    token = os.getenv("MAX_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Не задан MAX_BOT_TOKEN в .env. Не отправляй токен другим людям.")
    timeout = int(os.getenv("MAX_POLL_TIMEOUT_SECONDS", "30"))
    if not 0 <= timeout <= 90:
        raise ValueError("MAX_POLL_TIMEOUT_SECONDS должен быть от 0 до 90.")
    admins = {int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()}
    db = Path(os.getenv("DATABASE_PATH", "data/my_achievements.sqlite3"))
    docs = Path(os.getenv("DOCUMENTS_DIR", "documents"))
    log_file = Path(os.getenv("LOG_FILE", "logs/bot.log"))
    if not db.is_absolute(): db = BASE_DIR / db
    if not docs.is_absolute(): docs = BASE_DIR / docs
    if not log_file.is_absolute(): log_file = BASE_DIR / log_file
    return Settings(token, os.getenv("MAX_API_BASE_URL", "https://platform-api2.max.ru").rstrip("/"),
                    timeout, db, docs, admins, os.getenv("LOG_LEVEL", "INFO").upper(), log_file)

def ssl_context():
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
