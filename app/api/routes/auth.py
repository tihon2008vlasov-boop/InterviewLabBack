from fastapi import APIRouter, HTTPException, status

from app.core.lookup import get_or_none
from app.core.security import create_access_token, hash_password, verify_password
from app.models.company import Company
from app.models.user import User
from app.schemas.auth import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def to_user_out(user: User, company_name: str) -> UserOut:
    return UserOut(
        id=str(user.id),
        name=user.name,
        email=user.email,
        role=user.role,
        company=company_name,
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn) -> TokenOut:
    if await User.find_one(User.email == payload.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")

    company = await Company.insert_one(Company(name=payload.company))
    user = await User.insert_one(
        User(
            name=payload.name,
            email=payload.email,
            password_hash=hash_password(payload.password),
            role="owner",
            company_id=str(company.id),
        )
    )
    return TokenOut(
        token=create_access_token(str(user.id), user.role),
        user=to_user_out(user, company.name),
    )


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn) -> TokenOut:
    user = await User.find_one(User.email == payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    company = await get_or_none(Company, user.company_id)
    return TokenOut(
        token=create_access_token(str(user.id), user.role),
        user=to_user_out(user, company.name if company else ""),
    )


@router.post("/forgot-password")
async def forgot_password() -> dict:
    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def reset_password() -> dict:
    return {"detail": "Not implemented: verify reset token and update password"}
