import asyncio

from app.core.db import init_db
from app.models.company import Company
from app.models.task_template import TaskTemplate
from app.models.test import AlgorithmTestCase, TaskSettings, TestTask
from app.models.user import User
from app.task_catalog import TASK_CATALOG, CatalogTask

SOURCE_URLS = {
    "codeforces": "https://codeforces.com/problemset",
    "codewars": "https://www.codewars.com/kata",
    "leetcode": "https://leetcode.com/problemset",
}
POINTS = {"junior": 15, "middle": 25, "senior": 40}
TIME_LIMITS = {"junior": 20, "middle": 35, "senior": 50}


def source_url_for(entry: CatalogTask) -> str:
    if entry.source == "leetcode" and entry.slug == "target-pair":
        return "https://leetcode.com/problems/two-sum/"
    return SOURCE_URLS[entry.source]


def build_task(entry: CatalogTask) -> TestTask:
    examples = "\n\n".join(
        f"### Пример {index}\nВвод:\n```\n{input_data}\n```\n"
        f"Вывод:\n```\n{expected}\n```"
        for index, (input_data, expected) in enumerate(entry.tests, start=1)
    )
    readme = (
        f"# {entry.title}\n\n"
        f"## Условие\n{entry.statement}\n\n"
        "## Ввод и вывод\n"
        "Прочитайте данные из стандартного ввода в формате, показанном в примерах. "
        "Выведите только требуемый результат без поясняющего текста.\n\n"
        f"## Примеры\n{examples}\n\n"
        "## Требования\n"
        "Решение должно корректно обрабатывать граничные случаи и укладываться "
        "в ограничения из условия."
    )
    return TestTask(
        id=f"library-{entry.source}-{entry.slug}",
        type="algorithm",
        title=entry.title,
        description=entry.statement,
        points=POINTS[entry.level],
        starter_code=(
            "import sys\n\n"
            "def solve() -> None:\n"
            "    data = sys.stdin.read().strip()\n"
            "    # Напишите решение здесь\n"
            "    pass\n\n"
            "if __name__ == \"__main__\":\n"
            "    solve()\n"
        ),
        readme=readme,
        test_cases=[
            AlgorithmTestCase(
                id=f"case-{index}",
                input=input_data,
                expected_output=expected,
            )
            for index, (input_data, expected) in enumerate(entry.tests, start=1)
        ],
        settings=TaskSettings(
            time_limit_min=TIME_LIMITS[entry.level],
            camera_required=True,
            tab_switch_lock=True,
        ),
    )


async def seed_company(company: Company) -> tuple[int, int, int, int]:
    company_id = str(company.id)
    owner = await User.find_one(User.company_id == company_id)
    templates = await TaskTemplate.find(TaskTemplate.company_id == company_id).to_list()
    templates_by_task_id: dict[str, list[TaskTemplate]] = {}
    for template in templates:
        templates_by_task_id.setdefault(template.task.id, []).append(template)
    created = 0
    updated = 0
    skipped = 0
    removed = 0

    for entry in TASK_CATALOG:
        task = build_task(entry)
        matches = templates_by_task_id.get(task.id, [])
        existing = next(
            (template for template in matches if template.title == entry.title),
            matches[0] if matches else None,
        )
        for duplicate in matches:
            if duplicate.id != existing.id:
                await duplicate.delete()
                removed += 1
        if existing is not None:
            changed = any([
                existing.title != entry.title,
                existing.description != entry.statement,
                existing.level != entry.level,
                existing.tags != list(entry.tags),
                existing.source_url != source_url_for(entry),
                existing.task != task,
            ])
            if changed:
                existing.title = entry.title
                existing.description = entry.statement
                existing.task_type = "algorithm"
                existing.level = entry.level
                existing.language = "python"
                existing.tags = list(entry.tags)
                existing.source = entry.source
                existing.source_url = source_url_for(entry)
                existing.task = task
                await existing.save()
                updated += 1
            else:
                skipped += 1
            continue

        await TaskTemplate(
            company_id=company_id,
            created_by=str(owner.id) if owner else "catalog-seed",
            title=entry.title,
            description=entry.statement,
            task_type="algorithm",
            level=entry.level,
            language="python",
            tags=list(entry.tags),
            source=entry.source,
            source_url=source_url_for(entry),
            task=task,
        ).insert()
        created += 1

    return created, updated, skipped, removed


async def main() -> None:
    await init_db()
    companies = await Company.find_all().to_list()
    if not companies:
        raise RuntimeError("No companies found. Register an HR account before seeding the library.")

    total_created = 0
    total_updated = 0
    total_skipped = 0
    total_removed = 0
    for company in companies:
        created, updated, skipped, removed = await seed_company(company)
        total_created += created
        total_updated += updated
        total_skipped += skipped
        total_removed += removed
        print(
            f"[task-library] {company.name}: created={created}, "
            f"updated={updated}, skipped={skipped}, removed={removed}"
        )

    print(
        f"[task-library] done: companies={len(companies)}, "
        f"created={total_created}, updated={total_updated}, skipped={total_skipped}, "
        f"removed={total_removed}"
    )


if __name__ == "__main__":
    asyncio.run(main())
