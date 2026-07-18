from beanie import init_beanie
from pymongo import AsyncMongoClient

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.session import Session
from app.models.test import Test
from app.models.user import User


async def init_db() -> None:
    client: AsyncMongoClient = AsyncMongoClient(
        settings.mongodb_uri, serverSelectionTimeoutMS=3000
    )
    await init_beanie(
        database=client[settings.mongodb_db],
        document_models=[User, Company, Test, Candidate, Session, Invitation],
    )
    print(f"[db] connected to MongoDB, database '{settings.mongodb_db}'")
