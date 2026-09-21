# saed/views/base.py
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
    Connection, Course, CourseEnrollment,
    Notification, Profile,
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
def _send_email_async(
    subject, message, 
    recipient_list, 
    from_email=None,
    fail_silently=False, 
    html_message=None
    ):
    
    def _send():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=from_email or getattr(
                    django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.ng"
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
def _notify_admins(title, message, reason="admin_update",
                   created_by_role=""):
    try:
        admin_profiles = Profile.objects.filter(
            role__in=["saed_admin", "dunis_admin"]
        ).select_related("user")
        notifications = []
        for profile in admin_profiles:
            notifications.append(Notification(
                user=profile.user, title=title, message=message,
                reason=reason, created_by_role=created_by_role,
            ))
        if notifications:
            Notification.objects.bulk_create(notifications)
            _log_info(f"Created {len(notifications)} admin notifications",
                       extra={"title": title, "reason": reason})
    except Exception as exc:
        _log_error("Failed to create admin notifications", exc=exc,
                   extra={"title": title})


def _notify_admins_email(subject, message, html_message=None,
                         email_type="general", from_email=None):
    """
    Send emails to admin users based on their role and the email type.

    email_type:
      - "trainer"   → both SAED and DUNIS admins (trainer registrations, connections)
      - "payment"   → DUNIS admins only (refunds, payment issues)
      - "general"   → both SAED and DUNIS admins (complaints, general alerts)
    from_email: sender address (defaults to DEFAULT_FROM_EMAIL)
    """
    try:
        if email_type == "payment":
            roles = ["dunis_admin"]
        else:
            roles = ["saed_admin", "dunis_admin"]

        admin_emails = list(
            Profile.objects.filter(role__in=roles)
            .values_list("user__email", flat=True)
        )
        admin_emails = [e for e in admin_emails if e]

        if not admin_emails:
            _log_warning("No admin emails found for notification",
                         extra={"email_type": email_type})
            return

        _send_email_async(
            subject=subject,
            message=message,
            recipient_list=admin_emails,
            html_message=html_message,
            from_email=from_email,
        )
        _log_info(f"Admin email sent to {len(admin_emails)} admins",
                  extra={"subject": subject, "email_type": email_type,
                         "roles": roles})
    except Exception as exc:
        _log_error("Failed to send admin email", exc=exc,
                   extra={"subject": subject, "email_type": email_type})


def _notify_user(user, title, message, reason="user_update", created_by_role=None):
    try:
        Notification.objects.create(
            user=user, title=title, message=message, reason=reason,
            created_by_role=created_by_role or "",
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
    "startDate": "start_date", "endDate": "end_date",
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
from rest_framework.exceptions import NotAuthenticated


class IsAuthenticatedAPI(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        raise NotAuthenticated("Your session has expired. Please sign in again.")


def HasRole(*roles):
    """Factory that returns a DRF permission class checking the user's role."""
    class _HasRole(BasePermission):
        def has_permission(self, request, view):
            if not (request.user and request.user.is_authenticated):
                _log_warning(f"HasRole({roles}): unauthenticated request to {request.path}")
                raise NotAuthenticated("Your session has expired. Please sign in again.")
            user_role = role_for(request.user)
            if user_role not in roles:
                _log_warning(
                    f"HasRole({roles}): user {request.user.id} has role '{user_role}', "
                    f"denied access to {request.path}"
                )
                return False
            return True
    _HasRole.__name__ = f"HasRole_{'_'.join(roles)}"
    return _HasRole


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


class HasTrainerRole(BasePermission):
    """Permission: must be an authorized trainer (is_authorized + has_paid + payment_verified)."""
    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != "trainer":
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


# def _media_url(path, request=None):
#     if not path:
#         return None
#     if request:
#         return f"{request.scheme}://{request.get_host()}{django_settings.MEDIA_URL}{path}"
#     return f"{django_settings.MEDIA_URL}{path}"  # ← falls back to relative path

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


def program_payload(course):
    """Returns a course in the format the frontend expects as a 'program'."""
    trainer = course.trainer
    enrolled_count = CourseEnrollment.objects.filter(course=course, status="confirmed").count()
    return {
        "id": course.id,
        "title": course.title,
        "category": course.category,
        "description": course.description,
        "durationWeeks": course.duration_weeks,
        "capacity": course.max_students,
        "price": str(course.price),
        "trainerId": course.trainer_id,
        "trainerName": (trainer.get_full_name() or trainer.email) if trainer else None,
        "location": course.location,
        "startDate": course.start_date.isoformat() if course.start_date else None,
        "endDate": course.end_date.isoformat() if course.end_date else None,
        "availableSlots": max(course.max_students - enrolled_count, 0),
        "isActive": course.is_active,
        "hasFastTrack": course.has_fast_track,
        "isRestricted": course.is_restricted,
        "restrictedById": course.restricted_by_id,
        "restrictedAt": course.restricted_at.isoformat() if course.restricted_at else None,
    }


def application_payload(enrollment):
    """Returns an enrollment in the format the frontend expects as an 'application'."""
    from ..models import Lesson, LessonProgress
    total = Lesson.objects.filter(module__course=enrollment.course, module__is_active=True).count()
    completed = LessonProgress.objects.filter(
        student=enrollment.student, lesson__module__course=enrollment.course
    ).count()
    return {
        "id": enrollment.id,
        "status": enrollment.status,
        "motivation": f"Payment reference: {enrollment.payment_reference}" if enrollment.payment_reference else "",
        "createdAt": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else "",
        "applicant": user_payload(enrollment.student),
        "program": program_payload(enrollment.course),
        "type": "course_enrollment",
        "amountPaid": str(enrollment.amount_paid),
        "paymentVerified": enrollment.payment_verified,
        "totalLessons": total,
        "completedLessons": completed,
        "progressPercentage": round(completed / total * 100) if total else 0,
    }


def program_categories_payload():
    from ..models import SKILL_AREAS
    return [{"value": v, "label": l} for v, l in SKILL_AREAS]


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
    courses = Course.objects.select_related("trainer", "trainer__profile")
    user_role = role_for(user)
    if user_role == "trainer":
        return courses.filter(trainer=user)
    return courses


def managed_applications_for(user):
    if role_for(user) == "trainer":
        trainer_courses = Course.objects.filter(trainer=user)
        enrollments = CourseEnrollment.objects.filter(
            course__in=trainer_courses
        ).select_related("student", "student__profile", "course", "course__trainer")
        return list(enrollments)
    enrollments = CourseEnrollment.objects.all().select_related(
        "student", "student__profile", "course", "course__trainer"
    )
    return list(enrollments)


def trainer_program_payload(course):
    enrollments = CourseEnrollment.objects.filter(
        course=course
    ).select_related("student", "student__profile", "course", "course__trainer")
    payload = program_payload(course)
    payload["applications"] = [application_payload(item) for item in enrollments]
    return payload


def course_payload(course):
    trainer = course.trainer
    return {
        "id": course.id,
        "trainerId": course.trainer_id,
        "trainerName": (trainer.get_full_name() or trainer.email) if trainer else None,
        "title": course.title,
        "description": course.description,
        "category": course.category,
        "price": str(course.price),
        "durationWeeks": course.duration_weeks,
        "location": course.location,
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


def lesson_payload(lesson):
    return {
        "id": lesson.id,
        "moduleId": lesson.module_id,
        "title": lesson.title,
        "description": lesson.description,
        "contentType": lesson.content_type,
        "videoUrl": lesson.video_url,
        "textContent": lesson.text_content,
        "documentUrl": lesson.document_url,
        "durationSeconds": lesson.duration_seconds,
        "order": lesson.order,
        "isFreePreview": lesson.is_free_preview,
        "createdAt": lesson.created_at.isoformat(),
    }


def module_payload(module):
    return {
        "id": module.id,
        "courseId": module.course_id,
        "title": module.title,
        "description": module.description,
        "order": module.order,
        "isActive": module.is_active,
        "lessonCount": module.lessons.count(),
        "lessons": [lesson_payload(l) for l in module.lessons.all()],
        "createdAt": module.created_at.isoformat(),
    }


# --- Media upload ---

import os
from django.conf import settings as _settings
from django.utils.text import get_valid_filename
from rest_framework.views import APIView as _APIView
from rest_framework.response import Response as _Response
from rest_framework import status as _status

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_DOC_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".ppt", ".pptx", ".xls", ".xlsx"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB


class MediaUploadView(_APIView):
    """Accept a file upload, save it under MEDIA_ROOT, return the URL."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return _Response({"error": "No file provided."}, status=_status.HTTP_400_BAD_REQUEST)

        if file.size > MAX_UPLOAD_SIZE:
            return _Response({"error": "File too large. Max 500 MB."}, status=_status.HTTP_400_BAD_REQUEST)

        ext = os.path.splitext(file.name)[1].lower()
        all_allowed = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_DOC_EXTENSIONS | ALLOWED_IMAGE_EXTENSIONS
        if ext not in all_allowed:
            return _Response(
                {"error": f"Unsupported file type ({ext}). Allowed: {', '.join(sorted(all_allowed))}"},
                status=_status.HTTP_400_BAD_REQUEST,
            )

        if ext in ALLOWED_VIDEO_EXTENSIONS:
            subfolder = "videos"
        elif ext in ALLOWED_DOC_EXTENSIONS:
            subfolder = "documents"
        else:
            subfolder = "images"

        safe_name = get_valid_filename(file.name)
        unique_name = f"{int(now().timestamp())}_{safe_name}"
        dest_dir = _settings.MEDIA_ROOT / "uploads" / subfolder
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = dest_dir / unique_name

        with open(dest_path, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        url = f"{_settings.MEDIA_URL}uploads/{subfolder}/{unique_name}"
        return _Response({"ok": True, "url": url, "name": safe_name})
