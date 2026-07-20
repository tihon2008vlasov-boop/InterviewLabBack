import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.lookup import get_or_none
from app.core.security import bearer_scheme, decode_access_token, get_current_user_id
from app.models.candidate import ActivityEvent, Candidate, ProctorIncident
from app.models.session import Session
from app.models.user import User
from app.services.proctoring import proctoring_hub
from app.services.recordings import combine_chunks, recording_file, reset_recording_files, save_chunk

router = APIRouter(prefix="/proctoring", tags=["proctoring"])


EVENT_META: dict[str, tuple[str, str, int]] = {
    "proctoring_started": ("info", "Прокторинг запущен", 0),
    "vision_limited": ("info", "Ограниченный режим видеоанализа", 0),
    "face_verified": ("info", "Лицо кандидата подтверждено", 0),
    "face_missing": ("warning", "Лицо не видно в кадре", 8),
    "looking_away": ("warning", "Кандидат долго смотрит в сторону", 4),
    "multiple_people": ("critical", "В кадре обнаружено несколько людей", 20),
    "phone_detected": ("critical", "В кадре обнаружен телефон", 24),
    "identity_mismatch": ("critical", "Лицо отличается от лица при старте", 28),
    "camera_stopped": ("critical", "Камера отключена", 20),
    "screen_share_stopped": ("critical", "Демонстрация экрана остановлена", 24),
    "tab_hidden": ("warning", "Кандидат покинул вкладку теста", 5),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def candidate_recording_session(
    session_id: str,
    candidate_token: str,
    allow_finished: bool = False,
) -> Session:
    session = await get_or_none(Session, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    if not session.proctor_token or not secrets.compare_digest(candidate_token, session.proctor_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid candidate token")
    if not allow_finished and session.ended_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Session is already finished")
    return session


class RecordingCompleteIn(BaseModel):
    last_sequence: int = Field(ge=0, le=1_000_000)
    duration_sec: int = Field(ge=0, le=86_400)
    mime_type: str = Field(default="video/webm", max_length=120)


@router.post("/recordings/{session_id}/start")
async def start_recording(
    session_id: str,
    candidate_token: str = Header(alias="X-Candidate-Token"),
) -> dict:
    session = await candidate_recording_session(session_id, candidate_token)
    if session.recording_status == "ready":
        return {"ok": True, "status": "ready"}
    if session.recording_status != "recording":
        await reset_recording_files(session_id)
        session.recording_status = "recording"
        session.recording_path = ""
        session.recording_mime_type = ""
        session.recording_size_bytes = 0
        session.recording_duration_sec = 0
        session.recording_started_at = now()
        session.recording_completed_at = None
        session.recording_expires_at = None
        await session.save()
    return {
        "ok": True,
        "status": session.recording_status,
        "max_chunk_bytes": settings.recording_max_chunk_bytes,
    }


@router.post("/recordings/{session_id}/chunks")
async def upload_recording_chunk(
    session_id: str,
    sequence: int = Form(ge=0, le=1_000_000),
    chunk: UploadFile = File(),
    candidate_token: str = Header(alias="X-Candidate-Token"),
) -> dict:
    session = await candidate_recording_session(session_id, candidate_token)
    if session.recording_status != "recording":
        raise HTTPException(status.HTTP_409_CONFLICT, "Recording has not been started")
    data = await chunk.read(settings.recording_max_chunk_bytes + 1)
    await chunk.close()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Recording chunk is empty")
    if len(data) > settings.recording_max_chunk_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Recording chunk is too large")
    total_size = await save_chunk(session_id, sequence, data)
    if total_size > settings.recording_max_bytes:
        session.recording_status = "failed"
        await session.save()
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Recording size limit exceeded")
    session.recording_size_bytes = total_size
    session.last_seen_at = now()
    await session.save()
    return {"ok": True, "sequence": sequence, "received_bytes": len(data)}


@router.post("/recordings/{session_id}/complete")
async def complete_recording(
    session_id: str,
    payload: RecordingCompleteIn,
    candidate_token: str = Header(alias="X-Candidate-Token"),
) -> dict:
    session = await candidate_recording_session(session_id, candidate_token, allow_finished=True)
    if session.recording_status == "ready":
        return {"ok": True, "status": "ready", "size_bytes": session.recording_size_bytes}
    if session.recording_status != "recording":
        raise HTTPException(status.HTTP_409_CONFLICT, "Recording has not been started")
    normalized_mime = payload.mime_type.split(";", 1)[0].strip().lower()
    extension = "mp4" if normalized_mime == "video/mp4" else "webm"
    relative_path, size = await combine_chunks(session_id, payload.last_sequence, extension)
    session.recording_status = "ready"
    session.recording_path = relative_path
    session.recording_mime_type = normalized_mime or f"video/{extension}"
    session.recording_size_bytes = size
    session.recording_duration_sec = payload.duration_sec
    session.recording_completed_at = now()
    session.recording_expires_at = now() + timedelta(days=settings.recording_retention_days)
    await session.save()
    return {"ok": True, "status": "ready", "size_bytes": size}


@router.get("/recordings/{session_id}/media")
async def stream_recording(
    session_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    recording_access: str | None = Cookie(default=None, alias="proctor_recording_access"),
) -> FileResponse:
    session = await get_or_none(Session, session_id)
    user_id = ""
    if credentials is not None:
        try:
            user_id = str(decode_access_token(credentials.credentials)["sub"])
        except (JWTError, KeyError, TypeError):
            pass
    elif recording_access:
        try:
            payload = jwt.decode(
                recording_access,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
            if payload.get("purpose") == "recording_playback" and payload.get("session_id") == session_id:
                user_id = str(payload["sub"])
        except (JWTError, KeyError, TypeError):
            pass
    user = await get_or_none(User, user_id) if user_id else None
    if session is None or user is None or session.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    if session.recording_status != "ready" or not session.recording_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    if session.recording_expires_at and as_utc(session.recording_expires_at) <= now():
        raise HTTPException(status.HTTP_410_GONE, "Recording retention period has expired")
    path = recording_file(session)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording file not found")
    return FileResponse(
        path,
        media_type=session.recording_mime_type or "video/webm",
        filename=f"proctoring-{session_id}.{path.suffix.lstrip('.')}",
        content_disposition_type="inline",
    )


@router.post("/recordings/{session_id}/playback-access")
async def create_playback_access(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
) -> JSONResponse:
    session = await get_or_none(Session, session_id)
    user = await get_or_none(User, user_id)
    if session is None or user is None or session.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    if session.recording_status != "ready" or not session.recording_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    expires = now() + timedelta(minutes=10)
    playback_token = jwt.encode(
        {
            "sub": user_id,
            "session_id": session_id,
            "purpose": "recording_playback",
            "exp": expires,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = JSONResponse({"ok": True, "expires_at": expires.isoformat()})
    response.set_cookie(
        key="proctor_recording_access",
        value=playback_token,
        max_age=600,
        httponly=True,
        secure=settings.env == "production",
        samesite="none" if settings.env == "production" else "lax",
        path=f"/api/proctoring/recordings/{session_id}/media",
    )
    return response


async def save_media_state(session_id: str, camera_on: bool, screen_on: bool) -> None:
    session = await get_or_none(Session, session_id)
    if session is None:
        return
    session.camera_on = camera_on
    session.screen_on = screen_on
    session.last_seen_at = now()
    await session.save()


async def record_incident(session_id: str, raw: dict[str, Any]) -> ProctorIncident | None:
    session = await get_or_none(Session, session_id)
    if session is None or session.ended_at is not None:
        return None

    kind = str(raw.get("kind", ""))[:64]
    meta = EVENT_META.get(kind)
    if meta is None:
        return None
    severity, label, weight = meta
    try:
        confidence = max(0, min(100, int(raw.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0
    detail_raw = raw.get("detail")
    detail = str(detail_raw)[:500] if detail_raw else None
    incident = ProctorIncident(
        at=now(),
        kind=kind,
        severity=severity,
        label=label,
        detail=detail,
        confidence=confidence,
    )
    session.proctor_events = [*session.proctor_events[-249:], incident]
    session.proctor_risk_score = min(100, session.proctor_risk_score + weight)
    if kind == "camera_stopped":
        session.camera_on = False
    elif kind == "screen_share_stopped":
        session.screen_on = False
    session.last_seen_at = now()
    await session.save()

    candidate = await get_or_none(Candidate, session.candidate_id)
    if candidate is not None:
        integrity = candidate.integrity
        integrity.proctor_risk_score = session.proctor_risk_score
        integrity.proctor_events = [*integrity.proctor_events[-249:], incident]
        if kind == "phone_detected":
            integrity.phone_detections += 1
        elif kind == "multiple_people":
            integrity.multiple_people += 1
        elif kind == "face_missing":
            integrity.face_absence_events += 1
        elif kind == "identity_mismatch":
            integrity.identity_mismatches += 1
        elif kind == "screen_share_stopped":
            integrity.screen_share_interruptions += 1
        if severity != "info":
            candidate.activity = [
                *candidate.activity[-499:],
                ActivityEvent(
                    at=incident.at,
                    kind="warning",
                    label=label,
                    detail=detail,
                ),
            ]
        await candidate.save()
    return incident


async def authenticate(
    session: Session,
    role: str,
    token: str,
) -> tuple[bool, str, str]:
    if role == "candidate":
        valid = bool(session.proctor_token) and secrets.compare_digest(token, session.proctor_token)
        return valid, "candidate", session.candidate_id
    if role != "viewer":
        return False, "", ""
    try:
        payload = decode_access_token(token)
        user_id = str(payload["sub"])
    except (JWTError, KeyError, TypeError):
        return False, "", ""
    user = await get_or_none(User, user_id)
    if user is None or user.company_id != session.company_id:
        return False, "", ""
    return True, user.name, user_id


@router.websocket("/ws/{session_id}")
async def proctoring_socket(
    websocket: WebSocket,
    session_id: str,
) -> None:
    session = await get_or_none(Session, session_id)
    if session is None or session.ended_at is not None:
        await websocket.close(code=4404, reason="Session not found")
        return
    await websocket.accept()
    try:
        auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except (TimeoutError, WebSocketDisconnect, ValueError):
        try:
            await websocket.close(code=4401, reason="Authentication required")
        except RuntimeError:
            pass
        return
    if auth_message.get("type") != "authenticate":
        await websocket.close(code=4401, reason="Authentication required")
        return
    role = str(auth_message.get("role", ""))
    token = str(auth_message.get("token", ""))
    allowed, display_name, principal_id = await authenticate(session, role, token)
    if not allowed:
        await websocket.close(code=4401, reason="Unauthorized")
        return

    connection_id = str(uuid4())
    if role == "candidate":
        await proctoring_hub.connect_candidate(session_id, websocket)
        session.proctoring_enabled = True
        session.last_seen_at = now()
        await session.save()
    else:
        await proctoring_hub.connect_viewer(
            session_id,
            connection_id,
            websocket,
            display_name,
            principal_id,
        )

    await websocket.send_json(
        {
            "type": "ready",
            "connection_id": connection_id,
            "candidate_online": proctoring_hub.candidate_online(session_id),
            "countdown_sec": 3,
        }
    )

    try:
        while True:
            message = await websocket.receive_json()
            message_type = str(message.get("type", ""))

            if role == "candidate":
                if message_type == "proctor_event" and isinstance(message.get("event"), dict):
                    incident = await record_incident(session_id, message["event"])
                    if incident is not None:
                        await proctoring_hub.broadcast_viewers(
                            session_id,
                            {
                                "type": "proctor_event",
                                "event": incident.model_dump(mode="json"),
                            },
                        )
                elif message_type == "media_state":
                    camera_on = bool(message.get("camera_on"))
                    screen_on = bool(message.get("screen_on"))
                    await save_media_state(session_id, camera_on, screen_on)
                    await proctoring_hub.broadcast_viewers(
                        session_id,
                        {
                            "type": "media_state",
                            "camera_on": camera_on,
                            "screen_on": screen_on,
                        },
                    )
                elif message_type in {"offer", "ice_candidate"}:
                    target_id = str(message.get("target_id", ""))
                    if target_id and proctoring_hub.can_receive_media(session_id, target_id):
                        await proctoring_hub.send_viewer(
                            session_id,
                            target_id,
                            {**message, "viewer_id": target_id},
                        )
                continue

            if message_type == "watch_request":
                proctoring_hub.set_watching(session_id, connection_id, True)
                delivered = await proctoring_hub.send_candidate(
                    session_id,
                    {
                        "type": "watch_request",
                        "viewer_id": connection_id,
                        "viewer_name": display_name,
                        "countdown_sec": 3,
                    },
                )
                if not delivered:
                    proctoring_hub.set_watching(session_id, connection_id, False)
                    await websocket.send_json(
                        {"type": "error", "message": "Candidate is not connected"}
                    )
                else:
                    await websocket.send_json(
                        {"type": "watch_queued", "countdown_sec": 3}
                    )
                    await asyncio.sleep(3)
                    if proctoring_hub.allow_media(session_id, connection_id):
                        await proctoring_hub.send_candidate(
                            session_id,
                            {"type": "watch_authorized", "viewer_id": connection_id},
                        )
            elif message_type in {"answer", "ice_candidate"}:
                await proctoring_hub.send_candidate(
                    session_id,
                    {**message, "viewer_id": connection_id},
                )
            elif message_type == "stop_watching":
                proctoring_hub.set_watching(session_id, connection_id, False)
                await proctoring_hub.send_candidate(
                    session_id,
                    {"type": "viewer_left", "viewer_id": connection_id},
                )
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        if role == "candidate":
            await proctoring_hub.disconnect_candidate(session_id, websocket)
            await save_media_state(session_id, False, False)
        else:
            await proctoring_hub.disconnect_viewer(session_id, connection_id)
