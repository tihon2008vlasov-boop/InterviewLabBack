import asyncio
import json
import logging
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.ai import (
    GeneratedMockupOut,
    GeneratedTasksOut,
    GenerateMockupIn,
    GenerateTaskIn,
)

logger = logging.getLogger(__name__)
MAX_GEMINI_ATTEMPTS = 2

TASK_TYPE_INSTRUCTIONS = {
    "code": (
        "Кандидат должен написать самостоятельную реализацию с нуля. Дай ясное техническое "
        "задание и критерии приемки. starter_code содержит только минимальный каркас без решения."
    ),
    "bugfix": (
        "Кандидат должен найти и исправить баг в готовом коде. Опиши фактическое и ожидаемое "
        "поведение, шаги воспроизведения. starter_code обязан содержать реалистичный сломанный "
        "код; не раскрывай причину дефекта и не давай исправление."
    ),
    "feature": (
        "Кандидат должен доработать существующий проект. Дай контекст текущего поведения, новую "
        "функциональность и acceptance criteria. starter_code содержит существующую точку "
        "расширения, но не готовую реализацию фичи."
    ),
    "quiz": (
        "Кандидат должен письменно ответить на теоретические вопросы по стеку. Создай вопросы "
        "подходящей уровню сложности, проверяющие понимание, сравнение и применение концепций. "
        "В readme перечисли вопросы и критерии оценки без ответов. starter_code должен быть пустым."
    ),
    "algorithm": (
        "Кандидат должен решить алгоритмическую задачу. Сформулируй условие, формат ввода и "
        "вывода, ограничения и примеры. starter_code содержит только сигнатуру функции или ввод/вывод. "
        "Не называй нужный алгоритм и не добавляй решение. Создай 3 публичных test_cases с полным "
        "stdin и точным expected_output, пригодных для автоматического сравнения."
    ),
    "sql": (
        "Кандидат должен написать SQL-запрос или спроектировать SQL-схему. Все содержимое должно "
        "относиться к SQL: таблицы, связи, JOIN, агрегации, оконные функции или индексы согласно "
        "уровню. starter_code содержит DDL и при необходимости INSERT с тестовыми данными, но не "
        "содержит итоговый запрос-решение."
    ),
}


def _response_schema() -> dict:
    task_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "readme": {"type": "string"},
            "starter_code": {"type": "string"},
            "points": {"type": "integer", "minimum": 1, "maximum": 100},
            "settings": {
                "type": "object",
                "properties": {
                    "time_limit_min": {"type": "integer", "minimum": 1},
                    "camera_required": {"type": "boolean"},
                    "tab_switch_lock": {"type": "boolean"},
                },
                "required": ["time_limit_min", "camera_required", "tab_switch_lock"],
            },
            "test_cases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "input": {"type": "string"},
                        "expected_output": {"type": "string"},
                    },
                    "required": ["id", "input", "expected_output"],
                },
            },
        },
        "required": [
            "title",
            "description",
            "readme",
            "starter_code",
            "points",
            "settings",
            "test_cases",
        ],
    }
    return {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": task_schema,
                "minItems": 1,
                "maxItems": 10,
            }
        },
        "required": ["tasks"],
    }


def _build_prompt(payload: GenerateTaskIn) -> str:
    test = payload.test
    task = payload.task
    time_limit = task.time_limit_min or max(5, min(test.duration_min, 60))
    type_instruction = TASK_TYPE_INSTRUCTIONS[task.type]
    return (
        "Создай практическое, справедливое и полностью самостоятельное техническое "
        "задание на русском языке. Не добавляй решение. Соблюдай все параметры HR. "
        "Определи из запроса HR, сколько отдельных заданий нужно создать. Если количество "
        "не указано, создай одно. Верни ровно запрошенное количество (не больше 10), каждое "
        "как самостоятельное задание с уникальной целью. Описание каждого должно быть до "
        "1200 символов, readme до 5000 символов, starter_code до 5000 символов. Пиши "
        "компактно и заверши все строки и блоки кода.\n\n"
        f"Обязательный сценарий для выбранного типа: {type_instruction}\n\n"
        f"Запрос HR: {payload.prompt}\n"
        f"Название теста: {test.name or 'Без названия'}\n"
        f"Описание теста: {test.description or 'Не указано'}\n"
        f"Уровень: {test.level}\n"
        f"Стек или язык: {test.language}\n"
        f"Общая длительность теста: {test.duration_min} минут\n"
        f"Тип задания: {task.type}\n"
        f"Баллы: {task.points}\n"
        f"Лимит задания: {time_limit} минут\n"
        f"Камера обязательна: {task.camera_required}\n"
        f"Контроль смены вкладок: {task.tab_switch_lock}"
    )


def _request_gemini(payload: GenerateTaskIn) -> dict:
    model = quote(settings.gemini_model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": _build_prompt(payload)}]}],
        "generationConfig": {
            "maxOutputTokens": 12000,
            "responseMimeType": "application/json",
            "responseJsonSchema": _response_schema(),
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": settings.gemini_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "InterviewLab/0.1 FastAPI",
        },
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def _extract_content(data: dict) -> str:
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        reason = data.get("promptFeedback", {}).get("blockReason", "unexpected response")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Gemini did not return a task: {reason}",
        ) from exc


MOCKUP_SCHEMA = {
    "type": "object",
    "properties": {"html": {"type": "string"}},
    "required": ["html"],
}


def _build_mockup_prompt(payload: GenerateMockupIn) -> str:
    return (
        "Ты UI-дизайнер. Создай эталонный макет интерфейса, который кандидат должен "
        "воспроизвести кодом. Верни один самодостаточный HTML-документ: весь CSS в теге "
        "<style>, без JavaScript, без внешних ссылок, шрифтов и картинок (иконки — inline "
        "SVG или emoji не использовать, только SVG). Реалистичные тексты на русском. "
        "Современный чистый дизайн: аккуратные отступы, читаемая типографика, светлая тема. "
        "Размер под вьюпорт ~800×600. Не добавляй пояснений — только HTML.\n\n"
        f"Что должно быть на макете: {payload.prompt}\n"
        f"Стек кандидата: {payload.language}\n"
        f"Уровень кандидата: {payload.level}"
    )


def _request_mockup(payload: GenerateMockupIn) -> dict:
    model = quote(settings.gemini_model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"role": "user", "parts": [{"text": _build_mockup_prompt(payload)}]}],
        "generationConfig": {
            "maxOutputTokens": 12000,
            "responseMimeType": "application/json",
            "responseJsonSchema": MOCKUP_SCHEMA,
            "thinkingConfig": {"thinkingLevel": "minimal"},
        },
    }
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": settings.gemini_api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "InterviewLab/0.1 FastAPI",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


async def generate_mockup_with_gemini(payload: GenerateMockupIn) -> GeneratedMockupOut:
    if not settings.gemini_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GEMINI_API_KEY is not configured",
        )

    for attempt in range(1, MAX_GEMINI_ATTEMPTS + 1):
        try:
            data = await asyncio.to_thread(_request_mockup, payload)
            return GeneratedMockupOut.model_validate_json(_extract_content(data))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.warning("Gemini mockup HTTP error on attempt %s: %s", attempt, detail)
            if attempt == MAX_GEMINI_ATTEMPTS or exc.code not in {429, 500, 502, 503, 504}:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Gemini API error: {detail}",
                ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            logger.warning("Gemini mockup connection error on attempt %s: %s", attempt, exc)
            if attempt == MAX_GEMINI_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Could not reach Gemini API",
                ) from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Invalid Gemini mockup JSON on attempt %s: %s", attempt, exc)
            if attempt == MAX_GEMINI_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Gemini returned invalid mockup JSON",
                ) from exc

        await asyncio.sleep(0.5 * attempt)

    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini mockup generation failed")


async def generate_task_with_gemini(payload: GenerateTaskIn) -> GeneratedTasksOut:
    if not settings.gemini_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GEMINI_API_KEY is not configured",
        )

    for attempt in range(1, MAX_GEMINI_ATTEMPTS + 1):
        try:
            data = await asyncio.to_thread(_request_gemini, payload)
            return GeneratedTasksOut.model_validate_json(_extract_content(data))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.warning("Gemini HTTP error on attempt %s: %s", attempt, detail)
            if attempt == MAX_GEMINI_ATTEMPTS or exc.code not in {429, 500, 502, 503, 504}:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Gemini API error: {detail}",
                ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            logger.warning("Gemini connection error on attempt %s: %s", attempt, exc)
            if attempt == MAX_GEMINI_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Could not reach Gemini API",
                ) from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Invalid Gemini JSON on attempt %s: %s", attempt, exc)
            if attempt == MAX_GEMINI_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Gemini returned invalid task JSON",
                ) from exc

        await asyncio.sleep(0.5 * attempt)

    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Gemini task generation failed")
