import asyncio
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx
from config import Settings, ssl_context

log = logging.getLogger(__name__)

class MaxApiError(Exception): pass

class MaxApiClient:
    def __init__(self, settings: Settings):
        self.client = httpx.AsyncClient(base_url=settings.api_url,
          headers={"Authorization": settings.token}, verify=ssl_context(),
          timeout=httpx.Timeout(100, connect=20))

    async def get_updates(self, marker=None, timeout=30):
        params={"timeout":timeout,"limit":100}
        if marker is not None: params["marker"]=marker
        try:
            r=await self.client.get("/updates",params=params); r.raise_for_status()
            data=r.json()
            return data if isinstance(data,dict) else {}
        except (httpx.HTTPError,ValueError) as e:
            log.exception("GET /updates failed"); raise MaxApiError("Не удалось получить обновления MAX.") from e

    async def send_message(self, uid, text, attachments=None):
        body={"text":text}
        if attachments: body["attachments"]=attachments
        try:
            r=await self.client.post("/messages",params={"user_id":uid},json=body); r.raise_for_status()
            return r.json() if r.content else {}
        except httpx.HTTPStatusError as e:
            code = ""
            message = ""
            try:
                error_data = e.response.json()
                if isinstance(error_data, dict):
                    code = str(error_data.get("code") or "")
                    message = str(error_data.get("message") or "")
            except ValueError:
                pass
            # Сохраняем код ошибки MAX: send_file использует его для повтора
            # при временном attachment.not.ready.
            details = " ".join(part for part in (code, message) if part)
            log.warning("POST /messages returned HTTP %s (%s)", e.response.status_code, code or "no-code")
            raise MaxApiError(f"MAX API HTTP {e.response.status_code}: {details or 'ошибка отправки сообщения'}") from e
        except (httpx.HTTPError,ValueError) as e:
            log.exception("POST /messages failed"); raise MaxApiError("Не удалось отправить сообщение.") from e

    async def edit_message(self, message_id, text, attachments=None):
        body={"text":text}
        if attachments is not None:
            body["attachments"]=attachments
        try:
            r=await self.client.put("/messages",params={"message_id":message_id},json=body)
            r.raise_for_status()
            return r.json() if r.content else {}
        except (httpx.HTTPError,ValueError) as e:
            log.exception("PUT /messages failed"); raise MaxApiError("Не удалось обновить экран бота.") from e

    async def answer_callback(self, callback_id, notification=""):
        try:
            r=await self.client.post("/answers",params={"callback_id":callback_id},json={"notification":notification})
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.exception("POST /answers failed"); raise MaxApiError("Не удалось ответить на нажатие кнопки.") from e

    async def delete_message(self, message_id):
        try:
            r=await self.client.delete("/messages",params={"message_id":message_id})
            r.raise_for_status()
            data=r.json() if r.content else {}
            if isinstance(data,dict) and data.get("success") is False:
                raise MaxApiError(data.get("message") or "MAX не удалил сообщение.")
            return data
        except httpx.HTTPError as e:
            log.exception("DELETE /messages failed")
            raise MaxApiError("Не удалось удалить сообщение.") from e

    async def send_file(self, uid, path: Path, caption=""):
        """Загружает файл в MAX и отправляет его отдельным сообщением."""
        path = Path(path)
        if not path.is_file():
            raise MaxApiError("Файл документа отсутствует на сервере бота.")

        try:
            # Шаг 1. Получаем одноразовый URL загрузки.
            response = await self.client.post("/uploads", params={"type": "file"})
            response.raise_for_status()
            try:
                upload_info = response.json()
            except ValueError as exc:
                raise MaxApiError("MAX вернул некорректный ответ при подготовке загрузки.") from exc

            upload_url = upload_info.get("url") if isinstance(upload_info, dict) else None
            # Для типа file токен обычно приходит на шаге 2, но оставляем
            # поддержку ответа, в котором он уже присутствует.
            token = upload_info.get("token") if isinstance(upload_info, dict) else None
            if not upload_url:
                log.error("MAX /uploads response did not contain 'url'; keys=%s",
                          list(upload_info.keys()) if isinstance(upload_info, dict) else type(upload_info).__name__)
                raise MaxApiError("MAX не вернул ссылку для загрузки файла.")

            # Шаг 2. Загружаем файл; для обычного file MAX возвращает token здесь.
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            async with httpx.AsyncClient(verify=ssl_context(), timeout=180) as uploader:
                with path.open("rb") as file_stream:
                    uploaded = await uploader.post(
                        upload_url,
                        files={"data": (path.name, file_stream, mime)},
                    )
                uploaded.raise_for_status()
                try:
                    upload_result = uploaded.json()
                except ValueError:
                    upload_result = {}

            if isinstance(upload_result, dict):
                token = upload_result.get("token") or token
            if not token:
                log.error("MAX file upload response did not contain 'token'; status=%s content_type=%s",
                          uploaded.status_code, uploaded.headers.get("content-type", ""))
                raise MaxApiError("MAX принял файл, но не вернул токен для отправки.")

            # MAX может ещё обрабатывать файл. Повторяем отправку при временной
            # ошибке готовности вложения.
            last_error = None
            for delay in (0, 1, 2, 4):
                if delay:
                    await asyncio.sleep(delay)
                try:
                    return await self.send_message(
                        uid, caption,
                        [{"type": "file", "payload": {"token": token}}],
                    )
                except MaxApiError as exc:
                    last_error = exc
                    if "attachment.not.ready" not in str(exc).lower() and "not processed" not in str(exc).lower():
                        raise
            raise last_error or MaxApiError("MAX не смог обработать загруженный файл.")

        except MaxApiError:
            raise
        except (httpx.HTTPError, OSError, ValueError) as exc:
            log.exception("File upload or delivery failed")
            raise MaxApiError("Не удалось загрузить или отправить документ через MAX.") from exc


    async def download_attachment(self, url, destination, max_bytes=25*1024*1024):
        """Скачивает вложение из MAX в локальную папку документов."""
        parsed=urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise MaxApiError("MAX передал некорректную ссылку на файл.")
        try:
            async with httpx.AsyncClient(verify=ssl_context(), timeout=120, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    length=int(response.headers.get("content-length", "0") or 0)
                    if length and length > max_bytes:
                        raise MaxApiError("Файл слишком большой. Максимальный размер — 25 МБ.")
                    total=0
                    with Path(destination).open("wb") as f:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            if total > max_bytes:
                                raise MaxApiError("Файл слишком большой. Максимальный размер — 25 МБ.")
                            f.write(chunk)
            return Path(destination)
        except MaxApiError:
            Path(destination).unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError, ValueError) as e:
            Path(destination).unlink(missing_ok=True)
            log.exception("Attachment download failed")
            raise MaxApiError("Не удалось скачать вложение из MAX.") from e

    async def close(self): await self.client.aclose()
