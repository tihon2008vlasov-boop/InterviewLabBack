from fastapi import APIRouter

from app.api.routes import analytics, auth, candidates, sessions, tests

api_router = APIRouter(prefix="/api")

api_router.include_router(auth.router)
api_router.include_router(tests.router)
api_router.include_router(candidates.router)
api_router.include_router(sessions.router)
api_router.include_router(analytics.router)


@api_router.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok"}
