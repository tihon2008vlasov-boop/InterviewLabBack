from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import get_current_user_id
from app.models.candidate import ActivityEvent, Candidate, CandidateStatus
from app.models.test import Test
from app.services.candidate_analysis import analyze_candidate_solution
from app.services.emailer import build_decision_email, send_email

router = APIRouter(
    prefix="/candidates", tags=["candidates"], dependencies=[Depends(get_current_user_id)]
)


class StatusIn(BaseModel):
    status: CandidateStatus


async def get_candidate_or_404(candidate_id: str) -> Candidate:
    candidate = await Candidate.get(candidate_id)
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return candidate


async def candidate_out(candidate: Candidate) -> dict:
    test = await Test.get(candidate.test_id)
    data = candidate.model_dump(mode="json", by_alias=True)
    data["_id"] = str(candidate.id)
    data["test_name"] = test.name if test else "Удалённый тест"
    data["level"] = test.level if test else "middle"
    data["language"] = test.language if test else "javascript"
    return data


@router.get("/")
async def list_candidates(status_filter: str | None = None, search: str | None = None) -> list[dict]:
    query: dict = {}
    if status_filter and status_filter != "all":
        query["status"] = status_filter
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"position": {"$regex": search, "$options": "i"}},
        ]
    candidates = await Candidate.find(query).sort(-Candidate.invited_at).to_list()
    return [await candidate_out(candidate) for candidate in candidates]


@router.get("/{candidate_id}")
async def get_candidate(candidate_id: str) -> dict:
    return await candidate_out(await get_candidate_or_404(candidate_id))


@router.patch("/{candidate_id}/status")
async def update_status(candidate_id: str, payload: StatusIn) -> dict:
    candidate = await get_candidate_or_404(candidate_id)
    candidate.status = payload.status
    await candidate.save()
    return await candidate_out(candidate)


@router.post("/{candidate_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_candidate(candidate_id: str, background_tasks: BackgroundTasks) -> dict:
    candidate = await get_candidate_or_404(candidate_id)
    if candidate.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Candidate has not completed the test")
    if not candidate.submitted_files:
        raise HTTPException(status.HTTP_409_CONFLICT, "Candidate has not submitted a solution")
    if candidate.score is not None or candidate.analysis_status == "completed":
        return {"ok": True, "message": "AI analysis already completed"}
    if candidate.analysis_status == "pending":
        return {"ok": True, "message": "AI analysis is already running"}
    candidate.analysis_status = "pending"
    await candidate.save()
    background_tasks.add_task(
        analyze_candidate_solution,
        str(candidate.id),
        candidate.test_id,
    )
    return {"ok": True, "message": "AI analysis started"}


class SendResultsIn(BaseModel):
    decision: Literal["interview", "hired", "pending"] = "pending"


@router.post("/{candidate_id}/send-results")
async def send_candidate_results(candidate_id: str, payload: SendResultsIn) -> dict:
    candidate = await get_candidate_or_404(candidate_id)
    if not candidate.completed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Кандидат ещё не завершил тест")

    test = await Test.get(candidate.test_id)
    test_name = test.name if test else "Технический тест"
    subject, html = build_decision_email(
        candidate.name, test_name, candidate.duration_sec, candidate.score, payload.decision
    )
    await send_email(candidate.email, f"{subject} — InterviewLab", html)

    if payload.decision == "hired":
        candidate.status = "hired"
    elif payload.decision == "interview" and candidate.status not in ("hired", "rejected"):
        candidate.status = "reviewed"

    labels = {
        "interview": "Отправлено приглашение на собеседование",
        "hired": "Отправлено письмо о найме",
        "pending": "Итоги отправлены кандидату",
    }
    candidate.activity.append(
        ActivityEvent(
            at=datetime.now(timezone.utc),
            kind="analyzed",
            label=labels[payload.decision],
            detail=candidate.email,
        )
    )
    await candidate.save()
    return {"ok": True, "message": f"Письмо отправлено на {candidate.email}"}
