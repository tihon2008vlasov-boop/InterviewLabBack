import asyncio
import json
import logging
import socket
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.lookup import get_or_none
from app.models.candidate import ActivityEvent, AIRecommendation, AIReport, Candidate
from app.models.session import Session
from app.models.test import Test
from app.services.typing_forensics import analyze_typing

logger = logging.getLogger(__name__)
MAX_SOLUTION_CHARS = 40_000
MAX_FILE_CHARS = 12_000
MAX_ANALYSIS_ATTEMPTS = 3


class AnalysisResult(BaseModel):
    technical_score: int = Field(ge=0, le=100)
    recommendation: AIRecommendation
    report: AIReport


def _response_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "technical_score": {"type": "integer", "minimum": 0, "maximum": 100},
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
                    "authenticity": {
                        "type": "object",
                        "properties": {
                            "verdict": {
                                "type": "string",
                                "enum": ["typed", "mixed", "likely_pasted", "no_data"],
                            },
                            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                            "summary": {"type": "string"},
                            "signals": {"type": "array", "items": {"type": "string"}},
                            "interview_questions": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": [
                            "verdict", "confidence", "summary", "signals", "interview_questions",
                        ],
                    },
                    "integrity_assessment": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "integer", "minimum": 0, "maximum": 100},
                            "risk_level": {
                                "type": "string",
                                "enum": ["low", "medium", "high", "critical"],
                            },
                            "summary": {"type": "string"},
                            "signals": {"type": "array", "items": {"type": "string"}},
                            "review_moments": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "at_sec": {"type": "integer", "minimum": 0},
                                        "source": {
                                            "type": "string",
                                            "enum": ["proctoring", "replay"],
                                        },
                                        "severity": {
                                            "type": "string",
                                            "enum": ["info", "warning", "critical"],
                                        },
                                        "title": {"type": "string"},
                                        "explanation": {"type": "string"},
                                    },
                                    "required": [
                                        "at_sec", "source", "severity", "title", "explanation",
                                    ],
                                },
                            },
                        },
                        "required": [
                            "score", "risk_level", "summary", "signals", "review_moments",
                        ],
                    },
                },
                "required": [
                    "summary", "strengths", "weaknesses", "verdict", "skills",
                    "task_scores", "code_findings", "authenticity", "integrity_assessment",
                ],
            },
        },
        "required": ["technical_score", "recommendation", "report"],
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


def _replay_text(candidate: Candidate) -> str:
    events = sorted(candidate.replay, key=lambda event: event.at_sec)
    if not events:
        return "CODE REPLAY TIMELINE: no events"
    lines = ["CODE REPLAY TIMELINE (snapshots omitted because final files are supplied separately):"]
    for event in events[-160:]:
        file_part = f" file={event.file}" if event.file else ""
        detail_part = f" detail={event.detail[:180]!r}" if event.detail else ""
        lines.append(
            f"- {event.at_sec}s kind={event.kind}{file_part} label={event.label!r}{detail_part}"
        )
    return "\n".join(lines)


def _proctoring_text(candidate: Candidate, session: Session | None) -> str:
    events = candidate.integrity.proctor_events
    if not events:
        return (
            "PROCTORING EVIDENCE: no incidents recorded; "
            f"backend risk score={candidate.integrity.proctor_risk_score}/100"
        )

    origin = None
    if session is not None:
        origin = session.recording_started_at or session.started_at
        if origin.tzinfo is None:
            origin = origin.replace(tzinfo=timezone.utc)

    lines = [
        "PROCTORING EVIDENCE (computer-vision and audio signals require manual confirmation):",
        f"- backend risk score={candidate.integrity.proctor_risk_score}/100",
        (
            "- counters: "
            f"phone={candidate.integrity.phone_detections}, "
            f"multiple_people={candidate.integrity.multiple_people}, "
            f"face_absent={candidate.integrity.face_absence_events}, "
            f"identity_mismatch={candidate.integrity.identity_mismatches}, "
            f"screen_stopped={candidate.integrity.screen_share_interruptions}, "
            f"camera_obstructed={candidate.integrity.camera_obstructions}, "
            f"speech_events={candidate.integrity.speech_events}, "
            f"tab_switches={candidate.integrity.tab_switches}"
        ),
    ]
    for event in events[-160:]:
        at_sec = event.at_sec
        if at_sec is None and origin is not None:
            event_at = event.at
            if event_at.tzinfo is None:
                event_at = event_at.replace(tzinfo=timezone.utc)
            at_sec = max(0, int((event_at - origin).total_seconds()))
        lines.append(
            f"- {at_sec or 0}s kind={event.kind} severity={event.severity} "
            f"confidence={event.confidence}% label={event.label!r} "
            f"detail={(event.detail or '')[:240]!r}"
        )
    return "\n".join(lines)


def _overall_score(technical_score: int, integrity_score: int) -> int:
    integrity_penalty = round((100 - integrity_score) * 0.35)
    score = max(0, min(100, technical_score - integrity_penalty))
    if integrity_score < 20:
        return min(score, 49)
    if integrity_score < 40:
        return min(score, 59)
    if integrity_score < 60:
        return min(score, 69)
    return score


def _recommendation_for_score(score: int) -> AIRecommendation:
    if score >= 85:
        return "strong_hire"
    if score >= 70:
        return "hire"
    if score >= 50:
        return "consider"
    return "reject"


def _request_analysis(candidate: Candidate, test: Test, session: Session | None) -> AnalysisResult:
    model = quote(settings.gemini_analysis_model, safe="")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    forensics = analyze_typing(candidate)
    prompt = (
        "Ты старший технический интервьюер. Проведи статический анализ решений кандидата на "
        "русском языке. Сопоставь каждый файл с соответствующим заданием по номеру. Не утверждай, "
        "что код запускался: интерпретатор не используется. Оцени полноту, корректность, качество, "
        "безопасность и соответствие уровню. Для каждой конкретной проблемы укажи существующий "
        "файл и точные строки. Не создавай findings без уверенности. Максимум 20 findings.\n\n"
        "ОТДЕЛЬНО заполни блок authenticity — самостоятельность работы. Опирайся на PROCESS "
        "EVIDENCE (как код появлялся в редакторе) и на признаки в самом коде: избыточные "
        "комментарии к очевидным строкам, неиспользуемые импорты и переменные, обработка "
        "несуществующих кейсов, стиль не по заданию, решение шире требований, англоязычные "
        "комментарии при русском задании, идеально ровное форматирование без следов правок.\n"
        "Правила вывода: verdict=typed — код набирали руками; mixed — часть вставлена "
        "(шаблон, сниппет); likely_pasted — решение вставлено целиком, вероятно из чата с ИИ; "
        "no_data — снимков процесса нет. confidence — насколько ты уверен (0-100). "
        "В signals перечисли конкретные наблюдения с числами и именами файлов, без домыслов. "
        "В interview_questions дай 3-5 вопросов по этому коду, которые отличат автора от того, "
        "кто вставил чужое решение. Вставленный код НЕ снижает technical_score за качество — "
        "оценку качества и самостоятельность держи раздельно.\n\n"
        "ОБЯЗАТЕЛЬНО проанализируй PROCTORING EVIDENCE и CODE REPLAY TIMELINE. "
        "В integrity_assessment.score поставь оценку надёжности прохождения: 100 означает, "
        "что подозрительных сигналов нет, 0 — несколько сильных согласованных сигналов. "
        "Не считай одиночное событие компьютерного зрения доказательством: учитывай confidence, "
        "повторяемость, совпадение с уходами со вкладки, вставками и резкими изменениями кода. "
        "В review_moments перечисли до 12 самых важных моментов с точным at_sec, чтобы HR мог "
        "открыть запись или реплей на нужном месте. report.summary, report.verdict и recommendation "
        "должны учитывать и качество решения, и надёжность процесса. technical_score оценивает "
        "только решение. Общий балл сервер рассчитает как technical_score минус до 35 баллов "
        "штрафа; при критически низкой надёжности общий результат дополнительно ограничивается "
        "порогом ручной проверки.\n\n"
        f"TEST: {test.name}\nLEVEL: {test.level}\nSTACK: {test.language}\n"
        f"Время на тест: {test.duration_min} мин, кандидат затратил: "
        f"{(candidate.duration_sec or 0) // 60} мин\n\n"
        f"{forensics.as_prompt_block()}\n\n"
        f"{_replay_text(candidate)}\n\n"
        f"{_proctoring_text(candidate, session)}\n\n"
        "AUDIO ANALYSIS RULE: speech_detected contains a browser transcript and sustained_audio "
        "contains only an acoustic activity signal. Consider repeated speech, its content and "
        "coincidence with replay/proctoring events. Never treat one audio event as proof of cheating.\n\n"
        "КРИТИЧЕСКОЕ ТРЕБОВАНИЕ К ЯЗЫКУ: заполни НА РУССКОМ все текстовые поля JSON, которые "
        "увидит HR: summary, strengths, weaknesses, verdict, названия и комментарии skills и "
        "task_scores, title/explanation/suggestion у findings, authenticity.summary/signals/"
        "interview_questions, integrity_assessment.summary/signals и title/explanation у "
        "review_moments. Это правило действует независимо от языка кода, задания, транскрипта "
        "и англоязычных названий полей схемы. На английском оставляй только неизменяемые enum, "
        "имена файлов, идентификаторы кода и дословные цитаты. Перед ответом проверь, что ни одно "
        "человекочитаемое объяснение или вопрос не осталось на английском.\n\n"
        f"ASSIGNMENTS:\n{_task_text(test)}\n\nSOLUTIONS:\n{_solution_text(candidate)}"
    )
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 8000,
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
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    candidate_data = data["candidates"][0]
    content = candidate_data["content"]["parts"][0]["text"]
    if not content.strip():
        raise ValueError(
            f"Gemini returned empty analysis (finishReason={candidate_data.get('finishReason')})"
        )
    return AnalysisResult.model_validate_json(content)


async def analyze_candidate_solution(candidate_id: str, test_id: str, force: bool = False) -> None:
    candidate = await get_or_none(Candidate, candidate_id)
    test = await get_or_none(Test, test_id)
    if not settings.gemini_api_key:
        logger.error("Candidate analysis skipped: GEMINI_API_KEY is not configured")
        if candidate is not None:
            candidate.analysis_status = "failed"
            candidate.analysis_error = "GEMINI_API_KEY не настроен на сервере."
            await candidate.save()
        return
    if candidate is None or test is None or not candidate.submitted_files:
        if candidate is not None:
            candidate.analysis_status = "failed"
            candidate.analysis_error = (
                "Не найден тест или отправленное решение кандидата."
            )
            await candidate.save()
        return
    if candidate.status != "completed" or (candidate.score is not None and not force):
        return
    session = await (
        Session.find(Session.candidate_id == candidate_id)
        .sort(-Session.started_at)
        .first_or_none()
    )

    candidate.analysis_status = "pending"
    candidate.analysis_error = ""
    await candidate.save()

    try:
        result: AnalysisResult | None = None
        last_error: Exception | None = None
        for attempt in range(1, MAX_ANALYSIS_ATTEMPTS + 1):
            try:
                result = await asyncio.to_thread(_request_analysis, candidate, test, session)
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                logger.warning(
                    "Candidate analysis HTTP error for %s on attempt %s/%s: %s",
                    candidate_id,
                    attempt,
                    MAX_ANALYSIS_ATTEMPTS,
                    detail[:4000],
                )
                if exc.code not in {429, 500, 502, 503, 504}:
                    break
            except (URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Invalid candidate analysis for %s on attempt %s/%s: %s",
                    candidate_id,
                    attempt,
                    MAX_ANALYSIS_ATTEMPTS,
                    exc,
                )

            if attempt < MAX_ANALYSIS_ATTEMPTS:
                await asyncio.sleep(attempt * 1.5)

        if result is None:
            raise RuntimeError("Gemini analysis failed after retries") from last_error

        result.report.technical_score = result.technical_score
        candidate.score = _overall_score(
            result.technical_score,
            result.report.integrity_assessment.score,
        )
        candidate.ai_recommendation = _recommendation_for_score(candidate.score)
        candidate.ai_report = result.report
        candidate.analysis_status = "completed"
        candidate.analysis_error = ""
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
    except Exception as exc:
        logger.exception("Candidate analysis failed for %s: %s", candidate_id, exc)
        candidate.analysis_status = "failed"
        cause = exc.__cause__ if exc.__cause__ is not None else exc
        if isinstance(cause, HTTPError) and cause.code == 429:
            candidate.analysis_error = (
                "Лимит AI-провайдера исчерпан. Повторите анализ позже."
            )
        elif isinstance(cause, HTTPError) and cause.code in {401, 403}:
            candidate.analysis_error = (
                "AI-провайдер отклонил ключ доступа. Проверьте конфигурацию сервера."
            )
        elif isinstance(cause, (URLError, TimeoutError, socket.timeout)):
            candidate.analysis_error = (
                "AI-провайдер не ответил вовремя. Запустите анализ повторно."
            )
        else:
            candidate.analysis_error = (
                "AI-провайдер не смог обработать решение. Запустите анализ повторно."
            )
        await candidate.save()
