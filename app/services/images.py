"""Аватары пользователей и логотипы компаний в MongoDB через GridFS.

Браузер отдаёт выбранный файл как `data:image/png;base64,...`. Хранить такую
строку прямо в документе User или Company накладно: она раздувает каждый ответ
со списком команды и настройками, и не кэшируется браузером. Поэтому картинка
уезжает в GridFS, а в документе остаётся короткая ссылка `/files/<id>`.

GridFS — это не отдельный сервис, а две обычные коллекции (`images.files` и
`images.chunks`), которые ведёт драйвер: в MongoDB документ не может быть
больше 16 МБ, поэтому файлы хранятся кусками.
"""

import base64
import binascii
import re

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status
from gridfs import AsyncGridFSBucket, AsyncGridOut
from gridfs.errors import NoFile

from app.core.db import get_database

BUCKET = "images"
FILE_URL_PREFIX = "/files/"
MAX_IMAGE_BYTES = 2 * 1024 * 1024

# SVG сознательно не поддерживается: внутрь можно спрятать скрипт.
ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp", "image/gif"}
DATA_URL = re.compile(r"^data:(?P<mime>[\w.+-]+/[\w.+-]+);base64,(?P<payload>.+)$", re.DOTALL)


def _bucket() -> AsyncGridFSBucket:
    return AsyncGridFSBucket(get_database(), bucket_name=BUCKET)


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError, ValueError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None


def _decode(value: str) -> tuple[bytes, str]:
    match = DATA_URL.match(value)
    if match is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Expected a base64 data URL")
    mime = match.group("mime").lower()
    if mime not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unsupported image type '{mime}'. Allowed: PNG, JPEG, WebP, GIF",
        )
    try:
        data = base64.b64decode(match.group("payload"), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Image is not valid base64"
        ) from None
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB",
        )
    return data, mime


async def open_image(file_id: str) -> AsyncGridOut:
    try:
        return await _bucket().open_download_stream(_object_id(file_id))
    except NoFile:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found") from None


async def _drop(reference: str) -> None:
    """Удаляет предыдущую картинку. Старые значения с data URL пропускаем."""
    if not reference.startswith(FILE_URL_PREFIX):
        return
    try:
        await _bucket().delete(_object_id(reference.removeprefix(FILE_URL_PREFIX)))
    except (HTTPException, NoFile):
        return


async def store_image(value: str, previous: str, owner_id: str, kind: str) -> str:
    """Возвращает значение, которое нужно записать в документ.

    `value` — то, что прислал фронт: пустая строка (убрать картинку), новый
    data URL либо уже сохранённая ссылка, вернувшаяся без изменений.
    """
    value = value.strip()

    if value == previous:
        return previous

    if not value:
        await _drop(previous)
        return ""

    if not value.startswith("data:"):
        # Ссылка на уже загруженный файл. Фронт показывает её тегом <img>,
        # поэтому она приходит абсолютной — приводим обратно к относительной.
        # Проверка идёт до разбора data URL: подстрока `/files/` вполне может
        # случайно встретиться внутри base64.
        _, marker, file_id = value.partition(FILE_URL_PREFIX)
        if marker and file_id:
            return f"{FILE_URL_PREFIX}{file_id}"
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Expected a base64 data URL or a previously stored /files/ link",
        )

    data, mime = _decode(value)
    file_id = await _bucket().upload_from_stream(
        f"{kind}-{owner_id}",
        data,
        metadata={"contentType": mime, "kind": kind, "owner_id": owner_id},
    )
    await _drop(previous)
    return f"{FILE_URL_PREFIX}{file_id}"
