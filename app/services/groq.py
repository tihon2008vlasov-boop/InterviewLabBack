import asyncio
import json
import logging
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException, status
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.ai import GeneratedTaskOut, GenerateTaskIn

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
logger = logging.getLogger(__name__)
MAX_GROQ_ATTEMPTS = 2


def _json_schema_hint() -> str:
    return (
        "Return only valid JSON with this shape: "
        '{"title": string, "description": string, "readme": string, '
        '"starter_code": string, "points": number, '
        '"settings": {"time_limit_min": number|null, "camera_required": boolean, '
        '"tab_switch_lock": boolean}}'
    )


def _build_messages(payload: GenerateTaskIn) -> list[dict[str, str]]:
    test = payload.test
    task = payload.task
    return [
        {
            "role": "system",
            "content": (
                "You generate technical screening tasks for HR teams. "
                "Create practical, fair, self-contained tasks in Russian. "
                "Respect the requested level, stack, time limit, and task type. "
                "Do not include solutions. "
                + _json_schema_hint()
            ),
        },
        {
            "role": "user",
            "content": (
                f"HR request: {payload.prompt}\n"
                f"Test name: {test.name or 'Untitled'}\n"
                f"Test description: {test.description or 'No description'}\n"
                f"Level: {test.level}\n"
                f"Stack/language: {test.language}\n"
                f"Total test duration: {test.duration_min} minutes\n"
                f"Task type: {task.type}\n"
                f"Current task points: {task.points}\n"
                f"Current task time limit: {task.time_limit_min}\n"
                f"Camera required: {task.camera_required}\n"
                f"Tab switch tracking: {task.tab_switch_lock}"
            ),
        },
    ]


def _extract_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Groq returned an unexpected response") from exc


def _request_groq(payload: GenerateTaskIn) -> dict:
    body = {
        "model": settings.groq_model,
        "messages": _build_messages(payload),
        "temperature": 0.45,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    request = Request(
        GROQ_CHAT_COMPLETIONS_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.groq_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "InterviewLab/0.1 FastAPI",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


async def generate_task_with_groq(payload: GenerateTaskIn) -> GeneratedTaskOut:
    if not settings.groq_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GROQ_API_KEY is not configured")

    for attempt in range(1, MAX_GROQ_ATTEMPTS + 1):
        try:
            data = await asyncio.to_thread(_request_groq, payload)
            raw_task = json.loads(_extract_content(data))
            return GeneratedTaskOut.model_validate(raw_task)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            logger.warning("Groq HTTP error on attempt %s: %s", attempt, detail)
            if attempt == MAX_GROQ_ATTEMPTS or exc.code not in {429, 500, 502, 503, 504}:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    f"Groq API error: {detail}",
                ) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            logger.warning("Groq connection error on attempt %s: %s", attempt, exc)
            if attempt == MAX_GROQ_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Could not reach Groq API",
                ) from exc
        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning("Invalid Groq JSON on attempt %s: %s", attempt, exc)
            if attempt == MAX_GROQ_ATTEMPTS:
                raise HTTPException(
                    status.HTTP_502_BAD_GATEWAY,
                    "Groq returned invalid task JSON",
                ) from exc

        await asyncio.sleep(0.5 * attempt)

    raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Groq task generation failed")
