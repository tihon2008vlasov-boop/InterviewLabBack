from collections import Counter
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends

from app.core.security import get_current_user_id
from app.models.candidate import Candidate
from app.models.invitation import Invitation
from app.models.session import Session
from app.models.test import Test

router = APIRouter(
    prefix="/analytics", tags=["analytics"], dependencies=[Depends(get_current_user_id)]
)

LANGUAGE_LABELS = {
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    "node": "Node.js",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python": "Python",
    "java": "Java",
    "go": "Go",
    "csharp": "C#",
    "php": "PHP",
}


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("/dashboard")
async def dashboard_stats() -> dict:
    now = datetime.now(timezone.utc)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    week_ago = now - timedelta(days=7)

    active_tests = await Test.find(Test.status == "active").count()
    in_progress_now = await Session.find(Session.ended_at == None).count()  # noqa: E711
    completed_today = await Candidate.find(Candidate.completed_at >= start_of_day).count()

    recent_scored = await Candidate.find(
        Candidate.completed_at >= week_ago, Candidate.score != None  # noqa: E711
    ).to_list()
    avg_score_week = (
        round(sum(c.score or 0 for c in recent_scored) / len(recent_scored))
        if recent_scored
        else 0
    )

    return {
        "active_tests": active_tests,
        "in_progress_now": in_progress_now,
        "completed_today": completed_today,
        "avg_score_week": avg_score_week,
    }


@router.get("/overview")
async def analytics_overview() -> dict:
    now = datetime.now(timezone.utc)
    candidates = await Candidate.find_all().to_list()
    tests = await Test.find_all().to_list()
    invitations_count = await Invitation.count()

    completed = [c for c in candidates if c.completed_at]
    scored = [c for c in completed if c.score is not None]
    passed = [c for c in scored if (c.score or 0) >= 60]
    durations = [c.duration_sec for c in completed if c.duration_sec]

    avg_score = round(sum(c.score or 0 for c in scored) / len(scored)) if scored else 0
    success_rate = round(len(passed) / len(completed) * 100) if completed else 0
    avg_duration_min = round(sum(durations) / len(durations) / 60) if durations else 0
    ai_recommended = sum(1 for c in candidates if c.ai_recommendation in ("strong_hire", "hire"))
    rejections = sum(1 for c in candidates if c.status == "rejected")
    hired = sum(1 for c in candidates if c.status == "hired")

    trend = []
    for offset in range(13, -1, -1):
        day = (now - timedelta(days=offset)).date()
        label = day.strftime("%d.%m")
        invited = sum(1 for c in candidates if (d := as_utc(c.invited_at)) and d.date() == day)
        done = sum(1 for c in candidates if (d := as_utc(c.completed_at)) and d.date() == day)
        trend.append({"label": label, "invited": invited, "completed": done})

    buckets = [("0–20", 0, 20), ("21–40", 21, 40), ("41–60", 41, 60), ("61–80", 61, 80), ("81–100", 81, 100)]
    distribution = [
        {"label": label, "count": sum(1 for c in scored if lo <= (c.score or 0) <= hi)}
        for label, lo, hi in buckets
    ]

    top_tests = []
    for test in tests:
        test_candidates = [c for c in scored if c.test_id == str(test.id)]
        if not test_candidates:
            continue
        t_passed = [c for c in test_candidates if (c.score or 0) >= 60]
        top_tests.append(
            {
                "id": str(test.id),
                "name": test.name,
                "avg_score": round(sum(c.score or 0 for c in test_candidates) / len(test_candidates)),
                "completions": len(test_candidates),
                "pass_rate": round(len(t_passed) / len(test_candidates) * 100),
            }
        )
    top_tests.sort(key=lambda t: t["avg_score"], reverse=True)

    language_by_test = {str(t.id): t.language for t in tests}
    lang_counter = Counter(
        LANGUAGE_LABELS.get(language_by_test.get(c.test_id, ""), "Другое") for c in completed
    )

    started = sum(1 for c in candidates if c.status != "invited")

    return {
        "avg_score": avg_score,
        "success_rate": success_rate,
        "avg_duration_min": avg_duration_min,
        "invites_sent": invitations_count + len(candidates),
        "rejections": rejections,
        "ai_recommended": ai_recommended,
        "completion_trend": trend,
        "score_distribution": distribution,
        "top_tests": top_tests[:5],
        "funnel": [
            {"stage": "Приглашены", "value": invitations_count + len(candidates)},
            {"stage": "Открыли ссылку", "value": started},
            {"stage": "Начали тест", "value": started},
            {"stage": "Завершили", "value": len(completed)},
            {"stage": "Рекомендованы AI", "value": ai_recommended},
            {"stage": "Наняты", "value": hired},
        ],
        "languages": [{"name": name, "value": value} for name, value in lang_counter.most_common()],
    }


@router.get("/recent-invitations")
async def recent_invitations() -> list[dict]:
    invitations = await Invitation.find_all().sort(-Invitation.sent_at).limit(8).to_list()
    tests = {str(t.id): t.name for t in await Test.find_all().to_list()}
    return [
        {
            "id": str(i.id),
            "email": i.email,
            "test_id": i.test_id,
            "test_name": tests.get(i.test_id, "—"),
            "sent_at": i.sent_at.isoformat(),
            "status": i.status,
        }
        for i in invitations
    ]


@router.get("/notifications")
async def notifications() -> list[dict]:
    items: list[dict] = []
    tests = {str(t.id): t.name for t in await Test.find_all().to_list()}

    recent_completed = (
        await Candidate.find(Candidate.completed_at != None)  # noqa: E711
        .sort(-Candidate.completed_at)
        .limit(4)
        .to_list()
    )
    for c in recent_completed:
        score_part = f" Балл: {c.score}." if c.score is not None else ""
        items.append(
            {
                "id": f"done-{c.id}",
                "at": (as_utc(c.completed_at) or datetime.now(timezone.utc)).isoformat(),
                "kind": "candidate",
                "title": "Кандидат завершил тест",
                "message": f"{c.name} — {tests.get(c.test_id, '—')}.{score_part}",
            }
        )

    live = await Session.find(Session.ended_at == None).sort(-Session.started_at).limit(3).to_list()  # noqa: E711
    for s in live:
        candidate = await Candidate.get(s.candidate_id)
        if candidate:
            items.append(
                {
                    "id": f"live-{s.id}",
                    "at": (as_utc(s.started_at) or datetime.now(timezone.utc)).isoformat(),
                    "kind": "system",
                    "title": "Кандидат проходит тест",
                    "message": f"{candidate.name} — {tests.get(s.test_id, '—')}. Сейчас: {s.current_action or s.stage}.",
                }
            )

    recent_invites = await Invitation.find_all().sort(-Invitation.sent_at).limit(3).to_list()
    for i in recent_invites:
        items.append(
            {
                "id": f"inv-{i.id}",
                "at": (as_utc(i.sent_at) or datetime.now(timezone.utc)).isoformat(),
                "kind": "test",
                "title": "Приглашение отправлено",
                "message": f"{i.email} — {tests.get(i.test_id, '—')}.",
            }
        )

    items.sort(key=lambda x: x["at"], reverse=True)
    return items[:8]
