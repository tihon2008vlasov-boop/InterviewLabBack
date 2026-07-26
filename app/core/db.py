from beanie import init_beanie
from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import settings
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.invitation import Invitation
from app.models.session import Session
from app.models.task_template import TaskTemplate
from app.models.test import Test
from app.models.user import User


_database: AsyncDatabase | None = None


async def init_db() -> None:
    global _database
    client: AsyncMongoClient = AsyncMongoClient(
        settings.mongodb_uri, serverSelectionTimeoutMS=3000
    )
    _database = client[settings.mongodb_db]
    await init_beanie(
        database=_database,
        document_models=[User, Company, Test, TaskTemplate, Candidate, Session, Invitation],
    )
    print(f"[db] connected to MongoDB, database '{settings.mongodb_db}'")


def get_database() -> AsyncDatabase:
    """База для операций мимо Beanie — сейчас это только GridFS с картинками."""
    if _database is None:
        raise RuntimeError("Database is not initialised: init_db() has not run")
    return _database
