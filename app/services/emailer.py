import asyncio
import logging
import smtplib
import ssl
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from html import escape

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


def _meeting_block(meeting_url: str, meeting_at: str) -> str:
    """Блок с кнопкой видеовстречи для приглашения на собеседование."""
    if not meeting_url.strip() and not meeting_at.strip():
        return ""
    when = (
        f'<p style="margin:0 0 14px;color:#09090b"><strong>Когда:</strong> {escape(meeting_at.strip())}</p>'
        if meeting_at.strip()
        else ""
    )
    button = ""
    if meeting_url.strip():
        safe_url = escape(meeting_url.strip(), quote=True)
        button = f"""
    <p style="margin:0 0 10px">
      <a href="{safe_url}" style="display:inline-block;background:#2563eb;color:#fff;
         text-decoration:none;padding:12px 24px;font-weight:600;border-radius:4px">
        Присоединиться к встрече</a>
    </p>
    <p style="margin:0;color:#2563eb;font-size:12px;word-break:break-all">{safe_url}</p>"""
    return f"""
  <div style="border:1px solid #e6e6e9;background:#f7f9ff;padding:18px;margin:22px 0">
    <p style="margin:0 0 12px;font-weight:600;font-size:15px">Детали встречи</p>
    {when}{button}
  </div>"""


def _contact_block(contact_name: str, contact_details: str) -> str:
    """Блок «с кем связаться» для письма о найме."""
    if not contact_name.strip() and not contact_details.strip():
        return ""
    who = (
        f'<p style="margin:0 0 6px"><strong>{escape(contact_name.strip())}</strong></p>'
        if contact_name.strip()
        else ""
    )
    how = (
        f'<p style="margin:0;color:#6b6b74;line-height:1.6">'
        f'{escape(contact_details.strip()).replace(chr(10), "<br>")}</p>'
        if contact_details.strip()
        else ""
    )
    return f"""
  <div style="border:1px solid #e6e6e9;background:#f6fdf8;padding:18px;margin:22px 0">
    <p style="margin:0 0 12px;font-weight:600;font-size:15px">Ваш контакт для связи</p>
    {who}{how}
  </div>"""


def build_decision_email(
    candidate_name: str,
    test_name: str,
    duration_sec: int | None,
    score: int | None,
    decision: str,
    company_name: str = "InterviewLab",
    custom_subject: str = "",
    custom_message: str = "",
    meeting_url: str = "",
    meeting_at: str = "",
    contact_name: str = "",
    contact_details: str = "",
) -> tuple[str, str]:
    content = DECISION_CONTENT.get(decision, DECISION_CONTENT["pending"])
    minutes = f"{duration_sec // 60} мин" if duration_sec else "—"
    score_row = (
        f"<tr><td style='padding:6px 0;color:#6b6b74'>Оценка</td>"
        f"<td style='padding:6px 0;font-weight:600'>{score} / 100</td></tr>"
        if score is not None
        else ""
    )
    safe_candidate = escape(candidate_name)
    safe_test = escape(test_name)
    safe_company = escape(company_name or "InterviewLab")
    message = (
        escape(custom_message.strip()).replace("\n", "<br>")
        if custom_message.strip()
        else content["body"]
    )
    extra = ""
    if decision == "interview":
        extra = _meeting_block(meeting_url, meeting_at)
    elif decision == "hired":
        extra = _contact_block(contact_name, contact_details)

    html = f"""
<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;color:#09090b">
  <h2 style="margin:24px 0 4px">{content['heading']}</h2>
  <p style="color:#6b6b74;margin:0 0 12px">Здравствуйте, {safe_candidate}!</p>
  <p style="color:#6b6b74;margin:0 0 20px;line-height:1.6">{message}</p>
  {extra}
  <table style="width:100%;border-top:1px solid #e6e6e9;border-bottom:1px solid #e6e6e9">
    <tr><td style="padding:6px 0;color:#6b6b74">Тест</td><td style="padding:6px 0;font-weight:600">{safe_test}</td></tr>
    <tr><td style="padding:6px 0;color:#6b6b74">Затраченное время</td><td style="padding:6px 0;font-weight:600">{minutes}</td></tr>
    {score_row}
  </table>
  <p style="color:#a1a1aa;font-size:12px;margin-top:20px">{safe_company} · отправлено через InterviewLab</p>
</div>
"""
    subject = (custom_subject.strip() or content["subject"]).replace("\r", " ").replace("\n", " ")
    return subject, html


def build_invitation_email(
    test_name: str,
    invite_url: str,
    duration_min: int,
    company_name: str = "InterviewLab",
    custom_message: str = "",
) -> str:
    safe_test = escape(test_name)
    safe_company = escape(company_name or "InterviewLab")
    intro = (
        escape(custom_message.strip()).replace("\n", "<br>")
        if custom_message.strip()
        else "Приглашаем вас пройти техническое тестирование. "
        "Тест проходит прямо в браузере — ничего устанавливать не нужно."
    )
    return f"""
<div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;color:#09090b">
  <h2 style="margin:24px 0 12px">Приглашение на технический тест</h2>
  <p style="color:#6b6b74;margin:0 0 20px;line-height:1.6">{intro}</p>
  <table style="width:100%;border-top:1px solid #e6e6e9;border-bottom:1px solid #e6e6e9">
    <tr><td style="padding:8px 0;color:#6b6b74">Тест</td><td style="padding:8px 0;font-weight:600">{safe_test}</td></tr>
    <tr><td style="padding:8px 0;color:#6b6b74">Длительность</td><td style="padding:8px 0;font-weight:600">{duration_min} минут</td></tr>
  </table>
  <p style="margin:28px 0">
    <a href="{invite_url}"
       style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;
              padding:14px 28px;font-weight:600;border-radius:4px">Начать тест</a>
  </p>
  <p style="color:#a1a1aa;font-size:12px;margin:0 0 4px">Если кнопка не работает, откройте ссылку:</p>
  <p style="color:#2563eb;font-size:12px;word-break:break-all;margin:0">{invite_url}</p>
  <p style="color:#a1a1aa;font-size:12px;margin-top:24px">{safe_company} · отправлено через InterviewLab</p>
</div>
"""


def smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_pass)


def _send_sync(
    to: str, subject: str, html: str, from_name: str = "InterviewLab", reply_to: str = ""
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    from_address = parseaddr(settings.email_from)[1] or settings.smtp_user
    message["From"] = formataddr((str(Header(from_name or "InterviewLab", "utf-8")), from_address))
    message["To"] = to
    if reply_to:
        message["Reply-To"] = reply_to
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


def _send_bulk_sync(
    recipients: list[str], subject: str, html: str, from_name: str, reply_to: str
) -> None:
    """Разослать одно письмо списку адресов за одно подключение к SMTP.

    Логин к Gmail занимает секунды, поэтому переподключаться на каждого
    получателя нельзя — запрос успевал отвалиться по таймауту.
    """
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=30)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with server:
        if settings.smtp_port != 465:
            server.starttls(context=context)
        server.login(settings.smtp_user, settings.smtp_pass)
        for to in recipients:
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            from_address = parseaddr(settings.email_from)[1] or settings.smtp_user
            message["From"] = formataddr(
                (str(Header(from_name or "InterviewLab", "utf-8")), from_address)
            )
            message["To"] = to
            if reply_to:
                message["Reply-To"] = reply_to
            message.attach(MIMEText(html, "html", "utf-8"))
            server.sendmail(settings.smtp_user, [to], message.as_string())


async def send_bulk_email(
    recipients: list[str],
    subject: str,
    html: str,
    from_name: str = "InterviewLab",
    reply_to: str = "",
) -> None:
    if not recipients:
        return
    if not smtp_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Отправка почты не настроена: заполните SMTP_HOST, SMTP_USER и SMTP_PASS в backend/.env",
        )
    try:
        await asyncio.to_thread(_send_bulk_sync, recipients, subject, html, from_name, reply_to)
        logger.info("Sent %s emails: %s", len(recipients), subject)
    except smtplib.SMTPAuthenticationError as exc:
        logger.exception("SMTP auth failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "SMTP не принял логин/пароль. Для Gmail нужен «пароль приложения».",
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        logger.exception("SMTP bulk send failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Не удалось отправить письмо: {exc}",
        ) from exc


async def send_email(
    to: str,
    subject: str,
    html: str,
    from_name: str = "InterviewLab",
    reply_to: str = "",
) -> None:
    if not smtp_configured():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Отправка почты не настроена: заполните SMTP_HOST, SMTP_USER и SMTP_PASS в backend/.env",
        )
    try:
        await asyncio.to_thread(_send_sync, to, subject, html, from_name, reply_to)
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
