import asyncio
from datetime import datetime, timezone

from app.core.db import init_db
from app.models.candidate import Candidate, ProctorIncident
from app.models.session import Session


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def add_timecodes(events: list[ProctorIncident], origin: datetime) -> int:
    changed = 0
    origin = as_utc(origin)
    for event in events:
        if event.at_sec is not None:
            continue
        event.at_sec = max(0, int((as_utc(event.at) - origin).total_seconds()))
        changed += 1
    return changed


async def main() -> None:
    await init_db()
    changed_candidates = 0
    changed_sessions = 0
    changed_events = 0

    sessions = await Session.find_all().to_list()
    for session in sessions:
        origin = session.recording_started_at or session.started_at
        session_changes = add_timecodes(session.proctor_events, origin)
        if session_changes:
            await session.save()
            changed_sessions += 1
            changed_events += session_changes

        candidate = await Candidate.get(session.candidate_id)
        if candidate is None:
            continue
        candidate_changes = add_timecodes(candidate.integrity.proctor_events, origin)
        if candidate_changes:
            await candidate.save()
            changed_candidates += 1

    print(
        "[proctoring] "
        f"sessions={changed_sessions}, candidates={changed_candidates}, events={changed_events}"
    )


if __name__ == "__main__":
    asyncio.run(main())
