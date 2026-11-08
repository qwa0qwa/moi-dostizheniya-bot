import asyncio
import logging

from config import load_settings
from database import Database
from handlers import handle_update
from max_api import MaxApiClient, MaxApiError

async def run():
    settings = load_settings()
    settings.documents.mkdir(parents=True, exist_ok=True)
    settings.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(settings.log_file, encoding="utf-8")],
    )
    db = Database(settings.database)
    api = MaxApiClient(settings)
    marker = None
    logging.getLogger(__name__).info("Бот запущен в режиме Long Polling.")
    try:
        while True:
            try:
                result = await api.get_updates(marker, settings.poll_timeout)
                updates = result.get("updates", [])
                next_marker = result.get("marker")
                for update in updates:
                    try:
                        await handle_update(update, api, db, settings)
                    except Exception:
                        logging.getLogger(__name__).exception("Ошибка обработки обновления")
                if next_marker is not None:
                    marker = next_marker
            except MaxApiError:
                await asyncio.sleep(3)
    finally:
        db.close()
        await api.close()

if __name__ == "__main__":
    try: asyncio.run(run())
    except KeyboardInterrupt:
        print("Бот остановлен.")
