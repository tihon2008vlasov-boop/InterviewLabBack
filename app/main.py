from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await init_db()
    except Exception as err:
        print(
            "[db] ERROR: cannot connect to MongoDB "
            f"({settings.mongodb_uri}): {err}\n"
            "[db] Install and start MongoDB Community Server "
            "(winget install MongoDB.Server), then restart the API."
        )
    yield


app = FastAPI(
    title="InterviewLab API",
    version="0.1.0",
    description="Backend skeleton for the InterviewLab technical screening platform.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.client_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
