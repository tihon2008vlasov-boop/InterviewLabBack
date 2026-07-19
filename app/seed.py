import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.db import init_db
from app.core.security import hash_password
from app.models.candidate import AIReport, Candidate, Integrity, SkillScore
from app.models.company import Company
from app.models.test import InviteLink, Test, TestTask
from app.models.user import User

HR_EMAIL = "hr@interviewlab.ai"
HR_PASSWORD = "Password123!"


def now() -> datetime:
    return datetime.now(timezone.utc)


async def seed() -> None:
    await init_db()

    if await User.find_one(User.email == HR_EMAIL):
        print(f"Seed already applied — HR account {HR_EMAIL} exists. Nothing to do.")
        return

    company = await Company.insert_one(
        Company(name="TechCorp", website="https://techcorp.io", plan="pro", seats=10, status="active")
    )
    company_id = str(company.id)

    await User.insert_one(
        User(
            name="HR Manager",
            email=HR_EMAIL,
            password_hash=hash_password(HR_PASSWORD),
            role="owner",
            company_id=company_id,
        )
    )

    react_test = await Test.insert_one(
        Test(
            company_id=company_id,
            created_by=HR_EMAIL,
            name="Frontend React — Middle",
            description="Practical screening for middle React engineers: component design, data fetching, debugging.",
            level="middle",
            language="react",
            duration_min=90,
            status="active",
            tasks=[
                TestTask(
                    id=str(uuid4()),
                    type="code",
                    title="Страница поиска товаров",
                    description=(
                        "Соберите страницу поиска товаров поверх выданного фейкового API.\n\n"
                        "Требования:\n"
                        "1. Поле поиска фильтрует товары по названию — добавьте debounce\n"
                        "2. Показывайте состояние загрузки\n"
                        "3. Обрабатывайте ошибки и пустые результаты\n"
                        "4. Выводите название, цену и категорию товара\n"
                        "5. Показывайте суммарную стоимость видимых товаров"
                    ),
                    points=40,
                    starter_code=(
                        "import { useState } from 'react'\n\n"
                        "export default function App() {\n"
                        "  return (\n"
                        "    <div className=\"app\">\n"
                        "      <h1>Product Search</h1>\n"
                        "      {/* Реализуйте поиск и список результатов */}\n"
                        "    </div>\n"
                        "  )\n"
                        "}\n"
                    ),
                    readme=(
                        "# Поиск товаров\n\n"
                        "Используйте fetchProducts(query) из src/api/products.js.\n"
                        "Мы смотрим на структуру компонентов, гонки запросов,\n"
                        "обработку крайних случаев и базовую доступность."
                    ),
                ),
                TestTask(
                    id=str(uuid4()),
                    type="bugfix",
                    title="Fix the cart total bug",
                    description="The cart total re-renders with a stale value after removing an item. Find and fix the root cause.",
                    points=30,
                ),
                TestTask(
                    id=str(uuid4()),
                    type="quiz",
                    title="React fundamentals",
                    description="Eight questions on reconciliation, hooks rules, keys and memoization.",
                    points=30,
                ),
            ],
            links=[
                InviteLink(id=str(uuid4()), code="DEMO01", max_uses=None, expires_at=None),
                InviteLink(
                    id=str(uuid4()),
                    code="RCT7Q2",
                    max_uses=50,
                    expires_at=now() + timedelta(days=14),
                ),
            ],
        )
    )

    await Test.insert_one(
        Test(
            company_id=company_id,
            created_by=HR_EMAIL,
            name="Node.js API — Junior",
            description="Build two REST endpoints with validation and write basic tests.",
            level="junior",
            language="node",
            duration_min=60,
            status="active",
            tasks=[
                TestTask(
                    id=str(uuid4()),
                    type="code",
                    title="Todos endpoint",
                    description="Implement GET/POST /todos with validation on an Express starter.",
                    points=60,
                ),
            ],
            links=[InviteLink(id=str(uuid4()), code="NODE01")],
        )
    )

    test_id = str(react_test.id)
    await Candidate.insert_many(
        [
            Candidate(
                company_id=company_id,
                test_id=test_id,
                name="Ivan Petrov",
                email="ivan.petrov@gmail.com",
                phone="+7 705 214 88 31",
                position="Frontend Engineer",
                status="reviewed",
                score=87,
                ai_recommendation="strong_hire",
                ai_report=AIReport(
                    summary="Complete, production-quality solution well within the time limit. Clean component boundaries, deliberate async handling.",
                    strengths=["Handled fetch race condition with cleanup", "Clean component decomposition"],
                    weaknesses=["No tests written", "Focus management could improve"],
                    verdict="Move directly to the final interview.",
                    skills=[
                        SkillScore(name="React", score=88, comment="Idiomatic hooks"),
                        SkillScore(name="Architecture", score=84, comment="Clean boundaries"),
                        SkillScore(name="Code Quality", score=86, comment="Consistent naming"),
                    ],
                ),
                integrity=Integrity(tab_switches=1, paste_events=0, camera_uptime=99),
                invited_at=now() - timedelta(days=5),
                completed_at=now() - timedelta(days=4),
                duration_sec=4380,
            ),
            Candidate(
                company_id=company_id,
                test_id=test_id,
                name="Anna Lebedeva",
                email="anna.lebedeva@mail.ru",
                phone="+7 701 377 58 06",
                position="Frontend Engineer",
                status="completed",
                score=59,
                ai_recommendation="consider",
                integrity=Integrity(tab_switches=4, paste_events=2, camera_uptime=97),
                invited_at=now() - timedelta(days=3),
                completed_at=now() - timedelta(days=1),
                duration_sec=5220,
            ),
            Candidate(
                company_id=company_id,
                test_id=test_id,
                name="Timur Akhmetov",
                email="timur.akhmetov@gmail.com",
                phone="+7 778 640 15 92",
                position="Frontend Engineer",
                status="invited",
                invited_at=now() - timedelta(hours=20),
            ),
        ]
    )

    print("Seed complete.")
    print(f"  HR login:    {HR_EMAIL}")
    print(f"  HR password: {HR_PASSWORD}")
    print("  Invite links: DEMO01 (no limits), RCT7Q2 (50 uses, 14 days), NODE01")
    print("  Candidate link example: http://localhost:5173/test/DEMO01")


if __name__ == "__main__":
    asyncio.run(seed())
