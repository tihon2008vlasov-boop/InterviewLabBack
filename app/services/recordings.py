import asyncio
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status

from app.core.config import settings
from app.models.session import Session


def recordings_root() -> Path:
    root = Path(settings.recordings_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def session_recording_dir(session_id: str) -> Path:
    if not session_id or any(character not in "0123456789abcdefABCDEF" for character in session_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid session id")
    directory = (recordings_root() / session_id).resolve()
    if directory.parent != recordings_root():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid session id")
    return directory


def recording_file(session: Session) -> Path:
    if not session.recording_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    path = (recordings_root() / session.recording_path).resolve()
    if recordings_root() not in path.parents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recording not found")
    return path


async def reset_recording_files(session_id: str) -> None:
    directory = session_recording_dir(session_id)

    def reset() -> None:
        if directory.exists():
            shutil.rmtree(directory)
        (directory / "chunks").mkdir(parents=True, exist_ok=True)

    await asyncio.to_thread(reset)


async def delete_recording_files(session_id: str) -> None:
    directory = session_recording_dir(session_id)
    await asyncio.to_thread(shutil.rmtree, directory, True)


async def purge_expired_recordings() -> int:
    expired = await Session.find(
        Session.recording_status == "ready",
        Session.recording_expires_at <= datetime.now(timezone.utc),
    ).to_list()
    for session in expired:
        await delete_recording_files(str(session.id))
        session.recording_status = "none"
        session.recording_path = ""
        session.recording_mime_type = ""
        session.recording_size_bytes = 0
        await session.save()
    return len(expired)


async def save_chunk(session_id: str, sequence: int, data: bytes) -> int:
    directory = session_recording_dir(session_id)
    chunks_dir = directory / "chunks"
    chunk_path = chunks_dir / f"{sequence:08d}.part"

    def write() -> int:
        chunks_dir.mkdir(parents=True, exist_ok=True)
        temporary = chunk_path.with_suffix(".tmp")
        temporary.write_bytes(data)
        temporary.replace(chunk_path)
        return sum(path.stat().st_size for path in chunks_dir.glob("*.part"))

    return await asyncio.to_thread(write)


async def combine_chunks(
    session_id: str,
    last_sequence: int,
    extension: str,
) -> tuple[str, int]:
    directory = session_recording_dir(session_id)
    chunks_dir = directory / "chunks"
    final_path = directory / f"recording.{extension}"

    def combine() -> int:
        expected = [chunks_dir / f"{sequence:08d}.part" for sequence in range(last_sequence + 1)]
        missing = [path.name for path in expected if not path.is_file()]
        if missing:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Recording is incomplete: {len(missing)} chunk(s) missing",
            )
        temporary = final_path.with_suffix(f".{extension}.tmp")
        with temporary.open("wb") as output:
            for chunk in expected:
                with chunk.open("rb") as source:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
        temporary.replace(final_path)
        size = final_path.stat().st_size
        shutil.rmtree(chunks_dir, ignore_errors=True)
        return size

    size = await asyncio.to_thread(combine)
    relative_path = final_path.relative_to(recordings_root()).as_posix()
    return relative_path, size
