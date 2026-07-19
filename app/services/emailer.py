import asyncio
import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


DECISION_CONTENT = {
    "interview": {
        "subject": "Приглашаем вас на собеседование",
        "heading": "Поздравляем — вы прошли тест! 🎉",
        "body": "Команде понравилось ваше решение, и мы приглашаем вас на собеседование. "
        "В ближайшее время HR свяжется с вами, чтобы согласовать удобное время.",
    },
    "hired": {
        "subject": "Поздравляем — вы приняты!",
        "heading": "Добро пожаловать в команду! 🚀",
        "body": "По итогам теста мы готовы сделать вам предложение. "
        "HR свяжется с вами в ближайшее время с деталями оффера.",
    },
    "pending": {
        "subject": "Итоги вашего теста",
        "heading": "Ваше решение проверено ✅",
        "body": "Мы получили и рассмотрели ваше решение. "
        "Команда найма свяжется с вами, как только будет принято решение.",
    },
}


def build_decision_email(
    candidate_name: str,
    test_name: str,
    duration_sec: int | None,
    score: int | None,
    decision: str,
) -> tuple[str, str]:
    content = DECISION_CONTENT.get(decision, DECISION_CONTENT["pending"])
    minutes = f"{duration_sec // 60} мин" if duration_sec else "—"
    score_row = (
        f"<tr><td style='padding:6px 0;color:#6b6b74'>Оценка</td>"
        f"<td style='padding:6px 0;font-weight:600'>{score} / 100</td></tr>"
        if score is not None
        else ""
    )
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;color:#09090b">
  <h2 style="margin:24px 0 4px">{content['heading']}</h2>
  <p style="color:#6b6b74;margin:0 0 20px">Здравствуйте, {candidate_name}! {content['body']}</p>
  <table style="width:100%;border-top:1px solid #e6e6e9;border-bottom:1px solid #e6e6e9">
    <tr><td style="padding:6px 0;color:#6b6b74">Тест</td><td style="padding:6px 0;font-weight:600">{test_name}</td></tr>
    <tr><td style="padding:6px 0;color:#6b6b74">Затраченное время</td><td style="padding:6px 0;font-weight:600">{minutes}</td></tr>
    {score_row}
  </table>
  <p style="color:#a1a1aa;font-size:12px;margin-top:20px">InterviewLab · AI-платформа технического найма</p>
</div>
"""
    return content["subject"], html


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


def _send_sync(to: str, subject: str, html: str) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.email_from
    message["To"] = to
    message.attach(MIMEText(html, "html", "utf-8"))

    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20) as server:
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, [to], message.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls(context=context)
            server.login(settings.smtp_user, settings.smtp_pass)
            server.sendmail(settings.smtp_user, [to], message.as_string())


async def send_email(to: str, subject: str, html: str) -> None:
    if not smtp_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Отправка почты не настроена: заполните SMTP_HOST, SMTP_USER и SMTP_PASS в backend/.env",
        )
    try:
        await asyncio.to_thread(_send_sync, to, subject, html)
        logger.info("Email sent to %s: %s", to, subject)
    except smtplib.SMTPAuthenticationError as exc:
        logger.exception("SMTP auth failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "SMTP не принял логин/пароль. Для Gmail нужен «пароль приложения».",
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("SMTP send failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Не удалось отправить письмо: {exc}",
        ) from exc
