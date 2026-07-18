from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.session import Session
from app.models.test import Test
from app.models.user import User


async def init_db() -> None:
    client = AsyncIOMotorClient(settings.mongodb_uri)
    await init_beanie(
        database=client[settings.mongodb_db],
        document_models=[User, Company, Test, Candidate, Session, Invitation],
    )
