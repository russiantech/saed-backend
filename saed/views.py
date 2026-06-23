
# v2

"""
SAED IMS API Views
Production-ready with comprehensive error handling, logging, and async operations.
"""

import json
import logging
import re
import threading
import urllib.request
import urllib.error
from io import BytesIO
from datetime import date, timedelta

from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.http import JsonResponse, QueryDict
from django.http.multipartparser import MultiPartParser, MultiPartParserError
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from .models import (
    Application, Complaint, Connection, Course, CourseEnrollment,
    FastTrackVideo, Notification, Profile, Program
)

# ═══════════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════════
logger = logging.getLogger(__name__)


def _log_error(msg, exc=None, extra=None):
    """Centralized error logging with optional exception and extra context."""
    if exc:
        logger.exception(msg, extra=extra)
    else:
        logger.error(msg, extra=extra)


def _log_info(msg, extra=None):
    """Centralized info logging."""
    logger.info(msg, extra=extra)


def _log_warning(msg, extra=None):
    """Centralized warning logging."""
    logger.warning(msg, extra=extra)


# ═══════════════════════════════════════════════════════════════════════════════
# ASYNC EMAIL HELPER (prevents 504 Gateway Timeout)
# ═══════════════════════════════════════════════════════════════════════════════
def _send_email_async(subject, message, recipient_list, from_email=None,
                       fail_silently=False, html_message=None):
    """
    Send email in a background thread to prevent request blocking.
    This eliminates 504 Gateway Timeout caused by slow SMTP servers.
    """
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
            _log_info(f"Email sent successfully to {recipient_list}",
                       extra={"subject": subject})
        except Exception as exc:
            _log_error(
                f"Failed to send email to {recipient_list}",
                exc=exc,
                extra={"subject": subject, "recipients": recipient_list}
            )

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    return thread


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _notify_admins(title, message, reason="admin_update", program=None,
                    created_by_role=""):
    """Create notifications for all admin users."""
    try:
        admin_profiles = Profile.objects.filter(
            role__in=["saed_admin", "dunis_admin"]
        ).select_related("user")
        notifications = []
        for profile in admin_profiles:
            notifications.append(Notification(
                user=profile.user,
                title=title,
                message=message,
                reason=reason,
                program=program,
                created_by_role=created_by_role,
            ))
        if notifications:
            Notification.objects.bulk_create(notifications)
            _log_info(f"Created {len(notifications)} admin notifications",
                       extra={"title": title, "reason": reason})
    except Exception as exc:
        _log_error("Failed to create admin notifications", exc=exc,
                   extra={"title": title})


def _notify_user(user, title, message, reason="user_update", program=None):
    """Create a notification for a specific user."""
    try:
        Notification.objects.create(
            user=user,
            title=title,
            message=message,
            reason=reason,
            program=program,
        )
        _log_info(f"User notification created for user {user.id}",
                   extra={"title": title, "reason": reason})
    except Exception as exc:
        _log_error(f"Failed to create notification for user {user.id}",
                   exc=exc, extra={"title": title})


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS & FIELD MAPPINGS
# ═══════════════════════════════════════════════════════════════════════════════
PROGRAM_FIELDS = {
    "title": "title",
    "category": "category",
    "description": "description",
    "durationWeeks": "duration_weeks",
    "capacity": "capacity",
    "location": "location",
    "isActive": "is_active",
}

VALID_ROLES = {"corps_member", "trainer", "saed_admin", "dunis_admin"}
VALID_APPLICATION_STATUSES = {"approved", "declined", "completed"}
VALID_AUTH_STATUSES = {"pending", "approved", "declined", "removed"}


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def read_json(request):
    """Safely parse JSON from request body."""
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log_warning("Invalid JSON in request body", extra={"error": str(exc)})
        return {}


def _safe_int(value, default=0):
    """Safely convert value to int with fallback."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    """Safely convert value to float with fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_date(value):
    """Parse ISO date string or date object."""
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, TypeError) as exc:
        _log_warning(f"Date parse failed for value: {value}",
                     extra={"error": str(exc)})
        return None


def _resolve_course_dates(data):
    """Auto-resolve course start/end dates and duration."""
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
    """
    Safely parse multipart form data for PATCH requests.
    Django's MultiPartParser only works with POST by default.
    """
    if request.content_type and "multipart/form-data" in request.content_type:
        if request.method == "POST":
            return request.POST, request.FILES
        else:
            body = request.body
            meta = request.META.copy()
            meta["CONTENT_LENGTH"] = str(len(body))
            try:
                parser = MultiPartParser(
                    meta, BytesIO(body), request.upload_handlers,
                    request.encoding
                )
                return parser.parse()
            except MultiPartParserError as exc:
                _log_error("Multipart parse failed", exc=exc)
                return QueryDict("", encoding=request.encoding), None
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
# DECORATORS & PERMISSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def api_login_required(view_func):
    """Require authenticated user for API views."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            _log_warning("Unauthenticated API access attempt",
                        extra={"path": request.path, "method": request.method})
            return JsonResponse(
                {"error": "Authentication required."}, status=401
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def role_for(user):
    """Get user's role from profile."""
    profile = getattr(user, "profile", None)
    return profile.role if profile else "corps_member"


def require_roles(*roles):
    """Decorator to restrict views to specific roles."""
    def decorator(view_func):
        @api_login_required
        def wrapper(request, *args, **kwargs):
            user_role = role_for(request.user)
            if user_role not in roles:
                _log_warning(
                    f"Role access denied: {user_role} not in {roles}",
                    extra={"user_id": request.user.id, "path": request.path}
                )
                return JsonResponse(
                    {"error": "You do not have permission to perform this action."},
                    status=403
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def validation_error(message, fields=None, status=400):
    """Standardized validation error response."""
    _log_warning(f"Validation error: {message}", extra={"fields": fields})
    return JsonResponse(
        {"error": message, "fields": fields or {}}, status=status
    )


def clean_email(value):
    """Normalize and validate email address."""
    if not value:
        return ""
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return ""
    return email


def is_authorized(user):
    """Check if trainer user is fully authorized."""
    profile = getattr(user, "profile", None)
    return profile.is_authorized if profile else False


def require_authorized_trainer(view_func):
    """Decorator for views requiring authorized trainer status."""
    @api_login_required
    def wrapper(request, *args, **kwargs):
        if role_for(request.user) == "trainer":
            profile = getattr(request.user, "profile", None)
            if not profile:
                _log_warning("Trainer without profile access attempt",
                            extra={"user_id": request.user.id})
                return JsonResponse(
                    {"error": "Your account is pending setup.",
                     "authorized": False},
                    status=403,
                )
            if not profile.is_authorized:
                _log_warning("Unauthorized trainer access attempt",
                            extra={"user_id": request.user.id})
                return JsonResponse(
                    {
                        "error": "Your account is pending admin verification. "
                                 "Please wait for SAED admin to review your application.",
                        "authorized": False,
                        "reason": "unverified",
                    },
                    status=403,
                )
            if not profile.has_paid or not profile.payment_verified:
                _log_warning("Unpaid trainer access attempt",
                            extra={"user_id": request.user.id})
                return JsonResponse(
                    {
                        "error": "Your account is pending payment verification. "
                                 "Please complete payment to activate your account.",
                        "authorized": False,
                        "reason": "unpaid",
                    },
                    status=403,
                )
        return view_func(request, *args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════════
# PAYLOAD BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════
def _media_url(path, request=None):
    """Build absolute or relative media URL."""
    if not path:
        return None
    if request:
        return f"{request.scheme}://{request.get_host()}{django_settings.MEDIA_URL}{path}"
    return f"{django_settings.MEDIA_URL}{path}"


def user_payload(user, request=None):
    """Build user payload with profile data."""
    profile = getattr(user, "profile", None)
    payload = {
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
            profile.profile_picture.name if profile and profile.profile_picture else None,
            request
        ),
        "partnershipLetter": _media_url(
            profile.partnership_letter.name if profile and profile.partnership_letter else None,
            request
        ),
        "isRestricted": profile.authorization_status == "restricted" if profile else False,
        "restrictedById": profile.restricted_by_id if profile else None,
        "restrictedAt": profile.restricted_at.isoformat() if profile and profile.restricted_at else None,
    }
    return payload


def program_payload(program):
    """Build program payload with available slots calculation."""
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
    """Build application payload."""
    return {
        "id": application.id,
        "status": application.status,
        "motivation": application.motivation,
        "createdAt": application.created_at.isoformat(),
        "applicant": user_payload(application.applicant),
        "program": program_payload(application.program),
    }


def program_categories_payload():
    """Build program category options."""
    return [
        {"value": value, "label": label}
        for value, label in Program.CATEGORY_CHOICES
    ]


def trainer_payload(user):
    """Build minimal trainer payload."""
    return {
        "id": user.id,
        "fullName": user.get_full_name() or user.email or user.username,
        "email": user.email,
    }


def trainers_payload():
    """Get all authorized trainers."""
    trainers = User.objects.select_related("profile").filter(
        is_active=True,
        profile__role="trainer",
        profile__is_authorized=True,
    ).order_by("first_name", "last_name", "email")
    return [trainer_payload(user) for user in trainers]


def managed_programs_for(user):
    """Get programs manageable by the given user."""
    programs = Program.objects.select_related("trainer")
    user_role = role_for(user)
    if user_role == "trainer":
        return programs.filter(trainer=user)
    if user_role == "saed_admin":
        programs = programs.exclude(
            is_restricted=True,
            restricted_by__profile__role="dunis_admin"
        )
    return programs


def managed_applications_for(user):
    """Get applications manageable by the given user."""
    applications = Application.objects.select_related(
        "applicant", "applicant__profile", "program", "program__trainer"
    )
    if role_for(user) == "trainer":
        return applications.filter(program__trainer=user)
    return applications


def trainer_program_payload(program):
    """Build trainer program payload with applications."""
    applications = program.application_set.select_related(
        "applicant", "applicant__profile", "program", "program__trainer"
    )
    payload = program_payload(program)
    payload["applications"] = [application_payload(item) for item in applications]
    return payload


# ═══════════════════════════════════════════════════════════════════════════════
# BASIC VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
def health(_request):
    """Health check endpoint."""
    return JsonResponse({"status": "ok", "service": "SAED IMS API"})


@ensure_csrf_cookie
def csrf(request):
    """Get CSRF token."""
    return JsonResponse({"csrfToken": get_token(request)})


def me(request):
    """Get current user info."""
    if not request.user.is_authenticated:
        return JsonResponse({"user": None})
    return JsonResponse({"user": user_payload(request.user, request)})


# ═══════════════════════════════════════════════════════════════════════════════
# PROFILE VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_login_required
@require_http_methods(["PATCH"])
def update_profile(request):
    """Update user profile with file upload support."""
    parsed_files = None
    data = None

    # Handle multipart form data for PATCH
    parsed_data, parsed_files = _parse_multipart(request)
    if parsed_data is not None:
        data = parsed_data
    else:
        data = read_json(request)

    user = request.user
    profile = getattr(user, "profile", None)
    if not profile:
        _log_warning("Profile not found during update",
                    extra={"user_id": user.id})
        return JsonResponse({"error": "Profile not found."}, status=404)

    try:
        with transaction.atomic():
            if "fullName" in data:
                full_name = data.get("fullName", "").strip()
                if len(full_name.split()) < 2:
                    return validation_error(
                        "Enter first and last name.",
                        {"fullName": "First and last name are required."}
                    )
                user.first_name = full_name.split(" ", 1)[0]
                user.last_name = full_name.split(" ", 1)[1] if " " in full_name else ""
                user.save(update_fields=["first_name", "last_name"])

            # Profile field updates
            field_mappings = {
                "skillInterest": "skill_interest",
                "skillInterests": "skill_interests",
                "lgaOfDeployment": "lga_of_deployment",
                "phone": "phone",
                "stateOfOrigin": "state_of_origin",
            }

            for frontend_key, model_key in field_mappings.items():
                if frontend_key in data:
                    value = data[frontend_key]
                    if frontend_key == "skillInterests":
                        if isinstance(value, str):
                            try:
                                value = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                value = []
                        profile.skill_interests = value
                        if value:
                            profile.skill_interest = value[0] if value else ""
                    else:
                        setattr(profile, model_key, str(value).strip() if value else "")

            # Trainer-specific fields
            if profile.role == "trainer":
                trainer_fields = {
                    "bio": "bio",
                    "companyName": "company_name",
                    "yearsExperience": "years_experience",
                    "specialization": "specialization",
                    "skillInterest": "specialization",
                    "partnerLgas": "partner_lgas",
                }
                for frontend_key, model_key in trainer_fields.items():
                    if frontend_key in data:
                        value = data[frontend_key]
                        if frontend_key == "partnerLgas":
                            if isinstance(value, str):
                                try:
                                    value = json.loads(value)
                                except (json.JSONDecodeError, TypeError):
                                    value = []
                            profile.partner_lgas = value
                        elif frontend_key == "yearsExperience":
                            profile.years_experience = _safe_int(value, 0)
                        else:
                            setattr(profile, model_key, str(value).strip() if value else "")

            # File uploads
            files = parsed_files if parsed_files is not None else request.FILES
            profile_picture = files.get("profilePicture")
            if profile_picture:
                profile.profile_picture = profile_picture

            partnership_letter = files.get("partnershipLetter")
            if partnership_letter:
                profile.partnership_letter = partnership_letter

            profile.save()
            _log_info(f"Profile updated for user {user.id}")

    except Exception as exc:
        _log_error(f"Profile update failed for user {user.id}", exc=exc)
        return JsonResponse(
            {"error": "Profile update failed. Please try again."},
            status=500
        )

    return JsonResponse({"user": user_payload(user, request)})


# ═══════════════════════════════════════════════════════════════════════════════
# AUTHENTICATION VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@require_POST
def login_view(request):
    """User login with email/username and password."""
    data = read_json(request)
    login_id = data.get("email", "").strip()
    password = data.get("password", "")
    role = data.get("role")

    if not login_id or not password:
        return validation_error(
            "Enter your username/email and password.",
            {
                "email": "Username or email is required.",
                "password": "Password is required.",
            },
        )

    user = None
    authenticated = None

    try:
        # Try email first, then username
        user = User.objects.filter(email__iexact=login_id).first()
        if not user:
            user = User.objects.filter(username__iexact=login_id).first()

        if user:
            authenticated = authenticate(request, username=user.username, password=password)
            if authenticated is None and user.check_password(password):
                authenticated = user
                authenticated.backend = "django.contrib.auth.backends.ModelBackend"
        else:
            authenticated = authenticate(request, username=login_id, password=password)

        if authenticated is None:
            _log_warning("Failed login attempt", extra={"login_id": login_id})
            return JsonResponse(
                {"error": "Invalid username/email or password."}, status=400
            )

        user = authenticated
        profile = getattr(user, "profile", None)
        if role and profile and profile.role != role:
            _log_warning("Role mismatch during login",
                        extra={"user_id": user.id, "expected": role, "actual": profile.role})
            return JsonResponse(
                {"error": "This account is registered for a different role."},
                status=400
            )

        login(request, user)
        _log_info(f"User {user.id} logged in successfully")
        return JsonResponse({"user": user_payload(user, request)})

    except Exception as exc:
        _log_error("Login error", exc=exc, extra={"login_id": login_id})
        return JsonResponse(
            {"error": "Login failed. Please try again."}, status=500
        )


@csrf_exempt
@require_POST
def logout_view(request):
    """User logout."""
    try:
        user_id = request.user.id if request.user.is_authenticated else None
        logout(request)
        _log_info(f"User {user_id} logged out")
        return JsonResponse({"ok": True})
    except Exception as exc:
        _log_error("Logout error", exc=exc)
        return JsonResponse({"ok": True})  # Still return ok, logout is idempotent





@csrf_exempt
@require_POST
def signup_view(request):
    data = read_json(request)
    full_name = data.get("fullName", "").strip()
    username = data.get("username", "").strip()
    email = clean_email(data.get("email", ""))
    password = data.get("password", "")
    role = data.get("role", "corps_member")
    fields = {}

    if not username:
        fields["username"] = "Username is required."
    elif User.objects.filter(username__iexact=username).exists():
        fields["username"] = "This username is already taken."
    if len(full_name.split()) < 2:
        fields["fullName"] = "Enter first and last name."
    if not email:
        fields["email"] = "Enter a valid email address."
    elif User.objects.filter(email__iexact=email).exists():
        fields["email"] = "An account with this email already exists."
    if role != "corps_member":
        fields["role"] = "Public signup is only available for corps members."
    if role == "corps_member":
        if not data.get("phone", "").strip():
            fields["phone"] = "Phone number is required."
        if not data.get("nyscStateCode", "").strip():
            fields["nyscStateCode"] = "NYSC state code is required."
        if not data.get("stateOfDeployment", "").strip():
            fields["stateOfDeployment"] = "State of deployment is required."
        if not data.get("lgaOfDeployment", "").strip():
            fields["lgaOfDeployment"] = "LGA of deployment is required."
        if not data.get("skillInterest", "").strip():
            fields["skillInterest"] = "Skill interest is required."
    try:
        validate_password(password)
    except ValidationError as exc:
        fields["password"] = " ".join(exc.messages)

    if fields:
        return validation_error("Please correct the highlighted fields.", fields)

    try:
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=full_name.split(" ", 1)[0],
            last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
        )
    except IntegrityError:
        return validation_error("An account with this email already exists.", {"email": "Email is already registered."})

    Profile.objects.create(
        user=user,
        role=role,
        phone=data.get("phone", "").strip(),
        nysc_state_code=data.get("nyscStateCode", "").strip(),
        state_of_deployment=data.get("stateOfDeployment", "").strip(),
        state_of_origin=data.get("stateOfOrigin", "").strip(),
        lga_of_deployment=data.get("lgaOfDeployment", "").strip(),
        skill_interest=data.get("skillInterest", "").strip(),
    )
    login(request, user)
    return JsonResponse({"user": user_payload(user, request)}, status=201)


@csrf_exempt
@require_POST
def trainer_signup_view(request):
    """
    Trainer signup with file upload support.
    FIXED: Non-blocking email sending prevents 504 Gateway Timeout.
    FIXED: Proper multipart handling for file uploads.
    FIXED: Comprehensive error logging instead of silent failures.
    FIXED: Transaction atomic for data consistency.
    """
    _log_info("Trainer signup initiated", extra={
        "content_type": request.content_type,
        "method": request.method,
        "path": request.path,
    })

    # Parse request data based on content type
    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.POST
        partner_lgas_raw = data.get("partnerLgas", "[]")
        try:
            partner_lgas = json.loads(partner_lgas_raw)
        except (json.JSONDecodeError, TypeError) as exc:
            _log_warning("Invalid partnerLgas JSON", extra={"raw": partner_lgas_raw})
            partner_lgas = []
    else:
        data = read_json(request)
        partner_lgas = data.get("partnerLgas", [])

    # Extract fields
    full_name = data.get("fullName", "").strip()
    email = clean_email(data.get("email", ""))
    password = data.get("password", "")
    phone = data.get("phone", "").strip()
    specialization = data.get("specialization", "").strip()
    years_experience = data.get("yearsExperience", 0)
    bio = data.get("bio", "").strip()
    company_name = data.get("companyName", "").strip()
    number_trained = data.get("numberTrained", 0)

    # Validation
    fields = {}
    if len(full_name.split()) < 2:
        fields["fullName"] = "Enter first and last name."
    if not email:
        fields["email"] = "Enter a valid email address."
    if not phone:
        fields["phone"] = "Phone number is required."
    if not specialization:
        fields["specialization"] = "Specialization is required."
    if not partner_lgas:
        fields["partnerLgas"] = "Select at least one LGA."

    partnership_letter = request.FILES.get("partnershipLetter")
    if not partnership_letter:
        fields["partnershipLetter"] = "Partnership letter is required during registration."

    try:
        validate_password(password)
    except ValidationError as exc:
        fields["password"] = " ".join(exc.messages)

    if fields:
        _log_warning("Trainer signup validation failed", extra={"fields": fields})
        return validation_error("Please correct the highlighted fields.", fields)

    try:
        with transaction.atomic():
            # Create user
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=full_name.split(" ", 1)[0],
                last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
            )

            verification_token = get_random_string(64)
            profile = Profile.objects.create(
                user=user,
                role="trainer",
                phone=phone,
                specialization=specialization,
                partner_lgas=partner_lgas,
                years_experience=_safe_int(years_experience, 0),
                bio=bio,
                company_name=company_name,
                number_trained=_safe_int(number_trained, 0),
                is_authorized=False,
                authorization_status="pending",
                has_paid=False,
                email_verification_token=verification_token,
            )

            # Save partnership letter
            partnership_letter = request.FILES.get("partnershipLetter")
            if partnership_letter:
                profile.partnership_letter = partnership_letter
                profile.save(update_fields=["partnership_letter"])

            # Login user immediately
            login(request, user)
            _log_info(f"New trainer signed up: user {user.id}, email={email}")

    except IntegrityError:
        _log_warning("Trainer signup integrity error", extra={"email": email})
        return validation_error(
            "An account with this email already exists.",
            {"email": "Email is already registered."}
        )
    except Exception as exc:
        _log_error("Trainer signup error", exc=exc, extra={"email": email})
        return JsonResponse(
            {"error": "Signup failed. Please try again."}, status=500
        )

    # Send emails asynchronously (prevents 504 timeout)
    frontend_url = getattr(django_settings, 'FRONTEND_URL', 'http://localhost:3002')
    verify_url = f"{frontend_url}/verify-email?token={verification_token}"

    # 1. Verification email (async)
    _send_email_async(
        subject="Verify your SAED IMS email address",
        message=(
            f"Hello {full_name},\n\n"
            f"Please verify your email by clicking this link:\n{verify_url}\n\n"
            f"If you did not create this account, please ignore this email.\n\n"
            f"Best regards,\nNYSC SAED IMS"
        ),
        recipient_list=[email],
    )

    # 2. MD notification email (async)
    md_email = getattr(django_settings, "MD_EMAIL", "")
    if md_email:
        _send_email_async(
            subject=f"New Trainer Registration: {full_name}",
            message=(
                f"A new trainer has registered on the SAED IMS.\n\n"
                f"Name: {full_name}\n"
                f"Email: {email}\n"
                f"Phone: {phone}\n"
                f"Specialization: {specialization}\n"
                f"Partner LGAs: {', '.join(partner_lgas)}\n"
                f"Company: {company_name}\n"
                f"Years of Experience: {years_experience}\n"
                f"Number Trained: {number_trained}\n\n"
                f"Please review and authorize this trainer."
            ),
            recipient_list=[md_email],
        )

    return JsonResponse({"user": user_payload(user, request)}, status=201)


@csrf_exempt
@require_POST
def email_verify_view(request):
    """Verify email with token."""
    data = read_json(request)
    token = data.get("token", "")

    if not token:
        return validation_error(
            "Verification token is required.",
            {"token": "Token is required."}
        )

    try:
        profile = Profile.objects.filter(
            email_verification_token=token
        ).select_related("user").first()

        if not profile:
            _log_warning("Invalid verification token attempted", extra={"token": token[:8]})
            return JsonResponse(
                {"error": "Invalid or expired verification token."}, status=400
            )

        profile.is_email_verified = True
        profile.email_verification_token = ""
        profile.save(update_fields=["is_email_verified", "email_verification_token"])
        _log_info(f"Email verified for user {profile.user.id}")

        return JsonResponse({"ok": True, "message": "Email verified successfully."})

    except Exception as exc:
        _log_error("Email verification error", exc=exc)
        return JsonResponse(
            {"error": "Verification failed. Please try again."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRAM VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@require_http_methods(["GET"])
def program_list(request):
    """List active, unrestricted programs."""
    try:
        programs = Program.objects.filter(is_active=True, is_restricted=False)
        return JsonResponse({
            "programs": [program_payload(program) for program in programs],
            "categories": program_categories_payload(),
        })
    except Exception as exc:
        _log_error("Program list error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load programs."}, status=500
        )


@require_roles("corps_member")
def application_list(request):
    """List user's applications."""
    try:
        applications = Application.objects.filter(
            applicant=request.user
        ).select_related("program")
        return JsonResponse({
            "applications": [application_payload(item) for item in applications]
        })
    except Exception as exc:
        _log_error("Application list error", exc=exc,
                  extra={"user_id": request.user.id})
        return JsonResponse(
            {"error": "Failed to load applications."}, status=500
        )


@csrf_exempt
@api_login_required
@require_POST
def application_create(request):
    """Create a new program application."""
    if role_for(request.user) != "corps_member":
        return JsonResponse(
            {"error": "Only corps members can submit program applications."},
            status=403
        )

    data = read_json(request)
    program_id = data.get("programId")
    motivation = data.get("motivation", "")

    if not program_id:
        return validation_error(
            "Choose a program before applying.",
            {"programId": "Program is required."}
        )

    try:
        program = Program.objects.get(id=program_id, is_active=True)
    except Program.DoesNotExist:
        _log_warning("Application for non-existent program",
                    extra={"program_id": program_id})
        return JsonResponse({"error": "Program not found."}, status=404)

    try:
        application, created = Application.objects.get_or_create(
            applicant=request.user,
            program=program,
            defaults={"motivation": motivation},
        )
        if not created:
            return JsonResponse(
                {"error": "You already applied for this program."}, status=400
            )

        _log_info(f"Application created: {application.id} for program {program_id}")
        return JsonResponse(
            {"application": application_payload(application)}, status=201
        )

    except Exception as exc:
        _log_error("Application creation error", exc=exc)
        return JsonResponse(
            {"error": "Failed to create application."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PASSWORD RESET VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@require_POST
def password_reset_request(request):
    """Request password reset."""
    data = read_json(request)
    email = clean_email(data.get("email", ""))
    reset_payload = {}

    if not email:
        return validation_error(
            "Enter a valid email address.",
            {"email": "Use a valid email address."}
        )

    try:
        user = User.objects.filter(email=email, is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_payload = {"uid": uid, "token": token}
            _log_info(f"Password reset requested for user {user.id}")
        else:
            _log_warning("Password reset for unknown email", extra={"email": email})

        return JsonResponse({
            "ok": True,
            "message": "If that email exists, password reset instructions are available.",
            **reset_payload,
        })

    except Exception as exc:
        _log_error("Password reset request error", exc=exc)
        return JsonResponse(
            {"error": "Password reset failed. Please try again."}, status=500
        )


@csrf_exempt
@require_POST
def password_reset_confirm(request):
    """Confirm password reset with token."""
    data = read_json(request)
    uid = data.get("uid", "")
    token = data.get("token", "")
    password = data.get("password", "")

    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_id, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is None or not default_token_generator.check_token(user, token):
        _log_warning("Invalid password reset token attempted")
        return validation_error(
            "This password reset link is invalid or has expired.",
            {"token": "Request a new reset link."}
        )

    try:
        validate_password(password, user)
    except ValidationError as exc:
        return validation_error(
            "Choose a stronger password.",
            {"password": " ".join(exc.messages)}
        )

    try:
        user.set_password(password)
        user.save(update_fields=["password"])
        _log_info(f"Password reset completed for user {user.id}")
        return JsonResponse({"ok": True})
    except Exception as exc:
        _log_error("Password reset save error", exc=exc)
        return JsonResponse(
            {"error": "Password reset failed. Please try again."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["GET", "POST"])
@csrf_exempt
def manage_users(request):
    """List or create users (admin only)."""
    if request.method == "GET":
        try:
            users = User.objects.select_related("profile").order_by(
                "first_name", "email"
            )
            if role_for(request.user) == "saed_admin":
                users = users.exclude(
                    profile__authorization_status="restricted",
                    profile__restricted_by__profile__role="dunis_admin"
                )
            return JsonResponse({
                "users": [user_payload(user) for user in users]
            })
        except Exception as exc:
            _log_error("User list error", exc=exc)
            return JsonResponse(
                {"error": "Failed to load users."}, status=500
            )

    # POST - create new user
    if request.content_type and "multipart/form-data" in request.content_type:
        data = request.POST
    else:
        data = read_json(request)

    full_name = data.get("fullName", "").strip()
    email = clean_email(data.get("email", ""))
    role = data.get("role", "trainer")
    password = data.get("password", "")
    fields = {}

    if len(full_name.split()) < 2:
        fields["fullName"] = "Enter first and last name."
    if not email:
        fields["email"] = "Enter a valid email address."
    if role != "trainer":
        fields["role"] = "Admins can create trainer accounts only."
    if password:
        try:
            validate_password(password)
        except ValidationError as exc:
            fields["password"] = " ".join(exc.messages)

    if fields:
        return validation_error("Please correct the highlighted fields.", fields)

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password or get_random_string(20),
                first_name=full_name.split(" ", 1)[0],
                last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
            )
            Profile.objects.create(
                user=user,
                role="trainer",
                phone=data.get("phone", "").strip(),
                specialization=data.get("specialization", "").strip(),
                years_experience=_safe_int(data.get("yearsExperience", 0), 0),
                company_name=data.get("companyName", "").strip(),
                bio=data.get("bio", "").strip(),
                number_trained=_safe_int(data.get("numberTrained", 0), 0),
                partner_lgas=json.loads(data.get("partnerLgas", "[]"))
                    if isinstance(data.get("partnerLgas"), str)
                    else data.get("partnerLgas", []),
                is_authorized=True,
            )

            partnership_letter = request.FILES.get("partnershipLetter")
            if partnership_letter:
                user.profile.partnership_letter = partnership_letter
                user.profile.save(update_fields=["partnership_letter"])

            _log_info(f"Admin created trainer: user {user.id}")
            return JsonResponse({"user": user_payload(user)}, status=201)

    except IntegrityError:
        _log_warning("Admin user creation integrity error", extra={"email": email})
        return validation_error(
            "An account with this email already exists.",
            {"email": "Email is already registered."}
        )
    except Exception as exc:
        _log_error("Admin user creation error", exc=exc)
        return JsonResponse(
            {"error": "User creation failed. Please try again."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["GET", "PATCH"])
@csrf_exempt
def manage_user_detail(request, user_id):
    """Get or update specific user (admin only)."""
    try:
        user = User.objects.select_related("profile").get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    if request.method == "GET":
        return JsonResponse({"user": user_payload(user, request)})

    data = read_json(request)
    profile = getattr(user, "profile", None)
    if not profile:
        profile = Profile.objects.create(user=user)

    try:
        with transaction.atomic():
            if "fullName" in data:
                full_name = data.get("fullName", "").strip()
                if len(full_name.split()) < 2:
                    return validation_error(
                        "Enter first and last name.",
                        {"fullName": "First and last name are required."}
                    )
                user.first_name = full_name.split(" ", 1)[0]
                user.last_name = full_name.split(" ", 1)[1] if " " in full_name else ""

            if "role" in data:
                if user.id == request.user.id:
                    return validation_error(
                        "You cannot change your own role.",
                        {"role": "Self role changes are not allowed."}
                    )
                if data["role"] not in {"corps_member", "trainer"}:
                    return validation_error(
                        "Choose a valid account role.",
                        {"role": "Admins can only assign corps member or trainer roles."}
                    )
                profile.role = data["role"]

            if "phone" in data:
                profile.phone = data.get("phone", "").strip()
            if "isActive" in data:
                if user.id == request.user.id and not bool(data["isActive"]):
                    return validation_error(
                        "You cannot deactivate your own admin account.",
                        {"isActive": "Self deactivation is not allowed."}
                    )
                user.is_active = bool(data["isActive"])

            if "isAuthorized" in data:
                profile.is_authorized = bool(data["isAuthorized"])
                if profile.is_authorized:
                    profile.authorization_status = "approved"
                    profile.authorized_at = now()
                else:
                    profile.authorization_status = "pending"
                    profile.authorized_at = None

            if "authorizationStatus" in data:
                status_val = data["authorizationStatus"]
                if status_val in VALID_AUTH_STATUSES:
                    profile.authorization_status = status_val
                    profile.is_authorized = status_val == "approved"
                    if status_val == "approved":
                        profile.authorized_at = now()
                    else:
                        profile.authorized_at = None
                else:
                    return validation_error(
                        "Invalid authorization status.",
                        {"authorizationStatus": f"Must be one of: {VALID_AUTH_STATUSES}"}
                    )

            if "hasPaid" in data:
                profile.has_paid = bool(data["hasPaid"])
            if "canUploadFastTrack" in data:
                profile.can_upload_fast_track = bool(data["canUploadFastTrack"])
            if "isBusyCorper" in data:
                profile.is_busy_corper = bool(data["isBusyCorper"])
            if "paymentVerified" in data:
                profile.payment_verified = bool(data["paymentVerified"])
                if profile.payment_verified:
                    profile.payment_verified_at = now()
                    if profile.is_authorized:
                        profile.has_paid = True
                else:
                    profile.payment_verified_at = None

            user.save()
            profile.save()
            _log_info(f"Admin updated user {user.id}", extra={"updated_by": request.user.id})

    except Exception as exc:
        _log_error(f"User update error for {user_id}", exc=exc)
        return JsonResponse(
            {"error": "User update failed. Please try again."}, status=500
        )

    return JsonResponse({"user": user_payload(user, request)})










# ═══════════════════════════════════════════════════════════════════════════════
# PROGRAM MANAGEMENT VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
def apply_program_data(program, data):
    """Apply program data with validation."""
    fields = {}
    values = {}

    for frontend_key, model_key in PROGRAM_FIELDS.items():
        if frontend_key in data:
            values[model_key] = data[frontend_key]

    if "trainerId" in data:
        try:
            trainer_id = int(data.get("trainerId"))
            trainer = User.objects.select_related("profile").get(
                id=trainer_id, is_active=True, profile__role="trainer"
            )
        except (TypeError, ValueError, User.DoesNotExist):
            fields["trainerId"] = "Choose a valid trainer."
        else:
            values["trainer"] = trainer
            values["trainer_name"] = trainer.get_full_name() or trainer.email or trainer.username

    for field in ["title", "description", "trainer_name", "location"]:
        if field in values:
            values[field] = str(values[field]).strip()
            if not values[field]:
                fields[field] = "This field is required."

    if "category" in values and values["category"] not in dict(Program.CATEGORY_CHOICES):
        fields["category"] = "Choose a valid program category."

    for field in ["duration_weeks", "capacity"]:
        if field in values:
            try:
                values[field] = int(values[field])
            except (TypeError, ValueError):
                fields[field] = "Enter a number."
            else:
                if values[field] < 1:
                    fields[field] = "Enter a value greater than zero."

    required = ["title", "category", "description", "duration_weeks", "capacity", "location"]
    if program is None:
        for field in required:
            if field not in values:
                fields[field] = "This field is required."
        if "trainer" not in values:
            fields["trainerId"] = "Choose a trainer."

    if fields:
        return None, fields

    if program is None:
        program = Program()
    for key, value in values.items():
        setattr(program, key, value)
    program.save()
    return program, {}


@require_roles("saed_admin", "dunis_admin", "trainer")
@require_authorized_trainer
@require_http_methods(["GET", "POST"])
@csrf_exempt
def manage_programs(request):
    """List or create programs."""
    if request.method == "GET":
        try:
            programs = managed_programs_for(request.user)
            return JsonResponse({
                "programs": [program_payload(program) for program in programs],
                "categories": program_categories_payload(),
                "trainers": trainers_payload(),
            })
        except Exception as exc:
            _log_error("Program list error", exc=exc)
            return JsonResponse(
                {"error": "Failed to load programs."}, status=500
            )

    if role_for(request.user) != "saed_admin":
        return JsonResponse(
            {"error": "Only admins can create programs."}, status=403
        )

    program, fields = apply_program_data(None, read_json(request))
    if fields:
        return validation_error("Please correct the highlighted fields.", fields)

    _log_info(f"Program created: {program.id}")
    return JsonResponse({"program": program_payload(program)}, status=201)


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["PATCH"])
@csrf_exempt
def manage_program_detail(request, program_id):
    """Update specific program."""
    try:
        program = managed_programs_for(request.user).get(id=program_id)
    except Program.DoesNotExist:
        return JsonResponse({"error": "Program not found."}, status=404)

    program, fields = apply_program_data(program, read_json(request))
    if fields:
        return validation_error("Please correct the highlighted fields.", fields)

    _log_info(f"Program updated: {program_id}")
    return JsonResponse({"program": program_payload(program)})


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def restrict_program(request, program_id):
    """Restrict a program."""
    try:
        program = managed_programs_for(request.user).get(id=program_id)
    except Program.DoesNotExist:
        return JsonResponse({"error": "Program not found."}, status=404)

    if program.is_restricted:
        return JsonResponse(
            {"error": "Program is already restricted."}, status=400
        )

    try:
        program.is_restricted = True
        program.restricted_by = request.user
        program.restricted_at = now()
        program.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])

        trainer = program.trainer
        if trainer:
            _notify_user(
                trainer,
                "Program Restricted",
                f"Your program '{program.title}' has been restricted by an administrator.",
                reason="program_restricted",
            )

        corps_members = User.objects.filter(
            application__program=program,
            application__status="approved",
            profile__role="corps_member",
        ).distinct()
        for cm in corps_members:
            _notify_user(
                cm,
                "Program Restricted",
                f"The program '{program.title}' you are enrolled in has been restricted.",
                reason="program_restricted",
            )

        _log_info(f"Program {program_id} restricted by user {request.user.id}")
        return JsonResponse({"ok": True, "program": program_payload(program)})

    except Exception as exc:
        _log_error(f"Program restriction error for {program_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to restrict program."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def unrestrict_program(request, program_id):
    """Unrestrict a program."""
    try:
        program = managed_programs_for(request.user).get(id=program_id)
    except Program.DoesNotExist:
        return JsonResponse({"error": "Program not found."}, status=404)

    if not program.is_restricted:
        return JsonResponse(
            {"error": "Program is not restricted."}, status=400
        )

    try:
        program.is_restricted = False
        program.restricted_by = None
        program.restricted_at = None
        program.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])

        trainer = program.trainer
        if trainer:
            _notify_user(
                trainer,
                "Program Unrestricted",
                f"Your program '{program.title}' has been unrestricted and is now active again.",
                reason="program_unrestricted",
            )

        _log_info(f"Program {program_id} unrestricted by user {request.user.id}")
        return JsonResponse({"ok": True, "program": program_payload(program)})

    except Exception as exc:
        _log_error(f"Program unrestriction error for {program_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to unrestrict program."}, status=500
        )


@require_roles("saed_admin", "dunis_admin", "trainer")
@require_authorized_trainer
@require_http_methods(["GET"])
def manage_applications(request):
    """List applications for management."""
    try:
        applications = managed_applications_for(request.user)
        return JsonResponse({
            "applications": [application_payload(item) for item in applications]
        })
    except Exception as exc:
        _log_error("Application management list error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load applications."}, status=500
        )


@require_roles("saed_admin", "dunis_admin", "trainer")
@require_authorized_trainer
@require_http_methods(["PATCH"])
@csrf_exempt
def manage_application_detail(request, application_id):
    """Update application status."""
    data = read_json(request)
    status = data.get("status")

    if status not in VALID_APPLICATION_STATUSES:
        return validation_error(
            "Choose approve, decline, or complete.",
            {"status": "Invalid application status."}
        )

    try:
        application = managed_applications_for(request.user).get(id=application_id)
    except Application.DoesNotExist:
        return JsonResponse({"error": "Application not found."}, status=404)

    if application.status == "completed" and role_for(request.user) != "saed_admin":
        return validation_error(
            "Only admins can change the status of a completed application.",
            {"status": "Completed applications can only be modified by an admin."},
        )

    try:
        application.status = status
        application.save(update_fields=["status"])
        _log_info(f"Application {application_id} status changed to {status}")
        return JsonResponse({"application": application_payload(application)})
    except Exception as exc:
        _log_error(f"Application update error for {application_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to update application."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# DASHBOARD VIEW
# ═══════════════════════════════════════════════════════════════════════════════
@api_login_required
def dashboard(request):
    """Get dashboard statistics based on user role."""
    try:
        user_role = role_for(request.user)
        payload = {"stats": {}, "applications": []}

        if user_role == "corps_member":
            applications = Application.objects.filter(
                applicant=request.user
            ).select_related("program")
            my_connections = Connection.objects.filter(
                corps_member=request.user
            ).count()
            payload["stats"] = {
                "applications": applications.count(),
                "pending": applications.filter(status="pending").count(),
                "approved": applications.filter(status="approved").count(),
                "connections": my_connections,
            }
            payload["applications"] = [
                application_payload(item) for item in applications[:5]
            ]

        elif user_role == "trainer":
            my_courses = Course.objects.filter(trainer=request.user, is_active=True)
            my_corpers = Connection.objects.filter(trainer=request.user).count()
            trainer_programs = managed_programs_for(request.user).filter(is_active=True)
            payload["stats"] = {
                "courses": my_courses.count(),
                "corpers": my_corpers,
                "programs": trainer_programs.count(),
            }
            payload["trainerPrograms"] = [
                program_payload(p) for p in trainer_programs[:4]
            ]

        elif user_role == "saed_admin":
            trainer_profiles = Profile.objects.filter(role="trainer")
            payload["stats"] = {
                "totalTrainers": trainer_profiles.count(),
                "approvedTrainers": trainer_profiles.filter(is_authorized=True).count(),
                "pendingTrainers": trainer_profiles.filter(
                    authorization_status="pending"
                ).count(),
                "declinedTrainers": trainer_profiles.filter(
                    authorization_status="declined"
                ).count(),
                "removedTrainers": trainer_profiles.filter(
                    authorization_status="removed"
                ).count(),
                "totalCorpers": Profile.objects.filter(role="corps_member").count(),
                "totalConnections": Connection.objects.count(),
                "totalCourses": Course.objects.filter(is_active=True).count(),
            }
            payload["partnerStats"] = payload["stats"]

        elif user_role == "dunis_admin":
            trainer_profiles = Profile.objects.filter(role="trainer")
            pending_payments = trainer_profiles.filter(
                is_authorized=True, has_paid=False
            ).count()
            fast_track_enabled = trainer_profiles.filter(
                can_upload_fast_track=True
            ).count()
            payload["stats"] = {
                "totalTrainers": trainer_profiles.count(),
                "approvedTrainers": trainer_profiles.filter(is_authorized=True).count(),
                "pendingTrainers": trainer_profiles.filter(
                    authorization_status="pending"
                ).count(),
                "declinedTrainers": trainer_profiles.filter(
                    authorization_status="declined"
                ).count(),
                "removedTrainers": trainer_profiles.filter(
                    authorization_status="removed"
                ).count(),
                "paidTrainers": trainer_profiles.filter(has_paid=True).count(),
                "pendingPayments": pending_payments,
                "fastTrackEnabled": fast_track_enabled,
                "totalCorpers": Profile.objects.filter(role="corps_member").count(),
                "totalConnections": Connection.objects.count(),
                "totalCourses": Course.objects.filter(is_active=True).count(),
            }
            payload["partnerStats"] = payload["stats"]

        return JsonResponse(payload)

    except Exception as exc:
        _log_error("Dashboard error", exc=exc,
                  extra={"user_id": request.user.id, "role": role_for(request.user)})
        return JsonResponse(
            {"error": "Failed to load dashboard."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# COURSE VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
def course_payload(course):
    """Build course payload."""
    return {
        "id": course.id,
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
        "createdAt": course.created_at.isoformat(),
        "trainerId": course.trainer_id,
        "trainerName": course.trainer.get_full_name() or course.trainer.email,
        "isRestricted": course.is_restricted,
        "restrictedById": course.restricted_by_id,
        "restrictedAt": course.restricted_at.isoformat() if course.restricted_at else None,
    }


def connection_payload(connection):
    """Build connection payload."""
    return {
        "id": connection.id,
        "status": connection.status,
        "connectedAt": connection.connected_at.isoformat(),
        "corpsMember": user_payload(connection.corps_member),
        "trainer": user_payload(connection.trainer),
    }


@require_roles("trainer")
@require_http_methods(["GET", "POST"])
@csrf_exempt
def manage_courses(request):
    """List or create courses (trainer only)."""
    if request.method == "GET":
        try:
            courses = Course.objects.filter(trainer=request.user).order_by("-created_at")
            return JsonResponse({
                "courses": [course_payload(c) for c in courses]
            })
        except Exception as exc:
            _log_error("Course list error", exc=exc)
            return JsonResponse(
                {"error": "Failed to load courses."}, status=500
            )

    data = read_json(request)
    title = data.get("title", "").strip()
    if not title:
        return validation_error(
            "Course title is required.",
            {"title": "Title is required."}
        )

    data = _resolve_course_dates(data)

    try:
        course = Course.objects.create(
            trainer=request.user,
            title=title,
            description=data.get("description", "").strip(),
            category=data.get("category", "").strip(),
            price=_safe_float(data.get("price", 0)),
            duration_weeks=data.get("durationWeeks", 4),
            start_date=_parse_date(data.get("startDate")),
            end_date=_parse_date(data.get("endDate")),
            max_students=data.get("maxStudents", 40),
            has_fast_track=data.get("hasFastTrack", False),
        )
        _log_info(f"Course created: {course.id} by trainer {request.user.id}")
        return JsonResponse({"course": course_payload(course)}, status=201)
    except Exception as exc:
        _log_error("Course creation error", exc=exc)
        return JsonResponse(
            {"error": "Failed to create course."}, status=500
        )


@require_roles("trainer")
@require_http_methods(["PATCH", "DELETE"])
@csrf_exempt
def manage_course_detail(request, course_id):
    """Update or delete specific course."""
    try:
        course = Course.objects.get(id=course_id, trainer=request.user)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    if request.method == "DELETE":
        try:
            course.delete()
            _log_info(f"Course {course_id} deleted by trainer {request.user.id}")
            return JsonResponse({"ok": True})
        except Exception as exc:
            _log_error(f"Course deletion error for {course_id}", exc=exc)
            return JsonResponse(
                {"error": "Failed to delete course."}, status=500
            )

    data = read_json(request)
    data = _resolve_course_dates(data)

    field_mappings = {
        "title": "title",
        "description": "description",
        "category": "category",
        "price": "price",
        "durationWeeks": "duration_weeks",
        "startDate": "start_date",
        "endDate": "end_date",
        "maxStudents": "max_students",
        "hasFastTrack": "has_fast_track",
    }

    try:
        for field, model_field in field_mappings.items():
            if field in data:
                value = data[field]
                if field in ("startDate", "endDate"):
                    value = _parse_date(value)
                elif field == "price":
                    value = _safe_float(value)
                elif field in ("durationWeeks", "maxStudents"):
                    value = _safe_int(value)
                elif field == "hasFastTrack":
                    value = bool(value)
                setattr(course, model_field, value)

        course.save()
        _log_info(f"Course {course_id} updated by trainer {request.user.id}")
        return JsonResponse({"course": course_payload(course)})

    except Exception as exc:
        _log_error(f"Course update error for {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to update course."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["GET"])
def admin_courses(request):
    """List all courses for admin."""
    try:
        courses = Course.objects.select_related("trainer", "trainer__profile").all()
        user_role = role_for(request.user)
        if user_role == "saed_admin":
            courses = courses.exclude(
                is_restricted=True,
                restricted_by__profile__role="dunis_admin"
            )
        return JsonResponse({
            "courses": [course_payload(c) for c in courses]
        })
    except Exception as exc:
        _log_error("Admin course list error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load courses."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def restrict_course(request, course_id):
    """Restrict a course."""
    try:
        course = Course.objects.get(id=course_id)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    if course.is_restricted:
        return JsonResponse(
            {"error": "Course is already restricted."}, status=400
        )

    try:
        course.is_restricted = True
        course.restricted_by = request.user
        course.restricted_at = now()
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])

        _notify_user(
            course.trainer,
            "Course Restricted",
            f"Your course '{course.title}' has been restricted by an administrator.",
            reason="course_restricted",
        )

        corps_members = User.objects.filter(
            connections__trainer=course.trainer,
            profile__role="corps_member",
        ).distinct()
        for cm in corps_members:
            _notify_user(
                cm,
                "Course Restricted",
                f"A course you are enrolled in ('{course.title}') has been restricted.",
                reason="course_restricted",
            )

        _log_info(f"Course {course_id} restricted by admin {request.user.id}")
        return JsonResponse({"ok": True, "course": course_payload(course)})

    except Exception as exc:
        _log_error(f"Course restriction error for {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to restrict course."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def unrestrict_course(request, course_id):
    """Unrestrict a course."""
    try:
        course = Course.objects.get(id=course_id)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    if not course.is_restricted:
        return JsonResponse(
            {"error": "Course is not restricted."}, status=400
        )

    try:
        course.is_restricted = False
        course.restricted_by = None
        course.restricted_at = None
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])

        _notify_user(
            course.trainer,
            "Course Unrestricted",
            f"Your course '{course.title}' has been unrestricted and is now active again.",
            reason="course_unrestricted",
        )

        _log_info(f"Course {course_id} unrestricted by admin {request.user.id}")
        return JsonResponse({"ok": True, "course": course_payload(course)})

    except Exception as exc:
        _log_error(f"Course unrestriction error for {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to unrestrict course."}, status=500
        )







# ═══════════════════════════════════════════════════════════════════════════════
# TRAINER & CONNECTION VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@require_roles("corps_member")
@require_http_methods(["GET"])
def available_trainers(request):
    """List available trainers with optional filters."""
    try:
        lga = request.GET.get("lga", "")
        skill = request.GET.get("skill", "")
        trainers = User.objects.select_related("profile").filter(
            is_active=True,
            profile__role="trainer",
            profile__is_authorized=True,
        )
        if skill:
            trainers = trainers.filter(profile__specialization__icontains=skill)

        result = []
        for t in trainers:
            profile = t.profile
            if lga and lga not in (profile.partner_lgas or []):
                continue
            result.append({
                "id": t.id,
                "fullName": t.get_full_name() or t.email,
                "email": t.email,
                "specialization": profile.specialization,
                "partnerLgas": profile.partner_lgas,
                "yearsExperience": profile.years_experience,
                "bio": profile.bio,
                "companyName": profile.company_name,
                "numberTrained": profile.number_trained,
            })
        return JsonResponse({"trainers": result})

    except Exception as exc:
        _log_error("Available trainers error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load trainers."}, status=500
        )


@api_login_required
@require_http_methods(["GET"])
def trainer_detail(request, trainer_id):
    """Get trainer details with courses."""
    try:
        t = User.objects.select_related("profile").get(
            id=trainer_id,
            is_active=True,
            profile__role="trainer",
            profile__is_authorized=True
        )
    except User.DoesNotExist:
        return JsonResponse({"error": "Trainer not found."}, status=404)

    try:
        profile = t.profile
        courses = Course.objects.filter(trainer=t, is_active=True)
        existing_connection = Connection.objects.filter(
            corps_member=request.user, trainer=t
        ).first() if request.user.is_authenticated else None

        course_list = []
        for c in courses:
            enrollment = CourseEnrollment.objects.filter(
                student=request.user, course=c
            ).first() if request.user.is_authenticated else None
            course_list.append({
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "category": c.category,
                "price": str(c.price),
                "durationWeeks": c.duration_weeks,
                "startDate": c.start_date.isoformat() if c.start_date else None,
                "endDate": c.end_date.isoformat() if c.end_date else None,
                "maxStudents": c.max_students,
                "hasFastTrack": c.has_fast_track,
                "isPaid": enrollment.status == "confirmed" if enrollment else False,
                "isEnrolled": enrollment is not None,
                "enrollmentStatus": enrollment.status if enrollment else None,
            })

        return JsonResponse({
            "trainer": {
                "id": t.id,
                "fullName": t.get_full_name() or t.email,
                "email": t.email,
                "specialization": profile.specialization,
                "partnerLgas": profile.partner_lgas,
                "yearsExperience": profile.years_experience,
                "bio": profile.bio,
                "companyName": profile.company_name,
                "numberTrained": profile.number_trained,
                "profilePicture": profile.profile_picture.url if profile.profile_picture else None,
            },
            "courses": course_list,
            "connectionStatus": existing_connection.status if existing_connection else None,
            "connectionId": existing_connection.id if existing_connection else None,
        })

    except Exception as exc:
        _log_error(f"Trainer detail error for {trainer_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to load trainer details."}, status=500
        )


@require_roles("corps_member")
@require_http_methods(["POST"])
@csrf_exempt
def select_trainers(request):
    """Select trainers for connection."""
    data = read_json(request)
    trainer_ids = data.get("trainerIds", [])

    if not trainer_ids:
        return validation_error(
            "Select at least one trainer.",
            {"trainerIds": "Choose one or more trainers."}
        )

    profile = getattr(request.user, "profile", None)
    if not profile:
        return JsonResponse({"error": "Profile not found."}, status=400)

    created_count = 0
    errors = []

    for trainer_id in trainer_ids:
        try:
            trainer = User.objects.select_related("profile").get(
                id=trainer_id,
                is_active=True,
                profile__role="trainer",
                profile__is_authorized=True
            )
        except User.DoesNotExist:
            errors.append(f"Trainer {trainer_id} not found")
            continue

        _, created = Connection.objects.get_or_create(
            corps_member=request.user,
            trainer=trainer,
            defaults={"status": "active"},
        )
        if created:
            created_count += 1

    profile.has_selected_trainers = True
    profile.save(update_fields=["has_selected_trainers"])

    if errors:
        _log_warning("Some trainers not found during selection", extra={"errors": errors})

    _log_info(f"User {request.user.id} connected to {created_count} trainers")
    return JsonResponse({"ok": True, "connected": created_count})


@require_roles("corps_member")
@require_http_methods(["GET"])
def my_trainers(request):
    """Get user's connected trainers."""
    try:
        connections = Connection.objects.filter(
            corps_member=request.user
        ).select_related("trainer", "trainer__profile").exclude(status="cancelled")

        result = []
        for conn in connections:
            trainer = conn.trainer
            profile = trainer.profile
            courses = Course.objects.filter(trainer=trainer, is_active=True)
            result.append({
                "id": trainer.id,
                "fullName": trainer.get_full_name() or trainer.email,
                "email": trainer.email,
                "specialization": profile.specialization,
                "bio": profile.bio,
                "companyName": profile.company_name,
                "yearsExperience": profile.years_experience,
                "numberTrained": profile.number_trained,
                "connectionStatus": conn.status,
                "connectedAt": conn.connected_at.isoformat(),
                "courses": [
                    {
                        "id": c.id,
                        "title": c.title,
                        "description": c.description,
                        "category": c.category,
                        "price": str(c.price),
                        "durationWeeks": c.duration_weeks,
                        "startDate": c.start_date.isoformat() if c.start_date else None,
                        "endDate": c.end_date.isoformat() if c.end_date else None,
                        "maxStudents": c.max_students,
                        "hasFastTrack": c.has_fast_track,
                    }
                    for c in courses
                ],
            })
        return JsonResponse({"trainers": result})

    except Exception as exc:
        _log_error("My trainers error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load trainers."}, status=500
        )


@require_roles("corps_member")
@require_http_methods(["POST"])
@csrf_exempt
def connect_trainer(request):
    """Request connection with a trainer."""
    data = read_json(request)
    trainer_id = data.get("trainerId")

    if not trainer_id:
        return validation_error(
            "Trainer is required.",
            {"trainerId": "Select a trainer."}
        )

    try:
        trainer = User.objects.select_related("profile").get(
            id=trainer_id,
            is_active=True,
            profile__role="trainer",
            profile__is_authorized=True
        )
    except User.DoesNotExist:
        return JsonResponse({"error": "Trainer not found."}, status=404)

    try:
        connection, created = Connection.objects.get_or_create(
            corps_member=request.user,
            trainer=trainer,
            defaults={"status": "pending"},
        )
        if not created:
            return JsonResponse(
                {"error": "You are already connected to this trainer."}, status=400
            )

        trainer_courses = Course.objects.filter(trainer=trainer, is_active=True)
        all_full = all(
            Connection.objects.filter(trainer=trainer, status="active").count() >= c.max_students
            for c in trainer_courses
        ) if trainer_courses.exists() else False

        if all_full:
            connection.status = "cancelled"
            connection.save(update_fields=["status"])
            Notification.objects.create(
                user=request.user,
                title="Connection Auto-Declined",
                message=f"Your connection request with {trainer.get_full_name()} was automatically declined because all course slots are full.",
                reason="connection_request",
                created_by_role="trainer",
            )
            return JsonResponse(
                {"error": "All course slots for this trainer are full."}, status=400
            )

        cm_name = request.user.get_full_name() or request.user.email
        Notification.objects.create(
            user=trainer,
            title="New Connection Request",
            message=f"{cm_name} wants to connect with you. Please review and approve.",
            reason="connection_request",
            created_by_role="corps_member",
        )

        # Send email asynchronously
        _send_email_async(
            subject="SAED IMS - New Connection Request",
            message=(
                f"Hello {trainer.get_full_name()},\n\n"
                f"{cm_name} ({request.user.email}) wants to connect with you.\n"
                f"Please log in to review and approve this request.\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[trainer.email],
        )

        _log_info(f"Connection request created: {connection.id}")
        return JsonResponse(
            {"connection": connection_payload(connection)}, status=201
        )

    except Exception as exc:
        _log_error("Connection creation error", exc=exc)
        return JsonResponse(
            {"error": "Failed to create connection."}, status=500
        )


@require_roles("corps_member")
@require_http_methods(["GET"])
def my_connections(request):
    """Get user's connections."""
    try:
        connections = Connection.objects.filter(
            corps_member=request.user
        ).select_related("trainer", "trainer__profile")
        return JsonResponse({
            "connections": [connection_payload(c) for c in connections]
        })
    except Exception as exc:
        _log_error("My connections error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load connections."}, status=500
        )


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["GET"])
def my_corpers(request):
    """Get trainer's connected corps members."""
    try:
        connections = Connection.objects.filter(
            trainer=request.user
        ).select_related("corps_member", "corps_member__profile")
        return JsonResponse({
            "corpers": [connection_payload(c) for c in connections]
        })
    except Exception as exc:
        _log_error("My corpers error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load corps members."}, status=500
        )


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["POST"])
@csrf_exempt
def connection_approve(request, connection_id):
    """Approve a connection request."""
    try:
        connection = Connection.objects.select_related(
            "corps_member", "trainer"
        ).get(id=connection_id, trainer=request.user, status="pending")
    except Connection.DoesNotExist:
        return JsonResponse({"error": "Connection request not found."}, status=404)

    try:
        connection.status = "active"
        connection.save(update_fields=["status"])

        Notification.objects.create(
            user=connection.corps_member,
            title="Connection Approved",
            message=f"Your connection request with {request.user.get_full_name()} has been approved!",
            reason="connection_approved",
            created_by_role="trainer",
        )

        _send_email_async(
            subject="SAED IMS - Connection Approved!",
            message=(
                f"Hello {connection.corps_member.get_full_name()},\n\n"
                f"Your connection request with {request.user.get_full_name()} has been approved!\n"
                f"You can now access their courses and training materials.\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[connection.corps_member.email],
        )

        _log_info(f"Connection {connection_id} approved by trainer {request.user.id}")
        return JsonResponse({"connection": connection_payload(connection)})

    except Exception as exc:
        _log_error(f"Connection approval error for {connection_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to approve connection."}, status=500
        )


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["POST"])
@csrf_exempt
def connection_reject(request, connection_id):
    """Reject a connection request."""
    try:
        connection = Connection.objects.get(
            id=connection_id, trainer=request.user, status="pending"
        )
    except Connection.DoesNotExist:
        return JsonResponse({"error": "Connection request not found."}, status=404)

    try:
        connection.status = "cancelled"
        connection.save(update_fields=["status"])

        Notification.objects.create(
            user=connection.corps_member,
            title="Connection Declined",
            message=f"Your connection request with {request.user.get_full_name()} has been declined.",
            reason="connection_request",
            created_by_role="trainer",
        )

        _log_info(f"Connection {connection_id} rejected by trainer {request.user.id}")
        return JsonResponse({"connection": connection_payload(connection)})

    except Exception as exc:
        _log_error(f"Connection rejection error for {connection_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to reject connection."}, status=500
        )


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["GET"])
def corper_profile_for_trainer(request, corper_id):
    """Get corps member profile for trainer."""
    try:
        corper = User.objects.select_related("profile").get(
            id=corper_id, profile__role="corps_member"
        )
    except User.DoesNotExist:
        return JsonResponse({"error": "Corps member not found."}, status=404)

    try:
        connection = Connection.objects.filter(
            trainer=request.user, corps_member=corper
        ).first()

        trainer_courses = Course.objects.filter(trainer=request.user, is_active=True)
        corper_data = user_payload(corper)
        corper_data["connectionStatus"] = connection.status if connection else "none"
        corper_data["connectionId"] = connection.id if connection else None

        corper_enrollments = CourseEnrollment.objects.filter(
            student=corper, course__in=trainer_courses
        )
        enrollment_map = {e.course_id: e for e in corper_enrollments}

        courses_with_status = []
        for course in trainer_courses:
            enrolled_count = Connection.objects.filter(
                trainer=request.user, status="active"
            ).count()
            enrollment = enrollment_map.get(course.id)
            courses_with_status.append({
                **course_payload(course),
                "isFull": enrolled_count >= course.max_students,
                "enrolledCount": enrolled_count,
                "isEnrolled": enrollment is not None,
                "isPaid": enrollment.is_paid if enrollment else False,
                "enrollmentStatus": enrollment.status if enrollment else None,
                "enrollmentId": enrollment.id if enrollment else None,
            })

        return JsonResponse({
            "corper": corper_data,
            "courses": courses_with_status,
        })

    except Exception as exc:
        _log_error(f"Corper profile error for {corper_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to load corps member profile."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# FAST TRACK VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@require_roles("corps_member")
@require_http_methods(["GET"])
def trainee_fast_track_courses(request):
    """Get fast track courses for trainee."""
    try:
        connections = Connection.objects.filter(
            corps_member=request.user, status="active"
        ).select_related("trainer")
        trainer_ids = connections.values_list("trainer_id", flat=True)
        courses = Course.objects.filter(
            trainer_id__in=trainer_ids, is_active=True, has_fast_track=True
        )

        enrolled_ids = set(
            CourseEnrollment.objects.filter(
                student=request.user, course__in=courses, status="confirmed"
            ).values_list("course_id", flat=True)
        )
        pending_ids = set(
            CourseEnrollment.objects.filter(
                student=request.user, course__in=courses, status="pending"
            ).values_list("course_id", flat=True)
        )
        rejected_ids = set(
            CourseEnrollment.objects.filter(
                student=request.user, course__in=courses, status="rejected"
            ).values_list("course_id", flat=True)
        )
        refunded_ids = set(
            CourseEnrollment.objects.filter(
                student=request.user, course__in=courses, status="refunded"
            ).values_list("course_id", flat=True)
        )

        result = []
        for c in courses:
            videos = FastTrackVideo.objects.filter(course=c)
            profile = getattr(request.user, "profile", None)
            is_busy = profile.is_busy_corper if profile else False
            if not is_busy:
                videos = videos.filter(is_free_preview=True)

            enrollment_status = None
            if c.id in enrolled_ids:
                enrollment_status = "confirmed"
            elif c.id in pending_ids:
                enrollment_status = "pending"
            elif c.id in rejected_ids:
                enrollment_status = "rejected"
            elif c.id in refunded_ids:
                enrollment_status = "refunded"

            result.append({
                **course_payload(c),
                "videoCount": videos.count(),
                "isEnrolled": c.id in enrolled_ids,
                "isPending": c.id in pending_ids,
                "isRejected": c.id in rejected_ids,
                "isRefunded": c.id in refunded_ids,
                "enrollmentStatus": enrollment_status,
            })

        return JsonResponse({"courses": result})

    except Exception as exc:
        _log_error("Fast track courses error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load fast track courses."}, status=500
        )


def fast_track_video_payload(video):
    """Build fast track video payload."""
    return {
        "id": video.id,
        "courseId": video.course_id,
        "courseTitle": video.course.title,
        "title": video.title,
        "description": video.description,
        "videoUrl": video.video_url,
        "durationSeconds": video.duration_seconds,
        "order": video.order,
        "price": str(video.price),
        "isFreePreview": video.is_free_preview,
        "createdAt": video.created_at.isoformat(),
    }


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["GET", "POST"])
@csrf_exempt
def manage_fast_track_videos(request):
    """List or create fast track videos."""
    profile = request.user.profile
    if not profile.can_upload_fast_track:
        return JsonResponse(
            {"error": "You are not approved to upload fast track videos."},
            status=403
        )

    if request.method == "GET":
        try:
            course_id = request.GET.get("courseId")
            videos = FastTrackVideo.objects.select_related("course").filter(
                course__trainer=request.user
            )
            if course_id:
                videos = videos.filter(course_id=course_id)
            return JsonResponse({
                "videos": [fast_track_video_payload(v) for v in videos]
            })
        except Exception as exc:
            _log_error("Fast track video list error", exc=exc)
            return JsonResponse(
                {"error": "Failed to load videos."}, status=500
            )

    data = read_json(request)
    course_id = data.get("courseId")
    title = data.get("title", "").strip()

    if not course_id:
        return validation_error(
            "Course is required.",
            {"courseId": "Select a course."}
        )
    if not title:
        return validation_error(
            "Title is required.",
            {"title": "Title is required."}
        )

    try:
        course = Course.objects.get(id=course_id, trainer=request.user)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    try:
        video = FastTrackVideo.objects.create(
            course=course,
            title=title,
            description=data.get("description", "").strip(),
            video_url=data.get("videoUrl", "").strip(),
            duration_seconds=_safe_int(data.get("durationSeconds", 0)),
            order=_safe_int(data.get("order", 0)),
            price=data.get("price", 0),
            is_free_preview=bool(data.get("isFreePreview", False)),
        )
        _log_info(f"Fast track video created: {video.id} for course {course_id}")
        return JsonResponse(
            {"video": fast_track_video_payload(video)}, status=201
        )
    except Exception as exc:
        _log_error("Fast track video creation error", exc=exc)
        return JsonResponse(
            {"error": "Failed to create video."}, status=500
        )


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["PATCH", "DELETE"])
@csrf_exempt
def manage_fast_track_video_detail(request, video_id):
    """Update or delete fast track video."""
    profile = request.user.profile
    if not profile.can_upload_fast_track:
        return JsonResponse(
            {"error": "You are not approved to upload fast track videos."},
            status=403
        )

    try:
        video = FastTrackVideo.objects.select_related("course").get(
            id=video_id, course__trainer=request.user
        )
    except FastTrackVideo.DoesNotExist:
        return JsonResponse({"error": "Video not found."}, status=404)

    if request.method == "DELETE":
        try:
            video.delete()
            _log_info(f"Fast track video {video_id} deleted")
            return JsonResponse({"ok": True})
        except Exception as exc:
            _log_error(f"Video deletion error for {video_id}", exc=exc)
            return JsonResponse(
                {"error": "Failed to delete video."}, status=500
            )

    data = read_json(request)
    field_mappings = {
        "title": "title",
        "description": "description",
        "videoUrl": "video_url",
        "durationSeconds": "duration_seconds",
        "order": "order",
        "price": "price",
        "isFreePreview": "is_free_preview",
    }

    try:
        for field, model_field in field_mappings.items():
            if field in data:
                setattr(video, model_field, data[field])
        video.save()
        _log_info(f"Fast track video {video_id} updated")
        return JsonResponse({"video": fast_track_video_payload(video)})
    except Exception as exc:
        _log_error(f"Video update error for {video_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to update video."}, status=500
        )


@api_login_required
@require_http_methods(["GET"])
def course_detail(request, course_id):
    """Get course details with videos."""
    try:
        course = Course.objects.select_related("trainer", "trainer__profile").get(
            id=course_id, is_active=True
        )
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    try:
        videos = FastTrackVideo.objects.filter(course=course).order_by("order")
        return JsonResponse({
            "course": course_payload(course),
            "trainer": {
                "id": course.trainer.id,
                "fullName": course.trainer.get_full_name() or course.trainer.email,
                "specialization": course.trainer.profile.specialization if hasattr(course.trainer, "profile") else "",
                "companyName": course.trainer.profile.company_name if hasattr(course.trainer, "profile") else "",
            },
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "description": v.description,
                    "videoUrl": v.video_url,
                    "durationSeconds": v.duration_seconds,
                    "order": v.order,
                    "price": str(v.price),
                    "isFreePreview": v.is_free_preview,
                }
                for v in videos
            ],
        })
    except Exception as exc:
        _log_error(f"Course detail error for {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to load course details."}, status=500
        )


@require_roles("corps_member")
@require_http_methods(["GET"])
def fast_track_videos_for_course(request, course_id):
    """Get fast track videos for a specific course."""
    user = request.user
    profile = getattr(user, "profile", None)
    is_busy = profile.is_busy_corper if profile else False

    try:
        course = Course.objects.get(id=course_id, is_active=True)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    if not course.has_fast_track:
        return JsonResponse({
            "videos": [],
            "error": "Fast track is not enabled for this course."
        })

    try:
        is_enrolled = False
        if course.price > 0:
            is_enrolled = CourseEnrollment.objects.filter(
                student=user, course=course, status="confirmed"
            ).exists()

        videos = FastTrackVideo.objects.select_related("course").filter(course=course)
        if not is_busy and not is_enrolled:
            videos = videos.filter(is_free_preview=True)

        result = []
        for v in videos:
            result.append({
                "id": v.id,
                "title": v.title,
                "description": v.description,
                "videoUrl": v.video_url,
                "durationSeconds": v.duration_seconds,
                "price": str(v.price),
                "isFreePreview": v.is_free_preview,
            })

        return JsonResponse({"videos": result, "isEnrolled": is_enrolled})

    except Exception as exc:
        _log_error(f"Fast track videos error for course {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to load videos."}, status=500
        )


# @require_roles("dunis_admin")
# @require_http_methods(["GET"])
# def dunis_pending_payments(request):
#     profiles = Profile.objects.filter(
#         role="trainer",
#         is_authorized=True,
#         has_paid=False,
#     ).select_related("user")
#     result = []
#     for p in profiles:
#         result.append({
#             "id": p.user.id,
#             "fullName": p.user.get_full_name() or p.user.email,
#             "email": p.user.email,
#             "phone": p.phone,
#             "specialization": p.specialization,
#             "companyName": p.company_name,
#             "hasPaid": p.has_paid,
#             "paymentVerified": p.payment_verified,
#             "authorizedAt": p.authorized_at.isoformat() if p.authorized_at else None,
#         })
#     return JsonResponse({"trainers": result})


# @require_roles("dunis_admin")
# @require_http_methods(["POST"])
# @csrf_exempt
# def dunis_confirm_payment(request):
#     data = read_json(request)
#     user_id = data.get("userId")
#     reference = data.get("reference", "")
#     if not user_id:
#         return validation_error("User ID is required.", {"userId": "Select a trainer."})
#     try:
#         user = User.objects.select_related("profile").get(id=user_id)
#     except User.DoesNotExist:
#         return JsonResponse({"error": "Trainer not found."}, status=404)

#     profile = user.profile
#     if profile.role != "trainer":
#         return JsonResponse({"error": "This user is not a trainer."}, status=400)

#     profile.has_paid = True
#     profile.payment_verified = True
#     profile.payment_reference = reference
#     profile.payment_verified_at = now()
#     profile.save(update_fields=["has_paid", "payment_verified", "payment_reference", "payment_verified_at"])

#     try:
#         send_mail(
#             subject="SAED IMS - Account Activated!",
#             message=(
#                 f"Hello {user.get_full_name()},\n\n"
#                 f"Your payment has been verified and your account has been activated.\n"
#                 f"You can now log in and start using the SAED IMS platform.\n\n"
#                 f"Payment Reference: {reference}\n\n"
#                 f"Best regards,\nNYSC SAED IMS"
#             ),
#             from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"),
#             recipient_list=[user.email],
#             fail_silently=True,
#         )
#     except Exception as exc:
#         logger.exception(f"Failed to send email in dunis_confirm_payment: {exc}")
#         sentry_sdk.capture_exception(exc)

#     return JsonResponse({"ok": True, "message": "Payment confirmed. Account activated."})


# @require_roles("dunis_admin")
# @require_http_methods(["GET"])
# def dunis_all_trainers(request):
#     profiles = Profile.objects.filter(role="trainer").select_related("user").order_by("-created_at" if hasattr(Profile, "created_at") else "user__first_name")
#     result = []
#     for p in profiles:
#         result.append({
#             "id": p.user.id,
#             "fullName": p.user.get_full_name() or p.user.email,
#             "email": p.user.email,
#             "specialization": p.specialization,
#             "isAuthorized": p.is_authorized,
#             "isActive": p.user.is_active,
#             "hasPaid": p.has_paid,
#             "paymentVerified": p.payment_verified,
#             "paymentReference": p.payment_reference,
#             "canUploadFastTrack": p.can_upload_fast_track,
#             "authorizationStatus": p.authorization_status,
#         })
#     return JsonResponse({"trainers": result})


# @require_roles("dunis_admin")
# @require_http_methods(["PATCH"])
# @csrf_exempt
# def dunis_toggle_fast_track(request, user_id):
#     try:
#         user = User.objects.select_related("profile").get(id=user_id)
#     except User.DoesNotExist:
#         return JsonResponse({"error": "User not found."}, status=404)

#     profile = user.profile
#     if profile.role != "trainer":
#         return JsonResponse({"error": "This user is not a trainer."}, status=400)

#     data = read_json(request)
#     profile.can_upload_fast_track = bool(data.get("canUploadFastTrack", not profile.can_upload_fast_track))
#     profile.save(update_fields=["can_upload_fast_track"])

#     if not profile.can_upload_fast_track:
#         Course.objects.filter(trainer=user, has_fast_track=True).update(has_fast_track=False)

#     return JsonResponse({"ok": True, "canUploadFastTrack": profile.can_upload_fast_track})


# @csrf_exempt
# @api_login_required
# @require_POST
# def paystack_initialize(request):
#     data = read_json(request)
#     email = data.get("email", "")
#     amount = data.get("amount", 50000)
#     if not email:
#         return validation_error("Email is required.", {"email": "Email is required."})

#     secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
#     if not secret_key:
#         return JsonResponse({"error": "Payment is not configured."}, status=500)

#     reference = f"SAED-{get_random_string(12).upper()}"
#     profile = Profile.objects.filter(user__email=email, role="trainer").first()
#     if profile:
#         profile.payment_reference = reference
#         profile.save(update_fields=["payment_reference"])

#     amount_kobo = int(float(amount) * 100)
#     payload = json.dumps({
#         "email": email,
#         "amount": amount_kobo,
#         "reference": reference,
#         "metadata": {"reference": reference},
#     }).encode()

#     req = urllib.request.Request(
#         "https://api.paystack.co/transaction/initialize",
#         data=payload,
#         headers={
#             "Authorization": f"Bearer {secret_key}",
#             "Content-Type": "application/json",
#         },
#         method="POST",
#     )
#     try:
#         with urllib.request.urlopen(req) as resp:
#             body = json.loads(resp.read().decode())
#         if body.get("status"):
#             return JsonResponse({
#                 "ok": True,
#                 "reference": reference,
#                 "authorization_url": body["data"]["authorization_url"],
#                 "access_code": body["data"]["access_code"],
#                 "message": "Payment initialized.",
#             })
#         return JsonResponse({"error": body.get("message", "Payment initialization failed.")}, status=400)
#     except urllib.error.HTTPError as e:
#         body = json.loads(e.read().decode()) if e.readable() else {}
#         return JsonResponse({"error": body.get("message", "Payment gateway error.")}, status=400)
#     except Exception:
#         return JsonResponse({"error": "Unable to connect to payment gateway."}, status=502)


# @api_login_required
# @require_http_methods(["POST"])
# def course_pay_initialize(request):
#     data = read_json(request)
#     course_id = data.get("courseId")
#     if not course_id:
#         return validation_error("Course ID is required.", {"courseId": "Course ID is required."})
#     try:
#         course = Course.objects.get(id=course_id, is_active=True)
#     except Course.DoesNotExist:
#         return JsonResponse({"error": "Course not found."}, status=404)
#     if course.price <= 0:
#         return JsonResponse({"error": "This course is free."}, status=400)
#     confirmed_count = CourseEnrollment.objects.filter(
#         course=course, status="confirmed"
#     ).count()
#     if confirmed_count >= course.max_students:
#         return JsonResponse({
#             "error": "This course is full. No slots available.",
#             "slotsFull": True,
#         }, status=400)
#     enrollment, _ = CourseEnrollment.objects.get_or_create(
#         student=request.user, course=course,
#         defaults={"amount_paid": course.price},
#     )
#     if enrollment.status == "confirmed":
#         return JsonResponse({"error": "You already have access to this course."}, status=400)
#     if enrollment.status == "pending":
#         return JsonResponse({"error": "Payment already pending trainer confirmation.", "pending": True}, status=400)
#     if enrollment.status == "refunded":
#         enrollment.status = "pending"
#         enrollment.refund_requested = False
#         enrollment.refund_requested_at = None
#         enrollment.refund_processed = False
#         enrollment.refund_processed_at = None
#         enrollment.refund_note = ""
#     reference = f"SAED-COURSE-{get_random_string(12).upper()}"
#     enrollment.payment_reference = reference
#     enrollment.amount_paid = course.price
#     enrollment.save(update_fields=["payment_reference", "amount_paid", "status", "refund_requested", "refund_requested_at", "refund_processed", "refund_processed_at", "refund_note"])

#     secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
#     if not secret_key:
#         return JsonResponse({"error": "Payment is not configured."}, status=500)

#     amount_kobo = int(float(course.price) * 100)
#     payload = json.dumps({
#         "email": request.user.email,
#         "amount": amount_kobo,
#         "reference": reference,
#         "metadata": {"reference": reference, "course_id": course.id},
#     }).encode()

#     req = urllib.request.Request(
#         "https://api.paystack.co/transaction/initialize",
#         data=payload,
#         headers={
#             "Authorization": f"Bearer {secret_key}",
#             "Content-Type": "application/json",
#         },
#         method="POST",
#     )
#     try:
#         with urllib.request.urlopen(req) as resp:
#             body = json.loads(resp.read().decode())
#         if body.get("status"):
#             return JsonResponse({
#                 "ok": True,
#                 "reference": reference,
#                 "authorization_url": body["data"]["authorization_url"],
#                 "access_code": body["data"]["access_code"],
#                 "amount": str(course.price),
#                 "courseTitle": course.title,
#             })
#         return JsonResponse({"error": body.get("message", "Payment initialization failed.")}, status=400)
#     except urllib.error.HTTPError as e:
#         body = json.loads(e.read().decode()) if e.readable() else {}
#         return JsonResponse({"error": body.get("message", "Payment gateway error.")}, status=400)
#     except Exception:
#         return JsonResponse({"error": "Unable to connect to payment gateway."}, status=502)


# @api_login_required
# @require_http_methods(["POST"])
# def course_pay_verify(request):
#     data = read_json(request)
#     reference = data.get("reference", "")
#     if not reference:
#         return validation_error("Reference is required.", {"reference": "Reference is required."})
#     enrollment = CourseEnrollment.objects.filter(
#         student=request.user, payment_reference=reference
#     ).first()
#     if not enrollment:
#         return JsonResponse({"error": "Payment record not found."}, status=404)
#     if enrollment.status == "pending":
#         return JsonResponse({"ok": True, "message": "Payment already pending trainer confirmation."})
#     if enrollment.status == "confirmed":
#         return JsonResponse({"ok": True, "message": "Already verified."})

#     secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
#     if secret_key:
#         req = urllib.request.Request(
#             f"https://api.paystack.co/transaction/verify/{reference}",
#             headers={"Authorization": f"Bearer {secret_key}"},
#         )
#         try:
#             with urllib.request.urlopen(req) as resp:
#                 body = json.loads(resp.read().decode())
#             if not body.get("status") or body.get("data", {}).get("status") != "success":
#                 msg = body.get("message", "Payment not successful.")
#                 return JsonResponse({"error": msg}, status=400)
#         except Exception:
#             return JsonResponse({"error": "Unable to verify payment with gateway."}, status=502)

#     enrollment.status = "pending"
#     enrollment.amount_paid = enrollment.course.price
#     enrollment.save(update_fields=["status", "amount_paid"])
#     return JsonResponse({"ok": True, "message": "Payment submitted. Waiting for trainer confirmation."})


# @api_login_required
# @require_http_methods(["GET"])
# def course_enrollment_status(request, course_id):
#     enrollment = CourseEnrollment.objects.filter(
#         student=request.user, course_id=course_id
#     ).first()
#     return JsonResponse({
#         "isPaid": enrollment.status == "confirmed" if enrollment else False,
#         "enrolled": enrollment is not None,
#         "status": enrollment.status if enrollment else None,
#     })


# @require_roles("trainer")
# @require_http_methods(["GET"])
# def trainer_pending_enrollments(request):
#     courses = Course.objects.filter(trainer=request.user, is_active=True)
#     enrollments = CourseEnrollment.objects.filter(
#         course__in=courses, status="pending"
#     ).select_related("student", "course")
#     result = []
#     for e in enrollments:
#         result.append({
#             "id": e.id,
#             "studentId": e.student.id,
#             "studentName": e.student.get_full_name() or e.student.email,
#             "studentEmail": e.student.email,
#             "courseId": e.course.id,
#             "courseTitle": e.course.title,
#             "amount": str(e.amount_paid),
#             "paymentReference": e.payment_reference,
#             "enrolledAt": e.enrolled_at.isoformat(),
#         })
#     return JsonResponse({"enrollments": result})


# @require_roles("trainer")
# @require_http_methods(["POST"])
# @csrf_exempt
# def trainer_confirm_enrollment(request, enrollment_id):
#     try:
#         enrollment = CourseEnrollment.objects.select_related("student", "course").get(
#             id=enrollment_id, course__trainer=request.user, status="pending"
#         )
#     except CourseEnrollment.DoesNotExist:
#         return JsonResponse({"error": "Enrollment not found."}, status=404)
#     enrollment.status = "confirmed"
#     enrollment.confirmed_by = request.user
#     enrollment.confirmed_at = now()
#     enrollment.save(update_fields=["status", "confirmed_by", "confirmed_at"])
#     try:
#         send_mail(
#             subject="SAED IMS - Course Enrollment Confirmed",
#             message=(
#                 f"Hello {enrollment.student.get_full_name()},\n\n"
#                 f"Your payment for \"{enrollment.course.title}\" has been confirmed by the trainer.\n"
#                 f"You now have full access to the course content.\n\n"
#                 f"Payment Reference: {enrollment.payment_reference}\n\n"
#                 f"Best regards,\nNYSC SAED IMS"
#             ),
#             from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"),
#             recipient_list=[enrollment.student.email],
#             fail_silently=True,
#         )
#     except Exception as exc:
#         logger.exception(f"Failed to send email in trainer_confirm_enrollment: {exc}")
#         sentry_sdk.capture_exception(exc)

#     return JsonResponse({"ok": True, "message": "Enrollment confirmed."})


# @require_roles("trainer")
# @require_http_methods(["POST"])
# @csrf_exempt
# def trainer_reject_enrollment(request, enrollment_id):
#     try:
#         enrollment = CourseEnrollment.objects.select_related("student", "course").get(
#             id=enrollment_id, course__trainer=request.user, status="pending"
#         )
#     except CourseEnrollment.DoesNotExist:
#         return JsonResponse({"error": "Enrollment not found."}, status=404)
#     enrollment.status = "rejected"
#     enrollment.confirmed_by = request.user
#     enrollment.confirmed_at = now()
#     enrollment.refund_requested = True
#     enrollment.refund_requested_at = now()
#     enrollment.save(update_fields=["status", "confirmed_by", "confirmed_at", "refund_requested", "refund_requested_at"])
#     try:
#         send_mail(
#             subject="SAED IMS - Course Payment Not Verified",
#             message=(
#                 f"Hello {enrollment.student.get_full_name()},\n\n"
#                 f"Your payment for \"{enrollment.course.title}\" could not be verified.\n"
#                 f"A refund has been initiated for ₦{enrollment.amount_paid}.\n"
#                 f"Please allow 3-5 business days for the refund to reflect.\n\n"
#                 f"Payment Reference: {enrollment.payment_reference}\n\n"
#                 f"Best regards,\nNYSC SAED IMS"
#             ),
#             from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"),
#             recipient_list=[enrollment.student.email],
#             fail_silently=True,
#         )
    
#     except Exception as exc:
#         logger.exception(f"Failed to send email in trainer_confirm_enrollment: {exc}")
#         sentry_sdk.capture_exception(exc)
    
#     _notify_admins(
#         title="Refund Required",
#         message=f"Payment rejected for {enrollment.student.get_full_name()} ({enrollment.course.title}, ₦{enrollment.amount_paid}). Refund required.",
#         reason="admin_update",
#     )
#     return JsonResponse({"ok": True, "message": "Enrollment rejected. Refund has been flagged for processing."})


# @require_roles("saed_admin", "dunis_admin")
# @require_http_methods(["GET"])
# def admin_pending_refunds(request):
#     enrollments = CourseEnrollment.objects.filter(
#         refund_requested=True, refund_processed=False
#     ).select_related("student", "course", "course__trainer")
#     result = []
#     for e in enrollments:
#         result.append({
#             "id": e.id,
#             "studentName": e.student.get_full_name() or e.student.email,
#             "studentEmail": e.student.email,
#             "courseTitle": e.course.title,
#             "trainerName": e.course.trainer.get_full_name() or e.course.trainer.email,
#             "amount": str(e.amount_paid),
#             "paymentReference": e.payment_reference,
#             "status": e.status,
#             "refundRequestedAt": e.refund_requested_at.isoformat() if e.refund_requested_at else None,
#         })
#     return JsonResponse({"refunds": result})


# @require_roles("saed_admin", "dunis_admin")
# @require_http_methods(["POST"])
# @csrf_exempt
# def admin_process_refund(request, enrollment_id):
#     data = read_json(request)
#     note = data.get("note", "")
#     try:
#         enrollment = CourseEnrollment.objects.select_related("student", "course").get(
#             id=enrollment_id, refund_requested=True, refund_processed=False
#         )
#     except CourseEnrollment.DoesNotExist:
#         return JsonResponse({"error": "Refund not found."}, status=404)
#     enrollment.refund_processed = True
#     enrollment.refund_processed_at = now()
#     enrollment.refund_note = note
#     enrollment.status = "refunded"
#     enrollment.save(update_fields=["refund_processed", "refund_processed_at", "refund_note", "status"])
#     try:
#         send_mail(
#             subject="SAED IMS - Refund Processed",
#             message=(
#                 f"Hello {enrollment.student.get_full_name()},\n\n"
#                 f"Your refund of ₦{enrollment.amount_paid} for \"{enrollment.course.title}\" has been processed.\n"
#                 f"Please allow 3-5 business days for the refund to reflect in your account.\n\n"
#                 f"Payment Reference: {enrollment.payment_reference}\n"
#                 f"{'Note: ' + note if note else ''}\n\n"
#                 f"Best regards,\nNYSC SAED IMS"
#             ),
#             from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"),
#             recipient_list=[enrollment.student.email],
#             fail_silently=True,
#         )
    
#     except Exception as exc:
#         logger.exception(f"Failed to send email in admin_process_refund: {exc}")
#         sentry_sdk.capture_exception(exc)
        
#     return JsonResponse({"ok": True, "message": "Refund processed."})


# @require_roles("saed_admin", "dunis_admin")
# @require_http_methods(["POST"])
# @csrf_exempt
# def admin_reject_refund(request, enrollment_id):
#     data = read_json(request)
#     note = data.get("note", "")
#     try:
#         enrollment = CourseEnrollment.objects.select_related("student", "course").get(
#             id=enrollment_id, refund_requested=True, refund_processed=False
#         )
#     except CourseEnrollment.DoesNotExist:
#         return JsonResponse({"error": "Refund not found."}, status=404)
#     enrollment.refund_processed = True
#     enrollment.refund_processed_at = now()
#     enrollment.refund_note = note or "Refund denied by admin"
#     enrollment.save(update_fields=["refund_processed", "refund_processed_at", "refund_note"])
#     try:
#         send_mail(
#             subject="SAED IMS - Refund Denied",
#             message=(
#                 f"Hello {enrollment.student.get_full_name()},\n\n"
#                 f"Your refund request for ₦{enrollment.amount_paid} ({enrollment.course.title}) has been denied.\n"
#                 f"{'Reason: ' + note if note else ''}\n\n"
#                 f"Payment Reference: {enrollment.payment_reference}\n\n"
#                 f"Best regards,\nNYSC SAED IMS"
#             ),
#             from_email=getattr(django_settings, "DEFAULT_FROM_EMAIL", "noreply@saed-ims.com"),
#             recipient_list=[enrollment.student.email],
#             fail_silently=True,
#         )
    
#     except Exception as exc:
#         logger.exception(f"Failed to send email in admin_process_refund: {exc}")
#         sentry_sdk.capture_exception(exc)
        
#     return JsonResponse({"ok": True, "message": "Refund denied."})


# def _parse_iso8601_duration(text):
#     m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
#     if m:
#         return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
#     return None


# def _fetch_youtube_duration(url):
#     video_id = None
#     m = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", url)
#     if m:
#         video_id = m.group(1)
#     if not video_id:
#         return None

#     page_url = f"https://www.youtube.com/watch?v={video_id}"
#     try:
#         req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
#         with urllib.request.urlopen(req, timeout=10) as resp:
#             html = resp.read().decode("utf-8", errors="ignore")

#         m = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
#         if m:
#             return int(m.group(1))

#         m = re.search(r'"approxDurationMs"\s*:\s*"(\d+)"', html)
#         if m:
#             return int(m.group(1)) // 1000

#         m = re.search(r'"duration"\s*:\s*"(PT[\dHMS]+)"', html)
#         if m:
#             return _parse_iso8601_duration(m.group(1))
        
#     except Exception as exc:
#         logger.exception(f"Failed to send email in admin_process_refund: {exc}")
#         sentry_sdk.capture_exception(exc)
        
#     return None


# def _fetch_vimeo_duration(url):
#     try:
#         oembed_url = f"https://vimeo.com/api/oembed.json?url={urllib.request.quote(url)}"
#         req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
#         with urllib.request.urlopen(req, timeout=10) as resp:
#             data = json.loads(resp.read().decode("utf-8"))
#         return data.get("duration")
#     except Exception as exc:
#         logger.exception(f"Failed to send email in trainer_signup_view: {exc}")
#         sentry_sdk.capture_exception(exc)
#     return None


# @require_roles("trainer")
# @require_authorized_trainer
# @require_http_methods(["POST"])
# @csrf_exempt
# def fetch_video_duration(request):
#     data = read_json(request)
#     url = data.get("url", "").strip()
#     if not url:
#         return validation_error("URL is required.", {"url": "Enter a video URL."})

#     duration = None
#     if "youtube.com" in url or "youtu.be" in url:
#         duration = _fetch_youtube_duration(url)
#     elif "vimeo.com" in url:
#         duration = _fetch_vimeo_duration(url)

#     if duration is None:
#         return JsonResponse({"error": "Could not fetch duration. Enter it manually."}, status=422)

#     return JsonResponse({"durationSeconds": duration})


# @api_login_required
# @require_http_methods(["GET"])
# def notification_list(request):
#     notifications = Notification.objects.filter(user=request.user).order_by("-created_at")[:50]
#     user_role = role_for(request.user)
#     filtered = []
#     for n in notifications:
#         # Admin activities are not visible to anyone
#         if n.reason == "admin_update":
#             continue
#         # SAED admin cannot see DUNIS admin activities
#         if user_role == "saed_admin" and n.created_by_role == "dunis_admin":
#             continue
#         # DUNIS admin can see SAED admin activities (no filter needed)
#         filtered.append(n)
#     return JsonResponse({
#         "notifications": [
#             {
#                 "id": n.id,
#                 "title": n.title,
#                 "message": n.message,
#                 "reason": n.reason,
#                 "isRead": n.is_read,
#                 "createdAt": n.created_at.isoformat(),
#             }
#             for n in filtered[:50]
#         ]
#     })


# @api_login_required
# @require_POST
# def notification_mark_read(request, notification_id):
#     try:
#         notification = Notification.objects.get(id=notification_id, user=request.user)
#     except Notification.DoesNotExist:
#         return JsonResponse({"error": "Notification not found."}, status=404)
#     notification.is_read = True
#     notification.save(update_fields=["is_read"])
#     return JsonResponse({"ok": True})


# @api_login_required
# @require_POST
# def notification_mark_all_read(request):
#     count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
#     return JsonResponse({"ok": True, "marked": count})


# @api_login_required
# @require_POST
# def submit_complaint(request):
#     data = read_json(request)
#     subject = data.get("subject", "").strip()
#     message = data.get("message", "").strip()
#     if not subject:
#         return validation_error("Subject is required.", {"subject": "Enter a subject."})
#     if not message:
#         return validation_error("Message is required.", {"message": "Enter your complaint."})

#     sender_name = request.user.get_full_name() or request.user.email
#     admin_users = User.objects.filter(profile__role__in=["saed_admin", "dunis_admin"])
#     for admin in admin_users:
#         Complaint.objects.create(
#             user=admin,
#             subject=subject,
#             message=f"From: {sender_name} ({request.user.email})\n\n{message}",
#         )

#     return JsonResponse({"ok": True, "message": "Complaint submitted successfully."}, status=201)




# ═══════════════════════════════════════════════════════════════════════════════
# DUNIS ADMIN VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@require_roles("dunis_admin")
@require_http_methods(["GET"])
def dunis_pending_payments(request):
    """Get trainers with pending payments."""
    try:
        profiles = Profile.objects.filter(
            role="trainer",
            is_authorized=True,
            has_paid=False,
        ).select_related("user")

        result = []
        for p in profiles:
            result.append({
                "id": p.user.id,
                "fullName": p.user.get_full_name() or p.user.email,
                "email": p.user.email,
                "phone": p.phone,
                "specialization": p.specialization,
                "companyName": p.company_name,
                "hasPaid": p.has_paid,
                "paymentVerified": p.payment_verified,
                "authorizedAt": p.authorized_at.isoformat() if p.authorized_at else None,
            })
        return JsonResponse({"trainers": result})

    except Exception as exc:
        _log_error("Pending payments error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load pending payments."}, status=500
        )


@require_roles("dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def dunis_confirm_payment(request):
    """Confirm trainer payment."""
    data = read_json(request)
    user_id = data.get("userId")
    reference = data.get("reference", "")

    if not user_id:
        return validation_error(
            "User ID is required.",
            {"userId": "Select a trainer."}
        )

    try:
        user = User.objects.select_related("profile").get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "Trainer not found."}, status=404)

    profile = user.profile
    if profile.role != "trainer":
        return JsonResponse(
            {"error": "This user is not a trainer."}, status=400
        )

    try:
        profile.has_paid = True
        profile.payment_verified = True
        profile.payment_reference = reference
        profile.payment_verified_at = now()
        profile.save(update_fields=[
            "has_paid", "payment_verified", "payment_reference", "payment_verified_at"
        ])

        _send_email_async(
            subject="SAED IMS - Account Activated!",
            message=(
                f"Hello {user.get_full_name()},\n\n"
                f"Your payment has been verified and your account has been activated.\n"
                f"You can now log in and start using the SAED IMS platform.\n\n"
                f"Payment Reference: {reference}\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[user.email],
        )

        _log_info(f"Payment confirmed for user {user_id}")
        return JsonResponse({
            "ok": True,
            "message": "Payment confirmed. Account activated."
        })

    except Exception as exc:
        _log_error(f"Payment confirmation error for {user_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to confirm payment."}, status=500
        )


@require_roles("dunis_admin")
@require_http_methods(["GET"])
def dunis_all_trainers(request):
    """Get all trainers for DUNIS admin."""
    try:
        profiles = Profile.objects.filter(role="trainer").select_related("user").order_by(
            "-created_at" if hasattr(Profile, "created_at") else "user__first_name"
        )

        result = []
        for p in profiles:
            result.append({
                "id": p.user.id,
                "fullName": p.user.get_full_name() or p.user.email,
                "email": p.user.email,
                "specialization": p.specialization,
                "isAuthorized": p.is_authorized,
                "isActive": p.user.is_active,
                "hasPaid": p.has_paid,
                "paymentVerified": p.payment_verified,
                "paymentReference": p.payment_reference,
                "canUploadFastTrack": p.can_upload_fast_track,
                "authorizationStatus": p.authorization_status,
            })
        return JsonResponse({"trainers": result})

    except Exception as exc:
        _log_error("DUNIS trainers list error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load trainers."}, status=500
        )


@require_roles("dunis_admin")
@require_http_methods(["PATCH"])
@csrf_exempt
def dunis_toggle_fast_track(request, user_id):
    """Toggle fast track upload permission for trainer."""
    try:
        user = User.objects.select_related("profile").get(id=user_id)
    except User.DoesNotExist:
        return JsonResponse({"error": "User not found."}, status=404)

    profile = user.profile
    if profile.role != "trainer":
        return JsonResponse(
            {"error": "This user is not a trainer."}, status=400
        )

    data = read_json(request)
    try:
        profile.can_upload_fast_track = bool(
            data.get("canUploadFastTrack", not profile.can_upload_fast_track)
        )
        profile.save(update_fields=["can_upload_fast_track"])

        if not profile.can_upload_fast_track:
            Course.objects.filter(trainer=user, has_fast_track=True).update(
                has_fast_track=False
            )

        _log_info(f"Fast track toggled for user {user_id}: {profile.can_upload_fast_track}")
        return JsonResponse({
            "ok": True,
            "canUploadFastTrack": profile.can_upload_fast_track
        })

    except Exception as exc:
        _log_error(f"Fast track toggle error for {user_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to toggle fast track."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAYMENT VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@csrf_exempt
@api_login_required
@require_POST
def paystack_initialize(request):
    """Initialize Paystack payment for trainer."""
    data = read_json(request)
    email = data.get("email", "")
    amount = data.get("amount", 50000)

    if not email:
        return validation_error(
            "Email is required.",
            {"email": "Email is required."}
        )

    secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
    if not secret_key:
        _log_error("Paystack secret key not configured")
        return JsonResponse(
            {"error": "Payment is not configured."}, status=500
        )

    reference = f"SAED-{get_random_string(12).upper()}"

    try:
        profile = Profile.objects.filter(user__email=email, role="trainer").first()
        if profile:
            profile.payment_reference = reference
            profile.save(update_fields=["payment_reference"])
    except Exception as exc:
        _log_error("Paystack profile update error", exc=exc)

    amount_kobo = int(float(amount) * 100)
    payload = json.dumps({
        "email": email,
        "amount": amount_kobo,
        "reference": reference,
        "metadata": {"reference": reference},
    }).encode()

    req = urllib.request.Request(
        "https://api.paystack.co/transaction/initialize",
        data=payload,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if body.get("status"):
            _log_info(f"Paystack initialized for {email}")
            return JsonResponse({
                "ok": True,
                "reference": reference,
                "authorization_url": body["data"]["authorization_url"],
                "access_code": body["data"]["access_code"],
                "message": "Payment initialized.",
            })
        _log_warning("Paystack initialization failed", extra={"response": body})
        return JsonResponse(
            {"error": body.get("message", "Payment initialization failed.")},
            status=400
        )
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        _log_error("Paystack HTTP error", extra={"response": body})
        return JsonResponse(
            {"error": body.get("message", "Payment gateway error.")},
            status=400
        )
    except urllib.error.URLError as e:
        _log_error("Paystack connection error", exc=e)
        return JsonResponse(
            {"error": "Unable to connect to payment gateway."},
            status=502
        )
    except Exception as exc:
        _log_error("Paystack unexpected error", exc=exc)
        return JsonResponse(
            {"error": "Payment initialization failed."}, status=500
        )


@api_login_required
@require_http_methods(["POST"])
def course_pay_initialize(request):
    """Initialize course payment."""
    data = read_json(request)
    course_id = data.get("courseId")

    if not course_id:
        return validation_error(
            "Course ID is required.",
            {"courseId": "Course ID is required."}
        )

    try:
        course = Course.objects.get(id=course_id, is_active=True)
    except Course.DoesNotExist:
        return JsonResponse({"error": "Course not found."}, status=404)

    if course.price <= 0:
        return JsonResponse({"error": "This course is free."}, status=400)

    try:
        confirmed_count = CourseEnrollment.objects.filter(
            course=course, status="confirmed"
        ).count()
        if confirmed_count >= course.max_students:
            return JsonResponse({
                "error": "This course is full. No slots available.",
                "slotsFull": True,
            }, status=400)

        enrollment, _ = CourseEnrollment.objects.get_or_create(
            student=request.user,
            course=course,
            defaults={"amount_paid": course.price},
        )

        if enrollment.status == "confirmed":
            return JsonResponse(
                {"error": "You already have access to this course."}, status=400
            )
        if enrollment.status == "pending":
            return JsonResponse({
                "error": "Payment already pending trainer confirmation.",
                "pending": True
            }, status=400)

        if enrollment.status == "refunded":
            enrollment.status = "pending"
            enrollment.refund_requested = False
            enrollment.refund_requested_at = None
            enrollment.refund_processed = False
            enrollment.refund_processed_at = None
            enrollment.refund_note = ""

        reference = f"SAED-COURSE-{get_random_string(12).upper()}"
        enrollment.payment_reference = reference
        enrollment.amount_paid = course.price
        enrollment.save(update_fields=[
            "payment_reference", "amount_paid", "status",
            "refund_requested", "refund_requested_at",
            "refund_processed", "refund_processed_at", "refund_note"
        ])

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            _log_error("Paystack secret key not configured")
            return JsonResponse(
                {"error": "Payment is not configured."}, status=500
            )

        amount_kobo = int(float(course.price) * 100)
        payload = json.dumps({
            "email": request.user.email,
            "amount": amount_kobo,
            "reference": reference,
            "metadata": {"reference": reference, "course_id": course.id},
        }).encode()

        req = urllib.request.Request(
            "https://api.paystack.co/transaction/initialize",
            data=payload,
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
        if body.get("status"):
            _log_info(f"Course payment initialized for user {request.user.id}")
            return JsonResponse({
                "ok": True,
                "reference": reference,
                "authorization_url": body["data"]["authorization_url"],
                "access_code": body["data"]["access_code"],
                "amount": str(course.price),
                "courseTitle": course.title,
            })
        _log_warning("Course payment initialization failed", extra={"response": body})
        return JsonResponse(
            {"error": body.get("message", "Payment initialization failed.")},
            status=400
        )

    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        _log_error("Course payment HTTP error", extra={"response": body})
        return JsonResponse(
            {"error": body.get("message", "Payment gateway error.")},
            status=400
        )
    except urllib.error.URLError as e:
        _log_error("Course payment connection error", exc=e)
        return JsonResponse(
            {"error": "Unable to connect to payment gateway."},
            status=502
        )
    except Exception as exc:
        _log_error("Course payment initialization error", exc=exc)
        return JsonResponse(
            {"error": "Payment initialization failed."}, status=500
        )


@api_login_required
@require_http_methods(["POST"])
def course_pay_verify(request):
    """Verify course payment."""
    data = read_json(request)
    reference = data.get("reference", "")

    if not reference:
        return validation_error(
            "Reference is required.",
            {"reference": "Reference is required."}
        )

    try:
        enrollment = CourseEnrollment.objects.filter(
            student=request.user, payment_reference=reference
        ).first()
        if not enrollment:
            return JsonResponse(
                {"error": "Payment record not found."}, status=404
            )
        if enrollment.status == "pending":
            return JsonResponse({
                "ok": True,
                "message": "Payment already pending trainer confirmation."
            })
        if enrollment.status == "confirmed":
            return JsonResponse({"ok": True, "message": "Already verified."})

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if secret_key:
            req = urllib.request.Request(
                f"https://api.paystack.co/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {secret_key}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = json.loads(resp.read().decode())
                if not body.get("status") or body.get("data", {}).get("status") != "success":
                    msg = body.get("message", "Payment not successful.")
                    _log_warning("Payment verification failed", extra={"reference": reference})
                    return JsonResponse({"error": msg}, status=400)
            except Exception as exc:
                _log_error("Payment verification gateway error", exc=exc)
                return JsonResponse(
                    {"error": "Unable to verify payment with gateway."},
                    status=502
                )

        enrollment.status = "pending"
        enrollment.amount_paid = enrollment.course.price
        enrollment.save(update_fields=["status", "amount_paid"])
        _log_info(f"Payment verified for enrollment {enrollment.id}")
        return JsonResponse({
            "ok": True,
            "message": "Payment submitted. Waiting for trainer confirmation."
        })

    except Exception as exc:
        _log_error("Payment verification error", exc=exc)
        return JsonResponse(
            {"error": "Payment verification failed."}, status=500
        )


@api_login_required
@require_http_methods(["GET"])
def course_enrollment_status(request, course_id):
    """Get enrollment status for a course."""
    try:
        enrollment = CourseEnrollment.objects.filter(
            student=request.user, course_id=course_id
        ).first()
        return JsonResponse({
            "isPaid": enrollment.status == "confirmed" if enrollment else False,
            "enrolled": enrollment is not None,
            "status": enrollment.status if enrollment else None,
        })
    except Exception as exc:
        _log_error(f"Enrollment status error for course {course_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to get enrollment status."}, status=500
        )


@require_roles("trainer")
@require_http_methods(["GET"])
def trainer_pending_enrollments(request):
    """Get pending enrollments for trainer."""
    try:
        courses = Course.objects.filter(trainer=request.user, is_active=True)
        enrollments = CourseEnrollment.objects.filter(
            course__in=courses, status="pending"
        ).select_related("student", "course")

        result = []
        for e in enrollments:
            result.append({
                "id": e.id,
                "studentId": e.student.id,
                "studentName": e.student.get_full_name() or e.student.email,
                "studentEmail": e.student.email,
                "courseId": e.course.id,
                "courseTitle": e.course.title,
                "amount": str(e.amount_paid),
                "paymentReference": e.payment_reference,
                "enrolledAt": e.enrolled_at.isoformat(),
            })
        return JsonResponse({"enrollments": result})

    except Exception as exc:
        _log_error("Pending enrollments error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load enrollments."}, status=500
        )


@require_roles("trainer")
@require_http_methods(["POST"])
@csrf_exempt
def trainer_confirm_enrollment(request, enrollment_id):
    """Confirm a course enrollment."""
    try:
        enrollment = CourseEnrollment.objects.select_related(
            "student", "course"
        ).get(id=enrollment_id, course__trainer=request.user, status="pending")
    except CourseEnrollment.DoesNotExist:
        return JsonResponse({"error": "Enrollment not found."}, status=404)

    try:
        enrollment.status = "confirmed"
        enrollment.confirmed_by = request.user
        enrollment.confirmed_at = now()
        enrollment.save(update_fields=["status", "confirmed_by", "confirmed_at"])

        _send_email_async(
            subject="SAED IMS - Course Enrollment Confirmed",
            message=(
                f"Hello {enrollment.student.get_full_name()},\n\n"
                f"Your payment for \"{enrollment.course.title}\" has been confirmed by the trainer.\n"
                f"You now have full access to the course content.\n\n"
                f"Payment Reference: {enrollment.payment_reference}\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[enrollment.student.email],
        )

        _log_info(f"Enrollment {enrollment_id} confirmed by trainer {request.user.id}")
        return JsonResponse({"ok": True, "message": "Enrollment confirmed."})

    except Exception as exc:
        _log_error(f"Enrollment confirmation error for {enrollment_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to confirm enrollment."}, status=500
        )


@require_roles("trainer")
@require_http_methods(["POST"])
@csrf_exempt
def trainer_reject_enrollment(request, enrollment_id):
    """Reject a course enrollment and flag for refund."""
    try:
        enrollment = CourseEnrollment.objects.select_related(
            "student", "course"
        ).get(id=enrollment_id, course__trainer=request.user, status="pending")
    except CourseEnrollment.DoesNotExist:
        return JsonResponse({"error": "Enrollment not found."}, status=404)

    try:
        enrollment.status = "rejected"
        enrollment.confirmed_by = request.user
        enrollment.confirmed_at = now()
        enrollment.refund_requested = True
        enrollment.refund_requested_at = now()
        enrollment.save(update_fields=[
            "status", "confirmed_by", "confirmed_at",
            "refund_requested", "refund_requested_at"
        ])

        _send_email_async(
            subject="SAED IMS - Course Payment Not Verified",
            message=(
                f"Hello {enrollment.student.get_full_name()},\n\n"
                f"Your payment for \"{enrollment.course.title}\" could not be verified.\n"
                f"A refund has been initiated for ₦{enrollment.amount_paid}.\n"
                f"Please allow 3-5 business days for the refund to reflect.\n\n"
                f"Payment Reference: {enrollment.payment_reference}\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[enrollment.student.email],
        )

        _notify_admins(
            title="Refund Required",
            message=f"Payment rejected for {enrollment.student.get_full_name()} ({enrollment.course.title}, ₦{enrollment.amount_paid}). Refund required.",
            reason="admin_update",
        )

        _log_info(f"Enrollment {enrollment_id} rejected by trainer {request.user.id}")
        return JsonResponse({
            "ok": True,
            "message": "Enrollment rejected. Refund has been flagged for processing."
        })

    except Exception as exc:
        _log_error(f"Enrollment rejection error for {enrollment_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to reject enrollment."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["GET"])
def admin_pending_refunds(request):
    """Get pending refunds for admin."""
    try:
        enrollments = CourseEnrollment.objects.filter(
            refund_requested=True, refund_processed=False
        ).select_related("student", "course", "course__trainer")

        result = []
        for e in enrollments:
            result.append({
                "id": e.id,
                "studentName": e.student.get_full_name() or e.student.email,
                "studentEmail": e.student.email,
                "courseTitle": e.course.title,
                "trainerName": e.course.trainer.get_full_name() or e.course.trainer.email,
                "amount": str(e.amount_paid),
                "paymentReference": e.payment_reference,
                "status": e.status,
                "refundRequestedAt": e.refund_requested_at.isoformat() if e.refund_requested_at else None,
            })
        return JsonResponse({"refunds": result})

    except Exception as exc:
        _log_error("Pending refunds error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load refunds."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def admin_process_refund(request, enrollment_id):
    """Process a refund."""
    data = read_json(request)
    note = data.get("note", "")

    try:
        enrollment = CourseEnrollment.objects.select_related(
            "student", "course"
        ).get(id=enrollment_id, refund_requested=True, refund_processed=False)
    except CourseEnrollment.DoesNotExist:
        return JsonResponse({"error": "Refund not found."}, status=404)

    try:
        enrollment.refund_processed = True
        enrollment.refund_processed_at = now()
        enrollment.refund_note = note
        enrollment.status = "refunded"
        enrollment.save(update_fields=[
            "refund_processed", "refund_processed_at", "refund_note", "status"
        ])

        _send_email_async(
            subject="SAED IMS - Refund Processed",
            message=(
                f"Hello {enrollment.student.get_full_name()},\n\n"
                f"Your refund of ₦{enrollment.amount_paid} for \"{enrollment.course.title}\" has been processed.\n"
                f"Please allow 3-5 business days for the refund to reflect in your account.\n\n"
                f"Payment Reference: {enrollment.payment_reference}\n"
                f"{'Note: ' + note if note else ''}\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[enrollment.student.email],
        )

        _log_info(f"Refund processed for enrollment {enrollment_id}")
        return JsonResponse({"ok": True, "message": "Refund processed."})

    except Exception as exc:
        _log_error(f"Refund processing error for {enrollment_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to process refund."}, status=500
        )


@require_roles("saed_admin", "dunis_admin")
@require_http_methods(["POST"])
@csrf_exempt
def admin_reject_refund(request, enrollment_id):
    """Reject a refund request."""
    data = read_json(request)
    note = data.get("note", "")

    try:
        enrollment = CourseEnrollment.objects.select_related(
            "student", "course"
        ).get(id=enrollment_id, refund_requested=True, refund_processed=False)
    except CourseEnrollment.DoesNotExist:
        return JsonResponse({"error": "Refund not found."}, status=404)

    try:
        enrollment.refund_processed = True
        enrollment.refund_processed_at = now()
        enrollment.refund_note = note or "Refund denied by admin"
        enrollment.save(update_fields=[
            "refund_processed", "refund_processed_at", "refund_note"
        ])

        _send_email_async(
            subject="SAED IMS - Refund Denied",
            message=(
                f"Hello {enrollment.student.get_full_name()},\n\n"
                f"Your refund request for ₦{enrollment.amount_paid} ({enrollment.course.title}) has been denied.\n"
                f"{'Reason: ' + note if note else ''}\n\n"
                f"Payment Reference: {enrollment.payment_reference}\n\n"
                f"Best regards,\nNYSC SAED IMS"
            ),
            recipient_list=[enrollment.student.email],
        )

        _log_info(f"Refund rejected for enrollment {enrollment_id}")
        return JsonResponse({"ok": True, "message": "Refund denied."})

    except Exception as exc:
        _log_error(f"Refund rejection error for {enrollment_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to reject refund."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# VIDEO DURATION HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def _parse_iso8601_duration(text):
    """Parse ISO 8601 duration string to seconds."""
    if not text:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
    if m:
        return (int(m.group(1) or 0) * 3600 +
                int(m.group(2) or 0) * 60 +
                int(m.group(3) or 0))
    return None


def _fetch_youtube_duration(url):
    """Fetch video duration from YouTube."""
    video_id = None
    m = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", url)
    if m:
        video_id = m.group(1)
    if not video_id:
        return None

    page_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        m = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
        if m:
            return int(m.group(1))

        m = re.search(r'"approxDurationMs"\s*:\s*"(\d+)"', html)
        if m:
            return int(m.group(1)) // 1000

        m = re.search(r'"duration"\s*:\s*"(PT[\dHMS]+)"', html)
        if m:
            return _parse_iso8601_duration(m.group(1))
    except Exception as exc:
        _log_error(f"YouTube duration fetch failed for {url}", exc=exc)
    return None


def _fetch_vimeo_duration(url):
    """Fetch video duration from Vimeo."""
    try:
        oembed_url = f"https://vimeo.com/api/oembed.json?url={urllib.request.quote(url)}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("duration")
    except Exception as exc:
        _log_error(f"Vimeo duration fetch failed for {url}", exc=exc)
    return None


@require_roles("trainer")
@require_authorized_trainer
@require_http_methods(["POST"])
@csrf_exempt
def fetch_video_duration(request):
    """Fetch video duration from URL."""
    data = read_json(request)
    url = data.get("url", "").strip()

    if not url:
        return validation_error(
            "URL is required.",
            {"url": "Enter a video URL."}
        )

    duration = None
    if "youtube.com" in url or "youtu.be" in url:
        duration = _fetch_youtube_duration(url)
    elif "vimeo.com" in url:
        duration = _fetch_vimeo_duration(url)

    if duration is None:
        return JsonResponse(
            {"error": "Could not fetch duration. Enter it manually."},
            status=422
        )

    return JsonResponse({"durationSeconds": duration})


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATION VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@api_login_required
@require_http_methods(["GET"])
def notification_list(request):
    """Get notifications for current user."""
    try:
        notifications = Notification.objects.filter(
            user=request.user
        ).order_by("-created_at")[:50]
        user_role = role_for(request.user)
        filtered = []

        for n in notifications:
            # Admin activities are not visible to anyone
            if n.reason == "admin_update":
                continue
            # SAED admin cannot see DUNIS admin activities
            if user_role == "saed_admin" and n.created_by_role == "dunis_admin":
                continue
            # DUNIS admin can see SAED admin activities (no filter needed)
            filtered.append(n)

        return JsonResponse({
            "notifications": [
                {
                    "id": n.id,
                    "title": n.title,
                    "message": n.message,
                    "reason": n.reason,
                    "isRead": n.is_read,
                    "createdAt": n.created_at.isoformat(),
                }
                for n in filtered[:50]
            ]
        })

    except Exception as exc:
        _log_error("Notification list error", exc=exc)
        return JsonResponse(
            {"error": "Failed to load notifications."}, status=500
        )


@api_login_required
@require_POST
def notification_mark_read(request, notification_id):
    """Mark a notification as read."""
    try:
        notification = Notification.objects.get(
            id=notification_id, user=request.user
        )
    except Notification.DoesNotExist:
        return JsonResponse({"error": "Notification not found."}, status=404)

    try:
        notification.is_read = True
        notification.save(update_fields=["is_read"])
        return JsonResponse({"ok": True})
    except Exception as exc:
        _log_error(f"Notification mark read error for {notification_id}", exc=exc)
        return JsonResponse(
            {"error": "Failed to mark notification as read."}, status=500
        )


@api_login_required
@require_POST
def notification_mark_all_read(request):
    """Mark all notifications as read."""
    try:
        count = Notification.objects.filter(
            user=request.user, is_read=False
        ).update(is_read=True)
        return JsonResponse({"ok": True, "marked": count})
    except Exception as exc:
        _log_error("Mark all notifications read error", exc=exc)
        return JsonResponse(
            {"error": "Failed to mark notifications as read."}, status=500
        )


# ═══════════════════════════════════════════════════════════════════════════════
# COMPLAINT VIEWS
# ═══════════════════════════════════════════════════════════════════════════════
@api_login_required
@require_POST
def submit_complaint(request):
    """Submit a complaint to admins."""
    data = read_json(request)
    subject = data.get("subject", "").strip()
    message = data.get("message", "").strip()

    if not subject:
        return validation_error(
            "Subject is required.",
            {"subject": "Enter a subject."}
        )
    if not message:
        return validation_error(
            "Message is required.",
            {"message": "Enter your complaint."}
        )

    try:
        sender_name = request.user.get_full_name() or request.user.email
        admin_users = User.objects.filter(profile__role__in=["saed_admin", "dunis_admin"])
        complaints = []
        for admin in admin_users:
            complaints.append(Complaint(
                user=admin,
                subject=subject,
                message=f"From: {sender_name} ({request.user.email})\n\n{message}",
            ))
        if complaints:
            Complaint.objects.bulk_create(complaints)

        _log_info(f"Complaint submitted by user {request.user.id}")
        return JsonResponse(
            {"ok": True, "message": "Complaint submitted successfully."},
            status=201
        )

    except Exception as exc:
        _log_error("Complaint submission error", exc=exc)
        return JsonResponse(
            {"error": "Failed to submit complaint."}, status=500
        )

