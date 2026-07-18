from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, status

from app.core.security import get_current_user_id
from app.models.candidate import Candidate
from app.models.session import Session
from app.models.test import Test

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user_id)]
)


@router.get("/dashboard")
async def dashboard_stats() -> dict:
    start_of_day = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return {
        "active_tests": await Test.find(Test.status == "active").count(),
        "in_progress_now": await Session.find(Session.ended_at == None).count(),  # noqa: E711
        "completed_today": await Candidate.find(Candidate.completed_at >= start_of_day).count(),
    }


@router.get("/overview", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def analytics_overview() -> dict:
    return {
        "detail": (
            "Not implemented: aggregate avg score, funnel, score distribution "
            "and completion trend from the candidates collection"
        )
    }
