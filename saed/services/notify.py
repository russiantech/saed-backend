"""Single place for in-app notifications + email.

Every notification carries a `link` (frontend route) so the UI can take the user
straight to the course / lesson / payment / profile the message is about.
"""
import html
import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from ..models import Notification, Profile

logger = logging.getLogger(__name__)


def frontend_url(path="") -> str:
    base = getattr(settings, "FRONTEND_URL", "http://localhost:3002").rstrip("/")
    return f"{base}{path}" if path else base


def email_html(heading, paragraphs, cta_label=None, cta_path=None, tone="#1a5f2a"):
    body = "".join(f"<p>{html.escape(str(p))}</p>" for p in paragraphs)
    cta = ""
    if cta_label and cta_path:
        cta = (f'<p><a href="{html.escape(frontend_url(cta_path))}" style="background:{tone};color:#fff;'
               f'padding:10px 18px;border-radius:6px;text-decoration:none;display:inline-block;">'
               f'{html.escape(cta_label)}</a></p>')
    return (
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
        f'<div style="background:{tone};padding:20px;border-radius:8px 8px 0 0;">'
        '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
        '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
        f'<h2 style="color:{tone};margin-top:0;">{html.escape(heading)}</h2>{body}{cta}</div></div>'
    )


def send_email_async(subject, message, recipient_list, from_email=None, fail_silently=False, html_message=None):
    recipient_list = [r for r in (recipient_list or []) if r]
    if not recipient_list:
        return None

    def _send():
        try:
            send_mail(
                subject=subject, message=message,
                from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.ng"),
                recipient_list=recipient_list, fail_silently=fail_silently, html_message=html_message,
            )
        except Exception:
            logger.exception("Failed to send email to %s (%s)", recipient_list, subject)

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


def send_email(subject, message, recipient_list, from_email=None, html_message=None) -> bool:
    try:
        return bool(send_mail(
            subject=subject, message=message,
            from_email=from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.ng"),
            recipient_list=recipient_list, fail_silently=False, html_message=html_message,
        ))
    except Exception:
        logger.exception("Failed to send email to %s", recipient_list)
        return False


def notify(user, title, message, *, reason="user_update", link="", email=True,
           created_by_role="", cta_label=None, email_subject=None):
    """Create an in-app notification and (optionally) email the same content."""
    if user is None:
        return None
    try:
        note = Notification.objects.create(
            user=user, title=title[:200], message=message, reason=reason,
            link=link or "", created_by_role=created_by_role or "",
        )
    except Exception:
        logger.exception("Failed to create notification for %s", getattr(user, "id", None))
        return None
    if email and getattr(user, "email", ""):
        subject = email_subject or f"SAED IMS - {title}"
        body = email_html(title, [message], cta_label=cta_label or ("Open" if link else None), cta_path=link)
        text = message + (f"\n\nOpen: {frontend_url(link)}" if link else "")
        recipients = [user.email]
        transaction.on_commit(lambda: send_email_async(subject, text, recipients, html_message=body))
    return note


def notify_admins(title, message, *, reason="admin_update", link="", roles=("saed_admin", "dunis_admin"),
                  created_by_role="", email=False):
    try:
        profiles = Profile.objects.filter(role__in=roles).select_related("user")
        notes = [
            Notification(user=p.user, title=title[:200], message=message, reason=reason,
                         link=link or "", created_by_role=created_by_role)
            for p in profiles
        ]
        if notes:
            Notification.objects.bulk_create(notes)
        if email:
            addrs = [p.user.email for p in profiles if p.user.email]
            body = email_html(title, [message], cta_label="Open" if link else None, cta_path=link)
            transaction.on_commit(lambda: send_email_async(f"SAED IMS - {title}", message, addrs, html_message=body))
    except Exception:
        logger.exception("Failed to notify admins: %s", title)


def course_link(course, lesson_id=None) -> str:
    base = f"/app/courses/{course.public_id}"
    return f"{base}?lesson={lesson_id}" if lesson_id else base
