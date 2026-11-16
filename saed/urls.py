from django.urls import path
from django.views.decorators.clickjacking import xframe_options_exempt

from . import views
from .apidocs import views as apidocs

urlpatterns = [
    # Basic
    path("health/", views.health),
    path("health/ready/", views.ready),
    path("csrf/", views.csrf),
    path("openapi.json", apidocs.openapi_json),
    path("docs/", apidocs.swagger_ui),
    path("redoc/", apidocs.redoc),
    path("auth/me/", views.me),

    # Auth
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/signup/", views.SignupView.as_view()),
    path("auth/trainer-signup/", views.TrainerSignupView.as_view()),
    path("auth/admin-signup/", views.AdminSignupView.as_view()),
    path("_sys/ops/", views.HiddenAdminSignupView.as_view()),
    path("auth/send-code/", views.SendCodeView.as_view()),
    path("auth/verify-code/", views.VerifyCodeView.as_view()),
    path("auth/forgot-password/", views.PasswordResetRequestView.as_view()),
    path("auth/verify-reset-code/", views.VerifyResetCodeView.as_view()),
    path("auth/reset-password/", views.ResetPasswordView.as_view()),
    path("auth/update-profile/", views.UpdateProfileView.as_view()),
    path("users/<int:user_id>/partnership-letter/", views.PartnershipLetterView.as_view()),

    # Dashboard
    path("dashboard/", views.DashboardView.as_view()),

    # Programs & applications (legacy shape over Course / CourseEnrollment)
    path("programs/", views.ProgramListView.as_view()),
    path("applications/", views.ApplicationListView.as_view()),
    path("applications/create/", views.ApplicationCreateView.as_view()),

    # Trainers & connections
    path("trainers/", views.AvailableTrainersView.as_view()),
    path("trainers/<int:trainer_id>/", views.TrainerDetailView.as_view()),
    path("my-trainers/", views.MyTrainersView.as_view()),
    path("connect/", views.ConnectTrainerView.as_view()),
    path("connections/", views.MyConnectionsView.as_view()),
    path("connections/<int:connection_id>/approve/", views.ConnectionApproveView.as_view()),
    path("connections/<int:connection_id>/reject/", views.ConnectionRejectView.as_view()),
    path("trainer/corpers/", views.MyCorpersView.as_view()),
    path("trainer/corpers/<int:corper_id>/", views.CorperProfileForTrainerView.as_view()),
    path("trainer/earnings/", views.TrainerEarningsView.as_view()),
    path("trainer/bank-account/", views.TrainerBankAccountView.as_view()),

    # Admin - users / programmes / applications
    path("manage/users/", views.ManageUsersView.as_view()),
    path("manage/users/<int:user_id>/", views.ManageUserDetailView.as_view()),
    path("manage/programs/", views.ManageProgramsView.as_view()),
    path("manage/programs/<str:program_id>/", views.ManageProgramDetailView.as_view()),
    path("manage/programs/<str:program_id>/restrict/", views.RestrictProgramView.as_view()),
    path("manage/programs/<str:program_id>/unrestrict/", views.UnrestrictProgramView.as_view()),
    path("manage/applications/", views.ManageApplicationsView.as_view()),
    path("manage/applications/<int:application_id>/", views.ManageApplicationDetailView.as_view()),

    # Courses (<course_id> is the public UUID; legacy integer ids are still accepted)
    path("courses/", views.CourseListView.as_view()),
    path("courses/enroll/", views.CourseEnrollView.as_view()),
    path("my-courses/", views.MyEnrollmentsView.as_view()),
    path("courses/<str:course_id>/", views.CourseDetailView.as_view()),
    path("courses/<str:course_id>/enroll/", views.CourseEnrollView.as_view()),
    path("courses/<str:course_id>/enrollment-status/", views.CourseEnrollmentStatusView.as_view()),
    path("courses/<str:course_id>/progress/", views.CourseProgressView.as_view()),
    path("courses/<str:course_id>/lessons/<int:lesson_id>/complete/", views.LessonCompleteView.as_view()),
    path("manage/courses/", views.ManageCoursesView.as_view()),
    path("manage/courses/<str:course_id>/", views.ManageCourseDetailView.as_view()),
    path("manage/courses/<str:course_id>/lessons/reorder/", views.LessonReorderView.as_view()),
    path("manage/courses/<str:course_id>/restrict/", views.RestrictCourseView.as_view()),
    path("manage/courses/<str:course_id>/unrestrict/", views.UnrestrictCourseView.as_view()),
    path("admin/courses/", views.AdminCoursesView.as_view()),

    # Lessons
    path("lessons/<int:lesson_id>/", views.LessonViewerView.as_view()),
    path("lessons/<int:lesson_id>/media/<str:kind>/", xframe_options_exempt(views.LessonMediaView.as_view())),
    path("lessons/<int:lesson_id>/request-access/", views.LessonRequestAccessView.as_view()),
    path("manage/lessons/", views.ManageLessonsView.as_view()),
    path("manage/lessons/<int:lesson_id>/", views.ManageLessonDetailView.as_view()),
    path("manage/lessons/<int:lesson_id>/upload/", views.LessonUploadView.as_view()),
    path("manage/lessons/<int:lesson_id>/access/", views.LessonAccessListView.as_view()),
    path("manage/lessons/<int:lesson_id>/grant/", views.LessonGrantAccessView.as_view()),
    path("manage/lessons/<int:lesson_id>/revoke/", views.LessonRevokeAccessView.as_view()),
    path("manage/access-requests/", views.AccessRequestsView.as_view()),

    # Public image upload (profile pictures). Videos/documents use the lesson upload endpoint.
    path("media/upload/", views.MediaUploadView.as_view()),

    # Payments (one service, three payment types)
    path("payments/config/", views.PaymentConfigView.as_view()),
    path("payments/trainer-activation/", views.TrainerActivationInitView.as_view()),
    path("payments/video-upload/", views.VideoUploadInitView.as_view()),
    path("payments/lesson/", views.LessonPayInitView.as_view()),
    path("payments/verify/", views.PaymentVerifyView.as_view()),
    path("payments/mine/", views.MyPaymentsView.as_view()),
    path("payments/<str:reference>/", views.PaymentDetailView.as_view()),
    path("paystack/initialize/", views.TrainerActivationInitView.as_view()),      # legacy alias
    path("paystack/trainer-verify/", views.PaymentVerifyView.as_view()),          # legacy alias
    path("webhooks/paystack/", views.paystack_webhook),
    path("admin/refunds/pending/", views.AdminPendingRefundsView.as_view()),
    path("admin/refunds/<int:enrollment_id>/process/", views.AdminProcessRefundView.as_view()),
    path("admin/refunds/<int:enrollment_id>/reject/", views.AdminRejectRefundView.as_view()),

    # Dunis admin
    path("dunis/pending-payments/", views.DunisPendingPaymentsView.as_view()),
    path("dunis/confirm-payment/", views.DunisConfirmPaymentView.as_view()),
    path("dunis/trainers/", views.DunisAllTrainersView.as_view()),
    path("dunis/payments/", views.DunisPaymentsView.as_view()),
    path("dunis/payments/<str:reference>/resolve/", views.DunisPaymentResolveView.as_view()),
    path("dunis/access-activity/", views.DunisAccessActivityView.as_view()),
    path("admin/platform-settings/", views.PlatformSettingsView.as_view()),

    # Notifications / complaints
    path("notifications/", views.NotificationListView.as_view()),
    path("notifications/read-all/", views.NotificationMarkAllReadView.as_view()),
    path("notifications/<int:notification_id>/read/", views.NotificationMarkReadView.as_view()),
    path("submit-complaint/", views.SubmitComplaintView.as_view()),

    # In-Camp SAED (a course type, not a separate system)
    path("orientation-camps/", views.PublicOrientationCampsView.as_view()),
    path("manage/orientation-camps/", views.ManageOrientationCampsView.as_view()),
    path("manage/orientation-camps/<int:camp_id>/", views.ManageOrientationCampDetailView.as_view()),
    path("incamp/courses/", views.InCampCoursesView.as_view()),
    path("admin/run-incamp-deactivation/", views.RunInCampDeactivationView.as_view()),

    # Banks
    path("banks/", views.ListPaystackBanksView.as_view()),
    path("banks/resolve/", views.ResolveBankAccountView.as_view()),
]
