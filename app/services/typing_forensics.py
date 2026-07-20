"""Разбор процесса написания кода по снимкам реплея.

По финальному коду невозможно понять, писал его кандидат или вставил
готовое решение. Зато воркспейс раз в пару секунд присылает снимок файла —
по разнице между снимками видно скорость набора и резкие вбросы текста.
"""

from dataclasses import dataclass, field

from app.models.candidate import Candidate

# Быстрый разработчик выдаёт ~10 симв/с на коротких рывках.
# Всё, что выше и сразу большим куском, человек физически не наберёт.
HUMAN_CHARS_PER_SEC = 12
MIN_PASTE_CHARS = 120
LARGE_PASTE_CHARS = 400


@dataclass
class TypingForensics:
    typed_chars: int = 0
    pasted_chars: int = 0
    burst_count: int = 0
    largest_burst: int = 0
    fastest_burst_cps: float = 0.0
    paste_events: int = 0
    tab_switches: int = 0
    first_code_at_sec: int | None = None
    total_snapshots: int = 0
    bursts: list[dict] = field(default_factory=list)

    @property
    def final_chars(self) -> int:
        return self.typed_chars + self.pasted_chars

    @property
    def pasted_share(self) -> int:
        total = self.final_chars
        return round(self.pasted_chars / total * 100) if total else 0

    def verdict(self) -> str:
        """Грубая эвристика — окончательное решение остаётся за моделью."""
        if self.total_snapshots < 2:
            return "no_data"
        if self.pasted_share >= 60 or self.largest_burst >= LARGE_PASTE_CHARS:
            return "likely_pasted"
        if self.pasted_share >= 25 or self.burst_count >= 3:
            return "mixed"
        return "typed"

    def as_prompt_block(self) -> str:
        if self.total_snapshots < 2:
            return (
                "PROCESS EVIDENCE: снимков процесса нет — судить о способе "
                "написания кода нельзя. Не делай выводов об авторстве."
            )
        lines = [
            f"Снимков процесса: {self.total_snapshots}",
            f"Символов набрано вручную: {self.typed_chars}",
            f"Символов появилось рывками (вставка): {self.pasted_chars} ({self.pasted_share}% итогового кода)",
            f"Крупных вбросов текста: {self.burst_count}, самый большой: {self.largest_burst} символов",
            f"Пиковая скорость появления кода: {self.fastest_burst_cps:.0f} символов/сек "
            f"(предел ручного набора ~{HUMAN_CHARS_PER_SEC})",
            f"Событий вставки из буфера: {self.paste_events}",
            f"Переключений на другие вкладки: {self.tab_switches}",
        ]
        if self.first_code_at_sec is not None:
            lines.append(f"Первый код появился на {self.first_code_at_sec} секунде сессии")
        for burst in self.bursts[:5]:
            lines.append(
                f"  вброс: +{burst['chars']} символов за {burst['seconds']} с "
                f"в {burst['file']} (на {burst['at_sec']} секунде, "
                f"источник: {burst.get('source', 'рывок набора')})"
            )
        return "PROCESS EVIDENCE:\n" + "\n".join(lines)


def analyze_typing(candidate: Candidate) -> TypingForensics:
    result = TypingForensics(tab_switches=candidate.integrity.tab_switches)
    per_file: dict[str, tuple[int, int]] = {}  # файл -> (длина снимка, момент)

    events = sorted(
        (e for e in candidate.replay if e.snapshot is not None),
        key=lambda e: e.at_sec,
    )
    result.total_snapshots = len(events)
    result.paste_events = sum(1 for e in candidate.replay if e.kind == "paste")

    for event in events:
        name = event.file or "unknown"
        length = len(event.snapshot or "")

        # Стартовый шаблон кандидат не писал — это точка отсчёта, не его текст.
        if event.kind == "create":
            per_file[name] = (length, event.at_sec)
            continue

        prev_len, prev_at = per_file.get(name, (0, event.at_sec))
        delta = length - prev_len
        seconds = max(1, event.at_sec - prev_at)

        if delta > 0:
            speed = delta / seconds
            # Явная вставка из буфера или вброс, который физически не набрать.
            pasted = event.kind == "paste" or (
                delta >= MIN_PASTE_CHARS and speed > HUMAN_CHARS_PER_SEC
            )
            if pasted:
                result.pasted_chars += delta
                result.burst_count += 1
                result.largest_burst = max(result.largest_burst, delta)
                result.fastest_burst_cps = max(result.fastest_burst_cps, speed)
                result.bursts.append(
                    {
                        "chars": delta,
                        "seconds": seconds,
                        "file": name,
                        "at_sec": event.at_sec,
                        "source": "буфер обмена" if event.kind == "paste" else "рывок набора",
                    }
                )
            else:
                result.typed_chars += delta

        if length > 0 and result.first_code_at_sec is None:
            result.first_code_at_sec = event.at_sec
        per_file[name] = (length, event.at_sec)

    return result
