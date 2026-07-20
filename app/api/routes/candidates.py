from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.lookup import get_or_none
from app.core.security import get_current_user_id
from app.core.tenant import current_company_id
from app.models.candidate import ActivityEvent, Candidate, CandidateStatus
from app.models.company import Company
from app.models.session import Session
from app.models.test import Test
from app.models.user import User
from app.services.candidate_analysis import analyze_candidate_solution
from app.services.emailer import build_decision_email, send_email

router = APIRouter(
    prefix="/candidates", tags=["candidates"], dependencies=[Depends(get_current_user_id)]
)


class StatusIn(BaseModel):
    status: CandidateStatus


async def get_candidate_or_404(candidate_id: str, company_id: str | None = None) -> Candidate:
    candidate = await get_or_none(Candidate, candidate_id)
    # Чужого кандидата не отличаем от несуществующего.
    if candidate is None or (company_id is not None and candidate.company_id != company_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return candidate


async def candidate_out(candidate: Candidate, include_recording: bool = False) -> dict:
    test = await get_or_none(Test, candidate.test_id)
    data = candidate.model_dump(mode="json", by_alias=True)
    data["_id"] = str(candidate.id)
    data["test_name"] = test.name if test else "Удалённый тест"
    data["level"] = test.level if test else "middle"
    data["language"] = test.language if test else "javascript"
    if include_recording:
        session = await (
            Session.find(Session.candidate_id == str(candidate.id))
            .sort(-Session.started_at)
            .first_or_none()
        )
        recording_ready = bool(
            session
            and session.recording_status == "ready"
            and session.recording_path
            and (
                session.recording_expires_at is None
                or (
                    session.recording_expires_at
                    if session.recording_expires_at.tzinfo
                    else session.recording_expires_at.replace(tzinfo=timezone.utc)
                ) > datetime.now(timezone.utc)
            )
        )
        data["recording"] = {
            "available": recording_ready,
            "status": session.recording_status if session else "none",
            "session_id": str(session.id) if session else "",
            "mime_type": session.recording_mime_type if session else "",
            "size_bytes": session.recording_size_bytes if session else 0,
            "duration_sec": session.recording_duration_sec if session else 0,
            "started_at": session.recording_started_at.isoformat() if session and session.recording_started_at else None,
            "completed_at": session.recording_completed_at.isoformat() if session and session.recording_completed_at else None,
            "expires_at": session.recording_expires_at.isoformat() if session and session.recording_expires_at else None,
        }
    return data


@router.get("/")
async def list_candidates(
    status_filter: str | None = None,
    search: str | None = None,
    company_id: str = Depends(current_company_id),
) -> list[dict]:
    query: dict = {"company_id": company_id}
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
async def get_candidate(candidate_id: str, company_id: str = Depends(current_company_id)) -> dict:
    return await candidate_out(
        await get_candidate_or_404(candidate_id, company_id),
        include_recording=True,
    )


@router.patch("/{candidate_id}/status")
async def update_status(
    candidate_id: str, payload: StatusIn, company_id: str = Depends(current_company_id)
) -> dict:
    candidate = await get_candidate_or_404(candidate_id, company_id)
    candidate.status = payload.status
    await candidate.save()
    return await candidate_out(candidate)


@router.post("/{candidate_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
async def analyze_candidate(
    candidate_id: str,
    background_tasks: BackgroundTasks,
    company_id: str = Depends(current_company_id),
) -> dict:
    candidate = await get_candidate_or_404(candidate_id, company_id)
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
    subject: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=5000)
    # Для приглашения на собеседование
    meeting_url: str = Field(default="", max_length=500)
    meeting_at: str = Field(default="", max_length=200)
    # Для письма о найме
    contact_name: str = Field(default="", max_length=200)
    contact_details: str = Field(default="", max_length=1000)


@router.post("/{candidate_id}/send-results")
async def send_candidate_results(
    candidate_id: str,
    payload: SendResultsIn,
    user_id: str = Depends(get_current_user_id),
) -> dict:
    candidate = await get_candidate_or_404(candidate_id)
    user = await get_or_none(User, user_id)
    if user is None or candidate.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    if not candidate.completed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "Кандидат ещё не завершил тест")

    test = await get_or_none(Test, candidate.test_id)
    company = await get_or_none(Company, user.company_id)
    company_name = company.name if company else "InterviewLab"
    test_name = test.name if test else "Технический тест"
    subject, html = build_decision_email(
        candidate.name,
        test_name,
        candidate.duration_sec,
        candidate.score,
        payload.decision,
        company_name,
        payload.subject,
        payload.message,
        payload.meeting_url,
        payload.meeting_at,
        payload.contact_name,
        payload.contact_details,
    )
    await send_email(
        candidate.email,
        f"{subject} — {company_name}",
        html,
        from_name=company_name,
        reply_to=str(user.email),
    )

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
            detail=f"{candidate.email} · {subject}",
        )
    )
    await candidate.save()
    return {"ok": True, "message": f"Письмо отправлено на {candidate.email}"}
