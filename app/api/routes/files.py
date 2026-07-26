"""Отдача аватаров и логотипов из GridFS."""

from fastapi import APIRouter, Response

from app.services.images import open_image

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
async def get_file(file_id: str) -> Response:
    """Картинки отдаются без Authorization: тег <img> его слать не умеет.

    Защита — неугадываемый идентификатор файла. Секретов тут нет: логотип
    компании и фото сотрудника видны всем, кому показали интерфейс.
    """
    stream = await open_image(file_id)
    try:
        data = await stream.read()
        media_type = (stream.metadata or {}).get("contentType", "application/octet-stream")
    finally:
        await stream.close()
    return Response(
        content=data,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
