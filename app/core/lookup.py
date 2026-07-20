from typing import TypeVar

from beanie import Document
from bson import ObjectId

DocumentT = TypeVar("DocumentT", bound=Document)


async def get_or_none(model: type[DocumentT], raw_id: str | None) -> DocumentT | None:
    """Найти документ по id, не падая на мусоре в URL.

    Beanie бросает исключение, если строка не является валидным ObjectId,
    из-за чего запрос вроде /tests/abc возвращал 500 вместо 404.
    """
    if not raw_id or not ObjectId.is_valid(raw_id):
        return None
    return await model.get(raw_id)
