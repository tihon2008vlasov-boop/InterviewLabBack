import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.db import init_db
from app.services.recordings import purge_expired_recordings


async def recording_cleanup_loop() -> None:
    while True:
        try:
            removed = await purge_expired_recordings()
            if removed:
                print(f"[recordings] removed {removed} expired recording(s)")
        except Exception as err:
            print(f"[recordings] cleanup failed: {err}")
        await asyncio.sleep(60 * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database_ready = False
    try:
        await init_db()
        database_ready = True
    except Exception as err:
        print(
            "[db] ERROR: cannot connect to MongoDB "
            f"({settings.mongodb_uri}): {err}\n"
            "[db] Install and start MongoDB Community Server "
            "(winget install MongoDB.Server), then restart the API."
        )
    cleanup_task = asyncio.create_task(recording_cleanup_loop()) if database_ready else None
    yield
    if cleanup_task is not None:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


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
