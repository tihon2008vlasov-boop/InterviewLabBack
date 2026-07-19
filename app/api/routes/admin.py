from fastapi import APIRouter, Depends

from app.core.security import get_current_user_id
from app.models.candidate import Candidate
from app.models.company import Company
from app.models.test import Test
from app.models.user import User

router = APIRouter(tags=["admin"], dependencies=[Depends(get_current_user_id)])

PLAN_PRICES = {"free": 0, "pro": 199, "scale": 499, "enterprise": 1990}


@router.get("/team")
async def team(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    current = await User.get(user_id)
    if current is None:
        return []
    members = await User.find(User.company_id == current.company_id).to_list()
    return [
        {
            "id": str(m.id),
            "name": m.name,
            "email": m.email,
            "role": m.role,
            "status": "active",
            "joined_at": m.created_at.isoformat(),
        }
        for m in members
    ]


@router.get("/admin/stats")
async def admin_stats() -> dict:
    companies = await Company.find_all().to_list()
    return {
        "total_users": await User.count(),
        "active_companies": sum(1 for c in companies if c.status == "active"),
        "mrr": sum(PLAN_PRICES.get(c.plan, 0) for c in companies if c.status != "churned"),
        "total_tests": await Test.count(),
    }


@router.get("/admin/users")
async def admin_users() -> list[dict]:
    users = await User.find_all().sort(-User.created_at).to_list()
    companies = {str(c.id): c for c in await Company.find_all().to_list()}
    tests = await Test.find_all().to_list()
    tests_by_user: dict[str, int] = {}
    for t in tests:
        tests_by_user[t.created_by] = tests_by_user.get(t.created_by, 0) + 1
    return [
        {
            "id": str(u.id),
            "name": u.name,
            "email": u.email,
            "company": companies.get(u.company_id).name if companies.get(u.company_id) else "—",
            "plan": companies.get(u.company_id).plan if companies.get(u.company_id) else "free",
            "status": "active",
            "created_at": u.created_at.isoformat(),
            "tests_created": tests_by_user.get(str(u.id), 0) + tests_by_user.get(u.email, 0),
        }
        for u in users
    ]


@router.get("/admin/companies")
async def admin_companies() -> list[dict]:
    companies = await Company.find_all().to_list()
    users = await User.find_all().to_list()
    seats_used: dict[str, int] = {}
    for u in users:
        seats_used[u.company_id] = seats_used.get(u.company_id, 0) + 1
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "plan": c.plan,
            "seats": c.seats,
            "seats_used": seats_used.get(str(c.id), 0),
            "mrr": PLAN_PRICES.get(c.plan, 0) if c.status != "churned" else 0,
            "status": c.status,
            "created_at": None,
        }
        for c in companies
    ]


@router.get("/admin/tests")
async def admin_tests() -> list[dict]:
    tests = await Test.find_all().sort(-Test.updated_at).to_list()
    companies = {str(c.id): c.name for c in await Company.find_all().to_list()}
    candidates = await Candidate.find_all().to_list()
    result = []
    for t in tests:
        test_candidates = [c for c in candidates if c.test_id == str(t.id)]
        scored = [c for c in test_candidates if c.score is not None]
        result.append(
            {
                "id": str(t.id),
                "name": t.name,
                "company": companies.get(t.company_id, "—"),
                "invited": len(test_candidates),
                "completed": sum(1 for c in test_candidates if c.completed_at),
                "avg_score": round(sum(c.score or 0 for c in scored) / len(scored)) if scored else None,
                "status": t.status,
            }
        )
    return result
