import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id, hash_password, verify_password
from app.models.company import Company
from app.models.user import User
from app.schemas.settings import CompanyPatch, NotificationPatch, PasswordChangeIn, ProfilePatch
from app.services.images import store_image

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user_id)],
)


async def get_account(user_id: str) -> tuple[User, Company]:
    user = await get_or_none(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    company = await get_or_none(Company, user.company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return user, company


def settings_out(user: User, company: Company) -> dict:
    return {
        "profile": {
            "name": user.name,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "role": user.role,
        },
        "company": {
            "name": company.name,
            "website": company.website,
            "logo_url": company.logo_url,
            "plan": company.plan,
        },
        "notifications": user.notification_preferences,
        "api_key_prefix": company.api_key_prefix or None,
    }


@router.get("")
async def get_settings(user_id: str = Depends(get_current_user_id)) -> dict:
    user, company = await get_account(user_id)
    return settings_out(user, company)


@router.patch("/profile")
async def update_profile(
    payload: ProfilePatch,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    user, company = await get_account(user_id)
    email = str(payload.email).lower()
    duplicate = await User.find_one(User.email == email)
    if duplicate is not None and str(duplicate.id) != user_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "This email is already in use")
    user.name = payload.name.strip()
    user.email = email
    user.avatar_url = await store_image(payload.avatar_url, user.avatar_url, user_id, "avatar")
    await user.save()
    return settings_out(user, company)


@router.patch("/company")
async def update_company(
    payload: CompanyPatch,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    user, company = await get_account(user_id)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and admins can edit the company")
    company.name = payload.name.strip()
    company.website = payload.website.strip()
    company.logo_url = await store_image(
        payload.logo_url, company.logo_url, str(company.id), "logo"
    )
    await company.save()
    return settings_out(user, company)


@router.patch("/notifications")
async def update_notifications(
    payload: NotificationPatch,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    user, company = await get_account(user_id)
    user.notification_preferences = payload.model_dump()
    await user.save()
    return settings_out(user, company)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: PasswordChangeIn,
    user_id: str = Depends(get_current_user_id),
) -> None:
    user, _ = await get_account(user_id)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "New password must be different")
    user.password_hash = hash_password(payload.new_password)
    await user.save()


@router.post("/api-key")
async def rotate_api_key(user_id: str = Depends(get_current_user_id)) -> dict:
    user, company = await get_account(user_id)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and admins can manage API keys")
    api_key = f"il_live_{secrets.token_urlsafe(32)}"
    company.api_key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
    company.api_key_prefix = api_key[:15]
    await company.save()
    return {"api_key": api_key, "prefix": company.api_key_prefix}


@router.delete("/api-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(user_id: str = Depends(get_current_user_id)) -> None:
    user, company = await get_account(user_id)
    if user.role not in {"owner", "admin"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners and admins can manage API keys")
    company.api_key_hash = ""
    company.api_key_prefix = ""
    await company.save()
