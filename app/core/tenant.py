from fastapi import Depends, HTTPException, status

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id
from app.models.user import User


async def current_company_id(user_id: str = Depends(get_current_user_id)) -> str:
    """Компания текущего пользователя.

    Любая выборка данных должна фильтроваться по ней: пользователь видит
    только тесты, кандидатов и статистику своей компании.
    """
    user = await get_or_none(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user.company_id
