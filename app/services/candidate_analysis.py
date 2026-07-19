import asyncio
import json
import logging
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.models.candidate import AIRecommendation, AIReport, ActivityEvent, Candidate
from app.models.test import Test

logger = logging.getLogger(__name__)
MAX_SOLUTION_CHARS = 40_000
MAX_FILE_CHARS = 12_000


class AnalysisResult(BaseModel):
    score: int = Field(ge=0, le=100)
    recommendation: AIRecommendation
    report: AIReport


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 100},
            "recommendation": {
                "type": "string",
                "enum": ["strong_hire", "hire", "consider", "reject"],
            },
            "report": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "strengths": {"type": "array", "items": {"type": "string"}},
                    "weaknesses": {"type": "array", "items": {"type": "string"}},
                    "verdict": {"type": "string"},
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                                "comment": {"type": "string"},
                            },
                            "required": ["name", "score", "comment"],
                        },
                    },
                    "task_scores": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string"},
                                "score": {"type": "integer", "minimum": 0, "maximum": 100},
                                "comment": {"type": "string"},
                            },
                            "required": ["task", "score", "comment"],
                        },
                    },
                    "code_findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "file": {"type": "string"},
                                "line_start": {"type": "integer", "minimum": 1},
                                "line_end": {"type": "integer", "minimum": 1},
                                "severity": {
                                    "type": "string",
                                    "enum": ["info", "warning", "error"],
                                },
                                "title": {"type": "string"},
                                "explanation": {"type": "string"},
                                "suggestion": {"type": "string"},
                            },
                            "required": [
                                "file", "line_start", "line_end", "severity", "title",
                                "explanation", "suggestion",
                            ],
                        },
                    },
                },
                "required": [
                    "summary", "strengths", "weaknesses", "verdict", "skills",
                    "task_scores", "code_findings",
                ],
            },
        },
        "required": ["score", "recommendation", "report"],
    }


def _task_text(test: Test) -> str:
    blocks: list[str] = []
    index = 1
    for task in test.tasks:
        examples = "\n".join(
            f"EXAMPLE stdin={case.input!r} expected={case.expected_output!r}"
            for case in task.test_cases
        )
        blocks.append(
            f"TASK {index}: {task.title}\nDESCRIPTION: {task.description}\n"
            f"CRITERIA:\n{task.readme}\n{examples}"
        )
        index += 1
        for subtask in task.subtasks:
            examples = "\n".join(
                f"EXAMPLE stdin={case.input!r} expected={case.expected_output!r}"
                for case in subtask.test_cases
            )
            blocks.append(
                f"TASK {index}: {subtask.title}\nDESCRIPTION: {subtask.description}\n"
                f"CRITERIA:\n{subtask.readme}\n{examples}"
            )
            index += 1
    return "\n\n".join(blocks)


def _solution_text(candidate: Candidate) -> str:
    chunks: list[str] = []
    remaining = MAX_SOLUTION_CHARS
    for file in candidate.submitted_files:
        if remaining <= 0:
            break
        code = file.code[: min(MAX_FILE_CHARS, remaining)]
        chunks.append(f"FILE: {file.name}\nLANGUAGE: {file.language}\n```\n{code}\n```")
        remaining -= len(code)
    return "\n\n".join(chunks)


def _request_analysis(candidate: Candidate, test: Test) -> AnalysisResult:
    model = quote(settings.gemini_model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    prompt = (
        "Ты старший технический интервьюер. Проведи статический анализ решений кандидата на "
        "русском языке. Сопоставь каждый файл с соответствующим заданием по номеру. Не утверждай, "
        "что код запускался: интерпретатор не используется. Оцени полноту, корректность, качество, "
        "безопасность и соответствие уровню. Для каждой конкретной проблемы укажи существующий "
        "файл и точные строки. Не создавай findings без уверенности. Максимум 20 findings.\n\n"
        f"TEST: {test.name}\nLEVEL: {test.level}\nSTACK: {test.language}\n\n"
        f"ASSIGNMENTS:\n{_task_text(test)}\n\nSOLUTIONS:\n{_solution_text(candidate)}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 10000,
            "responseMimeType": "application/json",
            "responseJsonSchema": _response_schema(),
            "thinkingConfig": {"thinkingLevel": "low"},
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
        data = json.loads(response.read().decode("utf-8"))
    content = data["candidates"][0]["content"]["parts"][0]["text"]
    return AnalysisResult.model_validate_json(content)


async def analyze_candidate_solution(candidate_id: str, test_id: str) -> None:
    if not settings.gemini_api_key:
        logger.error("Candidate analysis skipped: GEMINI_API_KEY is not configured")
        return

    candidate = await Candidate.get(candidate_id)
    test = await Test.get(test_id)
    if candidate is None or test is None or not candidate.submitted_files:
        return
    if candidate.status != "completed" or candidate.score is not None:
        return

    candidate.analysis_status = "pending"
    await candidate.save()

    try:
        result = await asyncio.to_thread(_request_analysis, candidate, test)
        candidate.score = result.score
        candidate.ai_recommendation = result.recommendation
        candidate.ai_report = result.report
        candidate.analysis_status = "completed"
        candidate.analyzed_at = datetime.now(timezone.utc)
        candidate.activity.append(
            ActivityEvent(
                at=datetime.now(timezone.utc),
                kind="analyzed",
                label="AI-анализ решения завершён",
            )
        )
        await candidate.save()
        logger.info("Candidate analysis completed for %s", candidate_id)
    except (HTTPError, URLError, KeyError, IndexError, json.JSONDecodeError, ValidationError) as exc:
        logger.exception("Candidate analysis failed for %s: %s", candidate_id, exc)
        candidate.analysis_status = "failed"
        await candidate.save()
