from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_user_id
from app.models.candidate import ActivityEvent, Candidate, ReplayEvent
from app.models.session import Session
from app.models.test import Test
from app.schemas.session import (
    LiveSessionOut,
    SessionEventsIn,
    SessionStartIn,
    SessionStartOut,
    SessionSubmitIn,
    SessionTaskOut,
)

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


@router.get("/", dependencies=[Depends(get_current_user_id)])
async def list_live_sessions() -> list[LiveSessionOut]:
    sessions = (
        await Session.find(Session.ended_at == None).sort(-Session.started_at).to_list()  # noqa: E711
    )
    result: list[LiveSessionOut] = []
    for session in sessions:
        candidate = await Candidate.get(session.candidate_id)
        test = await Test.get(session.test_id)
        if candidate is None or test is None:
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
        )
    )
    return SessionStartOut(
        session_id=str(session.id),
        candidate_id=str(candidate.id),
        test_id=str(test.id),
        test_name=test.name,
        duration_min=test.duration_min,
        language=test.language,
        tasks=[
            SessionTaskOut(
                id=t.id,
                type=t.type,
                title=t.title,
                description=t.description,
                points=t.points,
                starter_code=t.starter_code,
                readme=t.readme,
                figma_url=t.figma_url,
                image_url=t.image_url,
                attached_files=t.attached_files,
                time_limit_min=t.settings.time_limit_min,
                camera_required=t.settings.camera_required,
                tab_switch_lock=t.settings.tab_switch_lock,
            )
            for t in test.tasks
        ],
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
    await session.save()

    if payload.replay_events:
        candidate = await Candidate.get(session.candidate_id)
        if candidate:
            candidate.replay.extend(ReplayEvent(**e.model_dump()) for e in payload.replay_events)
            await candidate.save()

    return {"ok": True}


@router.post("/{session_id}/submit")
async def submit_session(session_id: str, payload: SessionSubmitIn) -> dict:
    session = await get_session_or_404(session_id)
    if session.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is already finished")

    session.stage = "finished"
    session.ended_at = now()
    session.progress_pct = 100
    session.current_action = "Submitted"
    await session.save()

    candidate = await Candidate.get(session.candidate_id)
    if candidate:
        candidate.status = "completed"
        candidate.completed_at = now()
        candidate.submitted_files = payload.files
        candidate.duration_sec = payload.duration_sec or max(
            0, int((now() - as_utc(session.started_at)).total_seconds())
        )
        candidate.activity.append(
            ActivityEvent(at=now(), kind="submitted", label="Submitted the test")
        )
        await candidate.save()

    return {"ok": True, "message": "Submission received, AI analysis will start shortly"}
