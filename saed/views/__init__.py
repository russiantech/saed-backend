"""
SAED IMS API Views — split into modules.

Re-exports all views for backward-compatible url references (views.health, etc.).
"""

from .base import (
    _log_error, _log_info, _log_warning,
    _send_email_async, _notify_admins, _notify_admins_email, _notify_user,
    read_json, role_for, validation_error, clean_email,
    user_payload, program_payload, application_payload,
    program_categories_payload, trainer_payload, trainers_payload,
    managed_programs_for, managed_applications_for, trainer_program_payload,
    course_payload, connection_payload, lesson_payload,
    IsAuthenticatedAPI, HasRole, IsAuthorizedTrainer,
)

# Basic views
from .base import _log_error as _  # ensure base loaded

def health(_request):
    """Liveness probe: the process is up. Does not touch the database."""
    from django.http import JsonResponse
    return JsonResponse({"status": "ok", "service": "SAED IMS API"})


def ready(_request):
    """Readiness probe: database reachable and private media storage writable (503 otherwise)."""
    import os
    import tempfile
    from django.conf import settings
    from django.db import connection
    from django.http import JsonResponse
    checks = {}
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        checks["database"] = connection.vendor
    except Exception:
        checks["database"] = "unavailable"
    try:
        os.makedirs(settings.PRIVATE_MEDIA_ROOT, exist_ok=True)
        with tempfile.TemporaryFile(dir=settings.PRIVATE_MEDIA_ROOT):
            pass
        checks["privateStorage"] = "writable"
    except Exception:
        checks["privateStorage"] = "unavailable"
    ok = checks["database"] != "unavailable" and checks["privateStorage"] == "writable"
    return JsonResponse({"status": "ok" if ok else "unavailable", "checks": checks}, status=200 if ok else 503)

from django.views.decorators.csrf import ensure_csrf_cookie
from django.middleware.csrf import get_token as _get_token
from django.http import JsonResponse as _JsonResponse

@ensure_csrf_cookie
def csrf(request):
    return _JsonResponse({"csrfToken": _get_token(request)})

def me(request):
    if not request.user.is_authenticated:
        return _JsonResponse({"user": None})
    return _JsonResponse({"user": user_payload(request.user, request)})


# Auth views (DRF APIViews)
from .auth import (
    LoginView, LogoutView, SignupView, TrainerSignupView, AdminSignupView,
    HiddenAdminSignupView,
    PasswordResetRequestView, VerifyResetCodeView, ResetPasswordView,
    SendCodeView, VerifyCodeView,
)

# Profile
from .profile import UpdateProfileView, PartnershipLetterView

# Programs
from .programs import (
    ProgramListView, ApplicationListView, ApplicationCreateView,
    ManageProgramsView, ManageProgramDetailView,
    RestrictProgramView, UnrestrictProgramView,
    ManageApplicationsView, ManageApplicationDetailView,
)

# Users
from .users import ManageUsersView, ManageUserDetailView

# Courses
from .courses import (
    CourseListView, ManageCoursesView, ManageCourseDetailView, MyEnrollmentsView, CourseEnrollView,
    AdminCoursesView, RestrictCourseView, UnrestrictCourseView, CourseDetailView,
    CourseProgressView, LessonCompleteView, CourseEnrollmentStatusView,
)

# Lessons (management, viewer, media, access)
from .lessons import (
    ManageLessonsView, ManageLessonDetailView, LessonUploadView, LessonReorderView,
    LessonViewerView, LessonMediaView, LessonRequestAccessView, LessonAccessListView,
    AccessRequestsView, LessonGrantAccessView, LessonRevokeAccessView,
)

# Trainers
from .trainers import (
    AvailableTrainersView, TrainerDetailView, MyTrainersView, ConnectTrainerView,
    MyConnectionsView, MyCorpersView, ConnectionApproveView, ConnectionRejectView,
    CorperProfileForTrainerView,
)

# Payments
from .payments import (
    PaymentConfigView, TrainerActivationInitView, VideoUploadInitView, LessonPayInitView,
    PaymentVerifyView, MyPaymentsView, PaymentDetailView, TrainerEarningsView, paystack_webhook,
    AdminPendingRefundsView, AdminProcessRefundView, AdminRejectRefundView,
)

# Public image upload
from .base import MediaUploadView

# Notifications
from .notifications import (
    NotificationListView, NotificationMarkReadView, NotificationMarkAllReadView,
)

# Complaints
from .complaints import SubmitComplaintView

# Dashboard
from .dashboard import DashboardView

# DUNIS
from .dunis import (
    DunisPendingPaymentsView, DunisConfirmPaymentView, DunisAllTrainersView,
    PlatformSettingsView, DunisPaymentsView, DunisPaymentResolveView, DunisAccessActivityView,
)

# In-Camp & Orientation
from .incamp import (
    PublicOrientationCampsView,
    ManageOrientationCampsView, ManageOrientationCampDetailView,
    InCampCoursesView, RunInCampDeactivationView,
)

from .bank import ResolveBankAccountView, ListPaystackBanksView, TrainerBankAccountView
