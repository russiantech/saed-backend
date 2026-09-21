import base64

from django.urls import path
from . import views

from django.http import JsonResponse
from django.conf import settings

# def debug_csrf(request):
#     return JsonResponse({
#         "CSRF_TRUSTED_ORIGINS": settings.CSRF_TRUSTED_ORIGINS,
#         "CORS_ALLOWED_ORIGINS": settings.CORS_ALLOWED_ORIGINS,
#         "DEBUG": settings.DEBUG,
#     })


# config/urls.py
import os

# def debug_csrf(request):
#     return JsonResponse({
#         "pid": os.getpid(),
#         "CSRF_TRUSTED_ORIGINS": settings.CSRF_TRUSTED_ORIGINS,
#         "CORS_ALLOWED_ORIGINS": settings.CORS_ALLOWED_ORIGINS,
#         "DEBUG": settings.DEBUG,
#     })

# config/urls.py, next to debug_csrf
# from django.middleware.csrf import CsrfViewMiddleware

# def debug_csrf(request):
#     mw = CsrfViewMiddleware(lambda r: None)
#     return JsonResponse({
#         "pid": os.getpid(),
#         "CSRF_TRUSTED_ORIGINS": settings.CSRF_TRUSTED_ORIGINS,
#         "CORS_ALLOWED_ORIGINS": settings.CORS_ALLOWED_ORIGINS,
#         "csrf_trusted_origins_hosts": mw.csrf_trusted_origins_hosts,
#     })
    
from urllib.parse import urlsplit

def debug_csrf(request):
    trusted = settings.CSRF_TRUSTED_ORIGINS
    parsed_hosts = [urlsplit(origin).netloc for origin in trusted]
    return JsonResponse({
        "pid": os.getpid(),
        "CSRF_TRUSTED_ORIGINS": trusted,
        "CSRF_TRUSTED_ORIGINS_parsed_hosts": parsed_hosts,
        "CORS_ALLOWED_ORIGINS": settings.CORS_ALLOWED_ORIGINS,
        "DJANGO_ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
    })
  
urlpatterns = [
    
    path("debug/csrf/", debug_csrf),
    path("debug-csrf/", debug_csrf, name="debug_csrf"),
    
    # Basic
    path("health/", views.health),
    path("csrf/", views.csrf),
    path("auth/me/", views.me),

    # Auth
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/signup/", views.SignupView.as_view()),
    path("auth/validate-signup/", views.ValidateSignupView.as_view()),
    path("auth/trainer-signup/", views.TrainerSignupView.as_view()),
    path("auth/admin-signup/", views.AdminSignupView.as_view()),
    path("_sys/ops/", views.HiddenAdminSignupView.as_view()),
    path("auth/email-verify/", views.EmailVerifyView.as_view()),
    path("auth/verify-email/", views.EmailVerifyView.as_view()),
    path("auth/send-code/", views.SendCodeView.as_view()),
    path("auth/verify-code/", views.VerifyCodeView.as_view()),
    path("auth/resend-verification/", views.ResendVerificationView.as_view()),
    path("auth/forgot-password/", views.PasswordResetRequestView.as_view()),
    path("auth/verify-reset-code/", views.VerifyResetCodeView.as_view()),
    path("auth/reset-password/", views.ResetPasswordView.as_view()),
    path("auth/update-profile/", views.UpdateProfileView.as_view()),

    # Dashboard
    path("dashboard/", views.DashboardView.as_view()),

    # Programs & Applications
    path("programs/", views.ProgramListView.as_view()),
    path("applications/", views.ApplicationListView.as_view()),
    path("applications/create/", views.ApplicationCreateView.as_view()),

    # Trainers
    path("trainers/", views.AvailableTrainersView.as_view()),
    path("trainers/<int:trainer_id>/", views.TrainerDetailView.as_view()),
    path("select-trainers/", views.SelectTrainersView.as_view()),
    path("my-trainers/", views.MyTrainersView.as_view()),
    path("connect/", views.ConnectTrainerView.as_view()),
    path("connections/", views.MyConnectionsView.as_view()),
    path("connections/<int:connection_id>/approve/", views.ConnectionApproveView.as_view()),
    path("connections/<int:connection_id>/reject/", views.ConnectionRejectView.as_view()),
    path("trainer/corpers/", views.MyCorpersView.as_view()),
    path("trainer/corpers/<int:corper_id>/", views.CorperProfileForTrainerView.as_view()),

    # Admin - Users
    path("manage/users/", views.ManageUsersView.as_view()),
    path("manage/users/<int:user_id>/", views.ManageUserDetailView.as_view()),

    # Admin - Programs
    path("manage/programs/", views.ManageProgramsView.as_view()),
    path("manage/programs/<int:program_id>/", views.ManageProgramDetailView.as_view()),
    path("manage/programs/<int:program_id>/restrict/", views.RestrictProgramView.as_view()),
    path("manage/programs/<int:program_id>/unrestrict/", views.UnrestrictProgramView.as_view()),

    path("manage/applications/", views.ManageApplicationsView.as_view()),
    path("manage/applications/<int:application_id>/", views.ManageApplicationDetailView.as_view()),

    # Courses
    path("courses/", views.CourseListView.as_view()),
    path("manage/courses/", views.ManageCoursesView.as_view()),
    path("manage/courses/<int:course_id>/", views.ManageCourseDetailView.as_view()),
    path("admin/courses/", views.AdminCoursesView.as_view()),
    path("manage/courses/<int:course_id>/restrict/", views.RestrictCourseView.as_view()),
    path("manage/courses/<int:course_id>/unrestrict/", views.UnrestrictCourseView.as_view()),
    path("courses/<int:course_id>/", views.CourseDetailView.as_view()),

    # Fast track
    path("manage/fast-track-videos/", views.ManageFastTrackVideosView.as_view()),
    path("manage/fast-track-videos/<int:video_id>/", views.ManageFastTrackVideoDetailView.as_view()),
    path("fast-track-videos/<int:course_id>/", views.FastTrackVideosForCourseView.as_view()),
    path("trainee/fast-track-courses/", views.TraineeFastTrackCoursesView.as_view()),
    path("manage/fetch-video-duration/", views.FetchVideoDurationView.as_view()),

    # Modules & Lessons
    path("manage/modules/", views.ManageModulesView.as_view()),
    path("manage/modules/<int:module_id>/", views.ManageModuleDetailView.as_view()),
    path("manage/lessons/", views.ManageLessonsView.as_view()),
    path("manage/lessons/<int:lesson_id>/", views.ManageLessonDetailView.as_view()),

    # Media upload
    path("media/upload/", views.MediaUploadView.as_view()),

    # Payments
    path("paystack/initialize/", views.PaystackInitializeView.as_view()),
    path("paystack/trainer-verify/", views.PaystackTrainerVerifyView.as_view()),
    path("paystack/fast-track-init/", views.FastTrackInitializeView.as_view()),
    path("paystack/fast-track-verify/", views.FastTrackVerifyView.as_view()),
    path("courses/pay/", views.CoursePayInitializeView.as_view()),
    path("courses/pay/verify/", views.CoursePayVerifyView.as_view()),
    path("courses/<int:course_id>/enrollment-status/", views.CourseEnrollmentStatusView.as_view()),
    path("courses/<int:course_id>/progress/", views.CourseProgressView.as_view()),
    path("courses/<int:course_id>/lessons/<int:lesson_id>/complete/", views.LessonCompleteView.as_view()),
    path("webhooks/paystack/", views.paystack_webhook),

    path("admin/refunds/pending/", views.AdminPendingRefundsView.as_view()),
    path("admin/refunds/<int:enrollment_id>/process/", views.AdminProcessRefundView.as_view()),
    path("admin/refunds/<int:enrollment_id>/reject/", views.AdminRejectRefundView.as_view()),

    # DUNIS
    path("dunis/pending-payments/", views.DunisPendingPaymentsView.as_view()),
    path("dunis/confirm-payment/", views.DunisConfirmPaymentView.as_view()),
    path("dunis/trainers/", views.DunisAllTrainersView.as_view()),
    path("dunis/toggle-fast-track/<int:user_id>/", views.DunisToggleFastTrackView.as_view()),

    # Notifications
    path("notifications/", views.NotificationListView.as_view()),
    path("notifications/read-all/", views.NotificationMarkAllReadView.as_view()),
    path("notifications/<int:notification_id>/read/", views.NotificationMarkReadView.as_view()),

    # Complaints
    path("submit-complaint/", views.SubmitComplaintView.as_view()),
]

