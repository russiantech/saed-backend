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
    course_payload, connection_payload, fast_track_video_payload,
    IsAuthenticatedAPI, HasRole, IsAuthorizedTrainer,
)

# Basic views
from .base import _log_error as _  # ensure base loaded

def health(_request):
    from django.http import JsonResponse
    return JsonResponse({"status": "ok", "service": "SAED IMS API"})

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
    LoginView, LogoutView, SignupView, TrainerSignupView,
    EmailVerifyView, PasswordResetRequestView, PasswordResetConfirmView,
)

# Profile
from .profile import UpdateProfileView

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
    ManageCoursesView, ManageCourseDetailView,
    AdminCoursesView, RestrictCourseView, UnrestrictCourseView,
    CourseDetailView,
)

# Trainers
from .trainers import (
    AvailableTrainersView, TrainerDetailView, SelectTrainersView,
    MyTrainersView, ConnectTrainerView, MyConnectionsView,
    MyCorpersView, ConnectionApproveView, ConnectionRejectView,
    CorperProfileForTrainerView,
)

# Payments
from .payments import (
    PaystackInitializeView, CoursePayInitializeView, CoursePayVerifyView,
    CourseEnrollmentStatusView, TrainerPendingEnrollmentsView,
    TrainerConfirmEnrollmentView, TrainerRejectEnrollmentView,
    AdminPendingRefundsView, AdminProcessRefundView, AdminRejectRefundView,
)

# Fast track
from .fast_track import (
    TraineeFastTrackCoursesView, ManageFastTrackVideosView,
    ManageFastTrackVideoDetailView, FastTrackVideosForCourseView,
    FetchVideoDurationView,
)

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
    DunisPendingPaymentsView, DunisConfirmPaymentView,
    DunisAllTrainersView, DunisToggleFastTrackView,
)

# Program management helpers
from .programs import _apply_program_data as apply_program_data

