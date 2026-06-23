"""
Shared helpers, decorators, utilities, constants, and payload builders.
"""

import json
import logging
import threading
from io import BytesIO
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import JsonResponse, QueryDict
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.utils.timezone import now

from ..models import (
    Application, Connection, Course, CourseEnrollment,
    Notification, Profile, Program
)

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════════════════
logger = logging.getLogger(__name__)


def _log_error(msg, exc=None, extra=None):
    if exc:
        logger.exception(msg, extra=extra)
    else:
        logger.error(msg, extra=extra)


def _log_info(msg, extra=None):
    logger.info(msg, extra=extra)


def _log_warning(msg, extra=None):
    logger.warning(msg, extra=extra)


# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC EMAIL
# ═══════════════════════════════════════════════════════════════════════════════
def _send_email_async(subject, message, recipient_list, from_email=None,
                      fail_silently=False, html_message=None):
    def _send():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email or getattr(
                    django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"
                ),
                recipient_list=recipient_list,
                fail_silently=fail_silently,
                html_message=html_message,
            )
            _log_info(f"Email sent to {recipient_list}", extra={"subject": subject})
        except Exception as exc:
            _log_error(f"Failed to send email to {recipient_list}", exc=exc,
                       extra={"subject": subject, "recipients": recipient_list})

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _notify_admins(title, message, reason="admin_update", program=None,
                   created_by_role=""):
    try:
        admin_profiles = Profile.objects.filter(
            role__in=["saed_admin", "dunis_admin"]
        ).select_related("user")
        notifications = []
        for profile in admin_profiles:
            notifications.append(Notification(
                user=profile.user, title=title, message=message,
                reason=reason, program=program, created_by_role=created_by_role,
            ))
        if notifications:
            Notification.objects.bulk_create(notifications)
            _log_info(f"Created {len(notifications)} admin notifications",
                       extra={"title": title, "reason": reason})
    except Exception as exc:
        _log_error("Failed to create admin notifications", exc=exc,
                   extra={"title": title})


def _notify_user(user, title, message, reason="user_update", program=None):
    try:
        Notification.objects.create(
            user=user, title=title, message=message, reason=reason, program=program,
        )
        _log_info(f"Notification created for user {user.id}",
                   extra={"title": title, "reason": reason})
    except Exception as exc:
        _log_error(f"Failed to notify user {user.id}", exc=exc, extra={"title": title})


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════
PROGRAM_FIELDS = {
    "title": "title", "category": "category", "description": "description",
    "durationWeeks": "duration_weeks", "capacity": "capacity",
    "location": "location", "isActive": "is_active",
}

VALID_ROLES = {"corps_member", "trainer", "saed_admin", "dunis_admin"}
VALID_APPLICATION_STATUSES = {"approved", "declined", "completed"}
VALID_AUTH_STATUSES = {"pending", "approved", "declined", "removed"}


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def read_json(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log_warning("Invalid JSON in request body", extra={"error": str(exc)})
        return {}


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError) as exc:
        _log_warning(f"Date parse failed: {value}", extra={"error": str(exc)})
        return None


def _resolve_course_dates(data):
    start = _parse_date(data.get("startDate"))
    end = _parse_date(data.get("endDate"))
    weeks = data.get("durationWeeks")
    try:
        weeks = int(weeks) if weeks else None
    except (TypeError, ValueError):
        weeks = None
    if start and end and not weeks:
        delta = (end - start).days
        data["durationWeeks"] = max(1, round(delta / 7)) if delta > 0 else 4
    elif start and weeks and not end:
        data["endDate"] = (start + timedelta(weeks=weeks)).isoformat()
    elif end and weeks and not start:
        data["startDate"] = (end - timedelta(weeks=weeks)).isoformat()
    return data


def _parse_multipart(request):
    if request.content_type and "multipart/form-data" in request.content_type:
        if request.method == "POST":
            return request.POST, request.FILES
        else:
            body = request.body
            meta = request.META.copy()
            meta["CONTENT_LENGTH"] = str(len(body))
            try:
                parser = MultiPartParser(
                    meta, BytesIO(body), request.upload_handlers, request.encoding
                )
                return parser.parse()
            except MultiPartParserError as exc:
                _log_error("Multipart parse failed", exc=exc)
                return QueryDict("", encoding=request.encoding), None
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# DRF PERMISSION CLASSES
# ═══════════════════════════════════════════════════════════════════════════════
from rest_framework.permissions import BasePermission


class IsAuthenticatedAPI(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated


class HasRole(BasePermission):
    def __init__(self, *roles):
        self.roles = roles

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return role_for(request.user) in self.roles


class IsAuthorizedTrainer(BasePermission):
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user_role = role_for(request.user)
        if user_role != "trainer":
            return True
        profile = getattr(request.user, "profile", None)
        if not profile:
            return False
        if not profile.is_authorized:
            return False
        if not profile.has_paid or not profile.payment_verified:
            return False
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY DECORATORS (kept for backward compat during transition)
# ═══════════════════════════════════════════════════════════════════════════════
def role_for(user):
    profile = getattr(user, "profile", None)
    return profile.role if profile else "corps_member"


def validation_error(message, fields=None, status=400):
    _log_warning(f"Validation error: {message}", extra={"fields": fields})
    return JsonResponse(
        {"error": message, "fields": fields or {}}, status=status
    )


def clean_email(value):
    if not value:
        return ""
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


# ═══════════════════════════════════════════════════════════════════════════════
# PAYLOAD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════
def _media_url(path, request=None):
    if not path:
        return None
    if request:
        return f"{request.scheme}://{request.get_host()}{django_settings.MEDIA_URL}{path}"
    return f"{django_settings.MEDIA_URL}{path}"


def user_payload(user, request=None):
    profile = getattr(user, "profile", None)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "fullName": user.get_full_name() or user.username,
        "role": profile.role if profile else "corps_member",
        "phone": profile.phone if profile else "",
        "nyscStateCode": profile.nysc_state_code if profile else "",
        "stateOfDeployment": profile.state_of_deployment if profile else "",
        "stateOfOrigin": profile.state_of_origin if profile else "",
        "lgaOfDeployment": profile.lga_of_deployment if profile else "",
        "skillInterest": profile.skill_interest if profile else "",
        "skillInterests": profile.skill_interests if profile else [],
        "isActive": user.is_active,
        "isAuthorized": profile.is_authorized if profile else False,
        "hasPaid": profile.has_paid if profile else False,
        "specialization": profile.specialization if profile else "",
        "partnerLgas": profile.partner_lgas if profile else [],
        "yearsExperience": profile.years_experience if profile else 0,
        "bio": profile.bio if profile else "",
        "companyName": profile.company_name if profile else "",
        "numberTrained": profile.number_trained if profile else 0,
        "isVerified": profile.is_verified if profile else False,
        "hasSelectedTrainers": profile.has_selected_trainers if profile else False,
        "authorizationStatus": profile.authorization_status if profile else "pending",
        "isEmailVerified": profile.is_email_verified if profile else False,
        "canUploadFastTrack": profile.can_upload_fast_track if profile else False,
        "isBusyCorper": profile.is_busy_corper if profile else False,
        "paymentVerified": profile.payment_verified if profile else False,
        "paymentReference": profile.payment_reference if profile else False,
        "profilePicture": _media_url(
            profile.profile_picture.name if profile and profile.profile_picture else None, request
        ),
        "partnershipLetter": _media_url(
            profile.partnership_letter.name if profile and profile.partnership_letter else None, request
        ),
        "isRestricted": profile.authorization_status == "restricted" if profile else False,
        "restrictedById": profile.restricted_by_id if profile else None,
        "restrictedAt": profile.restricted_at.isoformat() if profile and profile.restricted_at else None,
    }


def program_payload(program):
    approved_count = program.application_set.filter(status="approved").count()
    return {
        "id": program.id,
        "title": program.title,
        "category": program.category,
        "description": program.description,
        "durationWeeks": program.duration_weeks,
        "capacity": program.capacity,
        "trainerId": program.trainer_id,
        "trainerName": program.trainer_name,
        "location": program.location,
        "availableSlots": max(program.capacity - approved_count, 0),
        "isActive": program.is_active,
        "isRestricted": program.is_restricted,
        "restrictedById": program.restricted_by_id,
        "restrictedAt": program.restricted_at.isoformat() if program.restricted_at else None,
    }


def application_payload(application):
    return {
        "id": application.id,
        "status": application.status,
        "motivation": application.motivation,
        "createdAt": application.created_at.isoformat(),
        "applicant": user_payload(application.applicant),
        "program": program_payload(application.program),
    }


def program_categories_payload():
    return [{"value": v, "label": l} for v, l in Program.CATEGORY_CHOICES]


def trainer_payload(user):
    return {
        "id": user.id,
        "fullName": user.get_full_name() or user.email or user.username,
        "email": user.email,
    }


def trainers_payload():
    trainers = User.objects.select_related("profile").filter(
        is_active=True, profile__role="trainer", profile__is_authorized=True,
    ).order_by("first_name", "last_name", "email")
    return [trainer_payload(u) for u in trainers]


def managed_programs_for(user):
    programs = Program.objects.select_related("trainer")
    user_role = role_for(user)
    if user_role == "trainer":
        return programs.filter(trainer=user)
    if user_role == "saed_admin":
        programs = programs.exclude(
            is_restricted=True, restricted_by__profile__role="dunis_admin"
        )
    return programs


def managed_applications_for(user):
    applications = Application.objects.select_related(
        "applicant", "applicant__profile", "program", "program__trainer"
    )
    if role_for(user) == "trainer":
        return applications.filter(program__trainer=user)
    return applications


def trainer_program_payload(program):
    applications = program.application_set.select_related(
        "applicant", "applicant__profile", "program", "program__trainer"
    )
    payload = program_payload(program)
    payload["applications"] = [application_payload(item) for item in applications]
    return payload


def course_payload(course):
    return {
        "id": course.id,
        "trainerId": course.trainer_id,
        "trainerName": course.trainer.get_full_name() or course.trainer.email,
        "title": course.title,
        "description": course.description,
        "category": course.category,
        "price": str(course.price),
        "durationWeeks": course.duration_weeks,
        "startDate": course.start_date.isoformat() if course.start_date else None,
        "endDate": course.end_date.isoformat() if course.end_date else None,
        "maxStudents": course.max_students,
        "isActive": course.is_active,
        "hasFastTrack": course.has_fast_track,
        "isRestricted": course.is_restricted,
        "restrictedById": course.restricted_by_id,
        "restrictedAt": course.restricted_at.isoformat() if course.restricted_at else None,
        "createdAt": course.created_at.isoformat(),
    }


def connection_payload(connection):
    return {
        "id": connection.id,
        "corpsMember": {
            "id": connection.corps_member.id,
            "fullName": connection.corps_member.get_full_name() or connection.corps_member.email,
            "email": connection.corps_member.email,
        },
        "trainer": {
            "id": connection.trainer.id,
            "fullName": connection.trainer.get_full_name() or connection.trainer.email,
            "email": connection.trainer.email,
        },
        "status": connection.status,
        "connectedAt": connection.connected_at.isoformat(),
        "completedAt": connection.completed_at.isoformat() if connection.completed_at else None,
    }


def fast_track_video_payload(video):
    return {
        "id": video.id,
        "courseId": video.course_id,
        "title": video.title,
        "description": video.description,
        "videoUrl": video.video_url,
        "durationSeconds": video.duration_seconds,
        "order": video.order,
        "price": str(video.price),
        "isFreePreview": video.is_free_preview,
        "createdAt": video.created_at.isoformat(),
    }
