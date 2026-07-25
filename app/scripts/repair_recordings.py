import asyncio

from app.core.db import init_db
from app.models.session import Session
from app.services.recordings import recording_file, repair_recording


async def main() -> None:
    await init_db()
    sessions = await Session.find(Session.recording_status == "ready").to_list()
    repaired = 0
    missing = 0
    failed = 0
    for session in sessions:
        path = recording_file(session)
        if not path.is_file():
            missing += 1
            continue
        if await repair_recording(path):
            session.recording_size_bytes = path.stat().st_size
            await session.save()
            repaired += 1
        else:
            failed += 1
    print(f"[recordings] repaired={repaired}, missing={missing}, failed={failed}")


if __name__ == "__main__":
    asyncio.run(main())
