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

from ..models import Connection, Course, CourseEnrollment, Notification, Profile
from ..services.streams import is_in_camp_active, lifecycle, lifecycle_blocked

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
# EMAIL + NOTIFICATIONS  (implemented once in services/notify.py)
# ═══════════════════════════════════════════════════════════════════════════════
from ..services import notify as _svc


def _send_email_async(subject, message, recipient_list, from_email=None, fail_silently=False, html_message=None):
    return _svc.send_email_async(subject, message, recipient_list, from_email=from_email,
                                 fail_silently=fail_silently, html_message=html_message)


def _send_email(subject, message, recipient_list, from_email=None, html_message=None):
    return _svc.send_email(subject, message, recipient_list, from_email=from_email, html_message=html_message)


def _notify_admins(title, message, reason="admin_update", created_by_role="", link=""):
    _svc.notify_admins(title, message, reason=reason, created_by_role=created_by_role, link=link)


def _notify_admins_email(subject, message, html_message=None, email_type="general", from_email=None):
    """email_type "payment" → Dunis admins only; anything else → SAED + Dunis admins."""
    try:
        roles = ["dunis_admin"] if email_type == "payment" else ["saed_admin", "dunis_admin"]
        emails = [e for e in Profile.objects.filter(role__in=roles).values_list("user__email", flat=True) if e]
        if emails:
            _send_email_async(subject=subject, message=message, recipient_list=emails,
                              html_message=html_message, from_email=from_email)
    except Exception as exc:
        _log_error("Failed to send admin email", exc=exc, extra={"subject": subject})


def _notify_user(user, title, message, reason="user_update", created_by_role=None, link="", email=False):
    return _svc.notify(user, title, message, reason=reason, link=link, email=email,
                       created_by_role=created_by_role or "")


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
from rest_framework.exceptions import NotAuthenticated, PermissionDenied


def _raise_if_stream_over(request):
    """Expired In-Camp accounts are switched off server-side (not just hidden in the UI)."""
    msg = lifecycle_blocked(request)
    if msg:
        raise PermissionDenied(msg, code="stream_expired")


class IsAuthenticatedAPI(BasePermission):
    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            _raise_if_stream_over(request)
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
            _raise_if_stream_over(request)
            return True
    _HasRole.__name__ = f"HasRole_{'_'.join(roles)}"
    _HasRole.roles = tuple(roles)
    return _HasRole


def HasRoleTrack(role, track):
    """HasRole(role) plus a programme check: In-Camp and Post-Camp accounts never reach each other's features."""
    base = HasRole(role)

    class _HasRoleTrack(base):
        def has_permission(self, request, view):
            if not super().has_permission(request, view):
                return False
            from ..services.streams import track_of
            if track_of(request.user) != track:
                label = "Post-Camp" if track == "post_camp" else "In-Camp"
                raise PermissionDenied(f"This feature belongs to the {label} programme.", code="wrong_track")
            return True
    _HasRoleTrack.__name__ = f"HasRoleTrack_{role}_{track}"
    return _HasRoleTrack


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
def _public_media_base(request=None):
    """Absolute origin for PUBLIC media (profile pictures). Backend host, never the SPA."""
    explicit = (
        getattr(django_settings, "MEDIA_PUBLIC_URL", None)
        or getattr(django_settings, "BACKEND_URL", None)
        or getattr(django_settings, "PUBLIC_API_URL", None)
        or ""
    )
    explicit = (explicit or "").rstrip("/")
    if explicit:
        return explicit
    if request is not None:
        return f"{request.scheme}://{request.get_host()}".rstrip("/")
    return ""


def _letter_payload(user, p, request=None):
    """Letters are never public URLs: they are streamed in-app through an authenticated endpoint.

    The URL is ABSOLUTE (API host), like every other media URL: when the web app and the API are on different hosts a
    relative path would be requested from the web app's own host and come back as that site's HTML page."""
    from ..services import media as _media
    info = _media.letter_info(p)
    has = bool(p and p.partnership_letter)
    path = f"/api/users/{user.id}/partnership-letter/"
    return {"partnershipLetter": f"{_public_media_base(request)}{path}" if has else None,
            "partnershipLetterName": info["name"], "partnershipLetterKind": info["kind"],
            "partnershipLetterAvailable": info["available"]}


def _media_url(path, request=None):
    """Absolute URL for a stored PUBLIC media path (or an already-absolute URL)."""
    if not path:
        return None
    path = str(path).strip()
    if path.startswith("http://") or path.startswith("https://"):
        return path
    media_prefix = (getattr(django_settings, "MEDIA_URL", "/media/") or "/media/").rstrip("/")
    if path.startswith(media_prefix + "/") or path == media_prefix:
        relative = path
    elif path.startswith("/"):
        relative = path
    else:
        relative = f"{media_prefix}/{path.lstrip('/')}"
    if not relative.startswith("/"):
        relative = "/" + relative
    base = _public_media_base(request)
    return f"{base}{relative}" if base else relative


def _has_payout(profile):
    return bool(profile and (profile.paystack_subaccount_code or (profile.account_number and profile.bank_code)))


def user_payload(user, request=None, lifecycle_info=False):
    profile = getattr(user, "profile", None)
    p = profile
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "fullName": user.get_full_name() or user.username,
        "role": p.role if p else "corps_member",
        "phone": p.phone if p else "",
        "nyscStateCode": p.nysc_state_code if p else "",
        "stateOfDeployment": p.state_of_deployment if p else "",
        "stateOfOrigin": p.state_of_origin if p else "",
        "lgaOfDeployment": p.lga_of_deployment if p else "",
        "skillInterest": p.skill_interest if p else "",
        "skillInterests": p.skill_interests if p else [],
        "isActive": user.is_active,
        "isAuthorized": p.is_authorized if p else False,
        "hasPaid": p.has_paid if p else False,
        "specialization": p.specialization if p else "",
        "partnerLgas": p.partner_lgas if p else [],
        "yearsExperience": p.years_experience if p else 0,
        "bio": p.bio if p else "",
        "companyName": p.company_name if p else "",
        "numberTrained": p.number_trained if p else 0,
        "isVerified": p.is_verified if p else False,
        "hasSelectedTrainers": p.has_selected_trainers if p else False,
        "authorizationStatus": p.authorization_status if p else "pending",
        "isEmailVerified": p.is_email_verified if p else False,
        "isBusyCorper": p.is_busy_corper if p else False,
        "paymentVerified": p.payment_verified if p else False,
        "paymentReference": p.payment_reference if p else "",
        "profilePicture": _media_url(p.profile_picture.name if p and p.profile_picture else None, request),
        **_letter_payload(user, p, request),
        "isRestricted": p.authorization_status == "restricted" if p else False,
        "restrictedById": p.restricted_by_id if p else None,
        "restrictedAt": p.restricted_at.isoformat() if p and p.restricted_at else None,
        "ppa": p.ppa if p else "",
        "accountMode": p.account_mode if p else "post_camp",
        "track": p.account_mode if p and p.account_mode == "in_camp" else "post_camp",
        "orientationCampId": p.orientation_camp_id if p else None,
        "inCampAccessActive": (is_in_camp_active(user) if lifecycle_info else p.in_camp_access_active)
        if p and p.account_mode == "in_camp" else True,
        # Stream window (computed per account, so only requested for the signed-in user, never in bulk lists).
        "lifecycle": lifecycle(user) if lifecycle_info and p and p.role in ("corps_member", "trainer") else None,
        "bankName": p.bank_name if p else "",
        "bankCode": p.bank_code if p else "",
        "accountNumber": p.account_number if p else "",
        "accountName": p.account_name if p else "",
        "bankVerified": p.bank_verified if p else False,
        "paystackSubaccountCode": p.paystack_subaccount_code if p else "",
        "hasPayoutAccount": _has_payout(p),
    }


def trainer_public_payload(user, request=None, profile=None):
    """What corps members may see about a trainer (no bank/contact secrets)."""
    p = profile or getattr(user, "profile", None)
    return {
        "id": user.id,
        "fullName": user.get_full_name() or user.email,
        "email": user.email,
        "specialization": p.specialization if p else "",
        "partnerLgas": (p.partner_lgas if p else []) or [],
        "yearsExperience": p.years_experience if p else 0,
        "bio": p.bio if p else "",
        "companyName": p.company_name if p else "",
        "numberTrained": p.number_trained if p else 0,
        "profilePicture": _media_url(p.profile_picture.name if p and p.profile_picture else None, request),
        "isVerified": bool(p and p.is_verified),
        "authorizationStatus": p.authorization_status if p else "pending",
        "stateOfDeployment": p.state_of_deployment if p else "",
        "lgaOfDeployment": p.lga_of_deployment if p else "",
        "ppa": p.ppa if p else "",
    }


def _category_label(key):
    from ..models import SKILL_AREAS
    return dict(SKILL_AREAS).get(key, key or "")


def skill_key(value):
    """Map a skill label or key ("Agro-Allied", "agro_allied", "ICT") to its canonical key, or "" if unknown."""
    import re
    from ..models import SKILL_AREAS
    norm = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())  # noqa: E731
    want = norm(value)
    if not want:
        return ""
    for key, label in SKILL_AREAS:
        if want in (norm(key), norm(label)):
            return key
    return ""


def profile_skill_keys(profile):
    """A corps member's skill set as ordered, de-duplicated canonical keys (multi-select first, legacy single value too)."""
    if profile is None:
        return []
    raw = list(profile.skill_interests or []) if isinstance(profile.skill_interests, (list, tuple)) else []
    raw.append(profile.skill_interest)
    keys = []
    for item in raw:
        k = skill_key(item)
        if k and k not in keys:
            keys.append(k)
    return keys


def annotate_courses(qs):
    """Attach lesson/enrolment counts as correlated sub-selects (one query, no join explosion on listings)."""
    from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
    from django.db.models.functions import Coalesce
    from ..models import CourseEnrollment, Lesson

    def sub(model, **flt):
        rows = model.objects.filter(course=OuterRef("pk"), **flt).order_by().values("course").annotate(n=Count("pk")).values("n")
        return Coalesce(Subquery(rows, output_field=IntegerField()), Value(0))

    return qs.select_related("trainer", "trainer__profile", "orientation_camp", "stream").annotate(
        _lesson_count=sub(Lesson, is_published=True),
        _paid_count=sub(Lesson, is_published=True, is_locked=True, price__gt=0),
        _enrolled_count=sub(CourseEnrollment, status="confirmed"),
    )


def attach_course_counts(courses):
    """Batch the per-course counts for an already-fetched page of courses (3 queries total, not 3 per course)."""
    from django.db.models import Count, Q
    from ..models import CourseEnrollment, Lesson
    courses = [c for c in courses if c is not None and not hasattr(c, "_lesson_count")]
    if not courses:
        return
    ids = [c.id for c in courses]
    lessons = {r["course_id"]: r for r in Lesson.objects.filter(course_id__in=ids, is_published=True).values("course_id").annotate(
        n=Count("id"), paid=Count("id", filter=Q(is_locked=True, price__gt=0)))}
    enrolled = {r["course_id"]: r["n"] for r in CourseEnrollment.objects.filter(course_id__in=ids, status="confirmed")
                .values("course_id").annotate(n=Count("id"))}
    for c in courses:
        row = lessons.get(c.id)
        c._lesson_count = row["n"] if row else 0
        c._paid_count = row["paid"] if row else 0
        c._enrolled_count = enrolled.get(c.id, 0)


def progress_for(user, course_ids):
    """{course_id: progress dict} for many courses in two queries."""
    from ..models import Lesson, LessonProgress
    course_ids = list(course_ids)
    lessons = {}
    for lid, cid in Lesson.objects.filter(course_id__in=course_ids, is_published=True).values_list("id", "course_id"):
        lessons.setdefault(cid, []).append(lid)
    all_ids = [l for ls in lessons.values() for l in ls]
    done = set(LessonProgress.objects.filter(student=user, lesson_id__in=all_ids).values_list("lesson_id", flat=True))
    out = {}
    for cid in course_ids:
        ls = lessons.get(cid, [])
        d = sorted(l for l in ls if l in done)
        out[cid] = {"totalLessons": len(ls), "completedLessons": len(d),
                    "percentage": round(len(d) / len(ls) * 100) if ls else 0, "completedLessonIds": d}
    return out


def course_payload(course, request=None):
    trainer = course.trainer
    lesson_count = getattr(course, "_lesson_count", None)
    if lesson_count is None:
        lessons = course.lessons.filter(is_published=True)
        lesson_count = lessons.count()
        paid_count = lessons.filter(is_locked=True, price__gt=0).count()
        enrolled = course.enrollments.filter(status="confirmed").count()
    else:
        paid_count, enrolled = course._paid_count, course._enrolled_count
    camp = course.orientation_camp
    return {
        # Public identifier (UUID). Legacy integer ids are still ACCEPTED by the API.
        "id": str(course.public_id),
        "trainerId": course.trainer_id,
        "trainerName": (trainer.get_full_name() or trainer.email) if trainer else None,
        "trainer": trainer_public_payload(trainer, request) if trainer else None,
        "title": course.title,
        "description": course.description,
        "category": course.category,
        "categoryLabel": _category_label(course.category),
        "durationWeeks": course.duration_weeks,
        "location": course.location,
        "startDate": course.start_date.isoformat() if course.start_date else None,
        "endDate": course.end_date.isoformat() if course.end_date else None,
        "maxStudents": course.max_students,
        "enrolledCount": enrolled,
        "availableSlots": max(course.max_students - enrolled, 0),
        "isActive": course.is_active,
        "isRestricted": course.is_restricted,
        "restrictedById": course.restricted_by_id,
        "restrictedAt": course.restricted_at.isoformat() if course.restricted_at else None,
        "createdAt": course.created_at.isoformat(),
        "courseType": course.course_type,
        "orientationCampId": course.orientation_camp_id,
        "orientationCamp": {"id": camp.id, "name": camp.name, "state": camp.state,
                            "startDate": camp.start_date.isoformat(), "endDate": camp.end_date.isoformat()} if camp else None,
        "learningObjectives": course.learning_objectives or [],
        "prerequisites": course.prerequisites or "",
        "trainingLocation": course.training_location or "",
        "trainingLga": course.training_lga or "",
        "trainingState": course.training_state or "",
        "isPublished": course.is_published,
        "streamId": course.stream_id,
        "stream": {"id": course.stream.id, "name": course.stream.name, "year": course.stream.year,
                   "number": course.stream.number} if course.stream_id else None,
        "approvalStatus": course.approval_status,
        "reviewNote": course.review_note or "",
        "lessonCount": lesson_count,
        "paidLessonCount": paid_count,
        "freeLessonCount": max(lesson_count - paid_count, 0),
    }


def program_payload(course):
    """Legacy 'program' shape used by the public programmes pages and admin editor."""
    payload = course_payload(course)
    payload["capacity"] = course.max_students
    payload["hasPublicPage"] = True
    return payload


def application_payload(enrollment, progress=None):
    """Enrolment in the shape the legacy 'applications' screens expect (pass `progress` to avoid per-row queries)."""
    from ..models import Lesson, LessonProgress
    if progress is not None:
        total, completed = progress["totalLessons"], progress["completedLessons"]
    else:
        total = Lesson.objects.filter(course=enrollment.course, is_published=True).count()
        completed = LessonProgress.objects.filter(
            student=enrollment.student, lesson__course=enrollment.course, lesson__is_published=True
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
    return {"id": user.id, "fullName": user.get_full_name() or user.email or user.username, "email": user.email}


def trainers_payload():
    trainers = User.objects.select_related("profile").filter(
        is_active=True, profile__role="trainer", profile__is_authorized=True,
    ).order_by("first_name", "last_name", "email")
    return [trainer_payload(u) for u in trainers]


def managed_programs_for(user):
    courses = Course.objects.select_related("trainer", "trainer__profile")
    return courses.filter(trainer=user) if role_for(user) == "trainer" else courses


def managed_applications_for(user):
    qs = CourseEnrollment.objects.select_related("student", "student__profile", "course", "course__trainer")
    if role_for(user) == "trainer":
        qs = qs.filter(course__trainer=user)
    return list(qs)


def trainer_program_payload(course):
    enrollments = CourseEnrollment.objects.filter(course=course).select_related(
        "student", "student__profile", "course", "course__trainer")
    payload = program_payload(course)
    payload["applications"] = [application_payload(item) for item in enrollments]
    return payload


def connection_payload(connection):
    cm, tr = connection.corps_member, connection.trainer
    return {
        "id": connection.id,
        "corpsMember": {"id": cm.id, "fullName": cm.get_full_name() or cm.email, "email": cm.email},
        "trainer": {"id": tr.id, "fullName": tr.get_full_name() or tr.email, "email": tr.email},
        "status": connection.status,
        "connectedAt": connection.connected_at.isoformat(),
        "completedAt": connection.completed_at.isoformat() if connection.completed_at else None,
    }


def lesson_payload(lesson, request=None, user=None, state=None, include_content=True, manage=False):
    """Serialise a lesson.

    `state` comes from services.access.lesson_state. Content (video/document/text) is only
    included when the viewer has access (or `manage`, i.e. the owning trainer/admin).
    Raw storage paths are never returned: files are exposed as short-lived signed stream URLs.
    """
    from ..services import media
    has_access = True if manage else bool(state and state.get("hasAccess"))
    data = {
        "id": lesson.id,
        "courseId": str(lesson.course.public_id),
        "title": lesson.title,
        "description": lesson.description,
        "contentType": lesson.content_type,
        "durationSeconds": lesson.duration_seconds,
        "order": lesson.order,
        "isPublished": lesson.is_published,
        "scheduledDate": lesson.scheduled_date.isoformat() if lesson.scheduled_date else None,
        "scheduledTime": lesson.scheduled_time.isoformat() if lesson.scheduled_time else None,
        "price": str(lesson.price or 0),
        "isLocked": bool(lesson.is_locked),
        "requiresPayment": lesson.requires_payment(),
        "isFree": not lesson.requires_payment(),
        "hasVideo": lesson.has_video,
        "hasDocument": lesson.has_document,
        "hasText": bool(lesson.text_content),
        "videoUploadPaid": bool(lesson.video_upload_paid),
        "state": "owner" if manage else (state or {}).get("state", "locked"),
        "hasAccess": has_access,
        "createdAt": lesson.created_at.isoformat() if lesson.created_at else None,
        "video": None, "document": None, "textContent": "",
    }
    if include_content and has_access and user is not None:
        data["video"] = media.media_descriptor(request, user, lesson, "video")
        data["document"] = media.media_descriptor(request, user, lesson, "document")
        data["textContent"] = lesson.text_content or ""
    if manage:
        # editing aid: the external link (if any) the trainer pasted
        data["videoLink"] = lesson.video_url
        data["documentLink"] = lesson.document_url
        data["videoFileName"] = lesson.video_file.name.rsplit("/", 1)[-1] if lesson.video_file else ""
        data["documentFileName"] = lesson.document_file.name.rsplit("/", 1)[-1] if lesson.document_file else ""
    return data


def ensure_trainer_connection(corps_member, trainer, status="active"):
    """Auto-connect a corps member to a trainer (enrolment / lesson purchase). Idempotent."""
    if not corps_member or not trainer or corps_member.id == getattr(trainer, "id", None):
        return None
    conn, created = Connection.objects.get_or_create(
        corps_member=corps_member, trainer=trainer, defaults={"status": status})
    if not created and conn.status in ("pending", "cancelled"):
        conn.status = status
        conn.save(update_fields=["status"])
    conn._created = created
    return conn


def paginate(request, queryset_or_list, default_size=12, max_size=60):
    """→ (page_items, pagination dict). Works for querysets and lists."""
    try:
        size = min(max(int(request.GET.get("pageSize", default_size)), 1), max_size)
    except (TypeError, ValueError):
        size = default_size
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1
    total = queryset_or_list.count() if hasattr(queryset_or_list, "count") and not isinstance(queryset_or_list, list) else len(queryset_or_list)
    pages = max((total + size - 1) // size, 1)
    page = min(page, pages)
    start = (page - 1) * size
    return queryset_or_list[start:start + size], {"page": page, "pageSize": size, "total": total, "totalPages": pages}


from django.conf import settings as _settings
# --- Public image upload (profile pictures / course covers) ---
#
# Videos and documents are NOT accepted here: they go through the lesson upload
# endpoint (private storage, upload-fee enforcement, access-controlled streaming).

import os
from django.utils.text import get_valid_filename
from rest_framework.views import APIView as _APIView
from rest_framework.response import Response as _Response
from rest_framework import status as _status

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB



class MediaUploadView(_APIView):
    """Accept an IMAGE upload, store under MEDIA_ROOT/uploads/images, return its absolute URL."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        file = request.FILES.get("file")
        if not file:
            return _Response({"error": "No file provided."}, status=_status.HTTP_400_BAD_REQUEST)
        ext = os.path.splitext(file.name)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            return _Response(
                {"error": "Only image files can be uploaded here. Upload lesson videos and documents from the lesson editor."},
                status=_status.HTTP_400_BAD_REQUEST)
        if file.size > MAX_IMAGE_SIZE:
            return _Response({"error": "Image too large. Max 10 MB."}, status=_status.HTTP_400_BAD_REQUEST)
        head = file.read(16)
        file.seek(0)
        from ..services.media import image_magic_ok
        if not image_magic_ok(ext, head):
            return _Response({"error": "The file is not a valid image."}, status=_status.HTTP_400_BAD_REQUEST)

        safe_name = get_valid_filename(file.name)
        unique_name = f"{int(now().timestamp())}_{safe_name}"
        dest_dir = _settings.MEDIA_ROOT / "uploads" / "images"
        os.makedirs(dest_dir, exist_ok=True)
        with open(dest_dir / unique_name, "wb+") as dest:
            for chunk in file.chunks():
                dest.write(chunk)
        relative = f"{_settings.MEDIA_URL}uploads/images/{unique_name}".replace("//", "/")
        if not relative.startswith("/"):
            relative = "/" + relative
        return _Response({"ok": True, "url": _media_url(relative, request), "path": relative, "name": safe_name})
