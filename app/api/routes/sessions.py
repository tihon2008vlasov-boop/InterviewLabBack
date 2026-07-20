from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.security import get_current_user_id
from app.models.candidate import ActivityEvent, Candidate, ReplayEvent
from app.models.session import Session
from app.models.test import Test
from app.models.user import User
from app.schemas.session import (
    LiveSessionOut,
    SessionEventsIn,
    SessionStartIn,
    SessionStartOut,
    SessionSubmitIn,
    SessionTaskOut,
)
from app.services.candidate_analysis import analyze_candidate_solution

router = APIRouter(prefix="/sessions", tags=["sessions"])


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def get_session_or_404(session_id: str) -> Session:
    session = await Session.get(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    return session


@router.get("/")
async def list_live_sessions(
    user_id: str = Depends(get_current_user_id),
) -> list[LiveSessionOut]:
    user = await User.get(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    active_after = now() - timedelta(seconds=45)
    sessions = (
        await Session.find(
            Session.company_id == user.company_id,
            Session.ended_at == None,  # noqa: E711
            Session.last_seen_at >= active_after,
        ).sort(-Session.started_at).to_list()
    )
    result: list[LiveSessionOut] = []
    for session in sessions:
        candidate = await Candidate.get(session.candidate_id)
        test = await Test.get(session.test_id)
        if candidate is None or test is None or candidate.status != "in_progress":
            continue
        started = as_utc(session.started_at)
        result.append(
            LiveSessionOut(
                id=str(session.id),
                candidate_name=candidate.name,
                candidate_email=candidate.email,
                position=candidate.position,
                test_id=str(test.id),
                test_name=test.name,
                language=test.language,
                started_at=started,
                elapsed_sec=max(0, int((now() - started).total_seconds())),
                total_sec=test.duration_min * 60,
                progress_pct=session.progress_pct,
                stage=session.stage,
                current_task=session.current_task,
                current_action=session.current_action,
                tab_switches=session.tab_switches,
                camera_on=session.camera_on,
            )
        )
    return result


@router.post("/{code}/start", response_model=SessionStartOut, status_code=status.HTTP_201_CREATED)
async def start_session(code: str, payload: SessionStartIn) -> SessionStartOut:
    test = await Test.find_one({"links.code": code})
    if test is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid invite link")

    link = next(l for l in test.links if l.code == code)
    if not link.active:
        raise HTTPException(status.HTTP_410_GONE, "This invite link has been disabled")
    if link.expires_at and as_utc(link.expires_at) < now():
        raise HTTPException(status.HTTP_410_GONE, "This invite link has expired")
    if link.max_uses is not None and link.uses >= link.max_uses:
        raise HTTPException(status.HTTP_410_GONE, "This invite link has reached its usage limit")

    link.uses += 1
    await test.save()

    candidate = await Candidate.insert_one(
        Candidate(
            company_id=test.company_id,
            test_id=str(test.id),
            name=payload.name,
            email=payload.email,
            position=payload.position,
            status="in_progress",
            activity=[
                ActivityEvent(at=now(), kind="opened", label="Opened the invitation link"),
                ActivityEvent(at=now(), kind="started", label=f"Started the test — {test.name}"),
            ],
        )
    )
    session = await Session.insert_one(
        Session(
            company_id=test.company_id,
            test_id=str(test.id),
            candidate_id=str(candidate.id),
            stage="hardware_check",
            current_action="Verifying camera and microphone",
            last_seen_at=now(),
        )
    )
    return SessionStartOut(
        session_id=str(session.id),
        candidate_id=str(candidate.id),
        test_id=str(test.id),
        test_name=test.name,
        duration_min=test.duration_min,
        language=test.language,
        tasks=test.tasks,
    )


@router.post("/{session_id}/events")
async def ingest_events(session_id: str, payload: SessionEventsIn) -> dict:
    session = await get_session_or_404(session_id)
    if session.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is already finished")

    for field in ("stage", "current_task", "current_action", "progress_pct", "camera_on", "tab_switches"):
        value = getattr(payload, field)
        if value is not None:
            setattr(session, field, value)
    session.last_seen_at = now()
    await session.save()

    if payload.replay_events:
        candidate = await Candidate.get(session.candidate_id)
        if candidate:
            candidate.replay.extend(ReplayEvent(**e.model_dump()) for e in payload.replay_events)
            await candidate.save()

    return {"ok": True}


@router.post("/{session_id}/submit")
async def submit_session(
    session_id: str, payload: SessionSubmitIn, background_tasks: BackgroundTasks
) -> dict:
    session = await get_session_or_404(session_id)
    if session.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is already finished")

    session.stage = "finished"
    session.ended_at = now()
    session.progress_pct = 100
    session.current_action = "Submitted"
    session.last_seen_at = now()
    await session.save()

    candidate = await Candidate.get(session.candidate_id)
    if candidate:
        candidate.status = "completed"
        if candidate.score is None:
            candidate.analysis_status = "pending"
        candidate.completed_at = now()
        candidate.submitted_files = payload.files
        candidate.replay.extend(ReplayEvent(**event.model_dump()) for event in payload.replay_events)
        candidate.duration_sec = payload.duration_sec or max(
            0, int((now() - as_utc(session.started_at)).total_seconds())
        )
        candidate.activity.append(
            ActivityEvent(at=now(), kind="submitted", label="Submitted the test")
        )
        await candidate.save()
        if candidate.score is None:
            background_tasks.add_task(
                analyze_candidate_solution,
                str(candidate.id),
                session.test_id,
            )

    return {"ok": True, "message": "Submission received, AI analysis will start shortly"}
