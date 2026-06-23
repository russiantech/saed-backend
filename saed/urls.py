from django.urls import path

from . import views


urlpatterns = [
    # Basic
    path("health/", views.health),
    path("csrf/", views.csrf),
    path("auth/me/", views.me),

    # Auth (DRF APIViews)
    path("auth/login/", views.LoginView.as_view()),
    path("auth/logout/", views.LogoutView.as_view()),
    path("auth/signup/", views.SignupView.as_view()),
    path("auth/trainer-signup/", views.TrainerSignupView.as_view()),
    path("auth/email-verify/", views.EmailVerifyView.as_view()),
    path("auth/password-reset/", views.PasswordResetRequestView.as_view()),
    path("auth/password-reset/confirm/", views.PasswordResetConfirmView.as_view()),

    # Profile
    path("auth/update-profile/", views.UpdateProfileView.as_view()),

    # Dashboard
    path("dashboard/", views.DashboardView.as_view()),

    # Programs
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

    # User management (admin)
    path("manage/users/", views.ManageUsersView.as_view()),
    path("manage/users/<int:user_id>/", views.ManageUserDetailView.as_view()),

    # Program management (admin)
    path("manage/programs/", views.ManageProgramsView.as_view()),
    path("manage/programs/<int:program_id>/", views.ManageProgramDetailView.as_view()),
    path("manage/programs/<int:program_id>/restrict/", views.RestrictProgramView.as_view()),
    path("manage/programs/<int:program_id>/unrestrict/", views.UnrestrictProgramView.as_view()),
    path("manage/applications/", views.ManageApplicationsView.as_view()),
    path("manage/applications/<int:application_id>/", views.ManageApplicationDetailView.as_view()),

    # Courses
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

    # Payments
    path("paystack/initialize/", views.PaystackInitializeView.as_view()),
    path("courses/pay/", views.CoursePayInitializeView.as_view()),
    path("courses/pay/verify/", views.CoursePayVerifyView.as_view()),
    path("courses/<int:course_id>/enrollment-status/", views.CourseEnrollmentStatusView.as_view()),
    path("trainer/enrollments/pending/", views.TrainerPendingEnrollmentsView.as_view()),
    path("trainer/enrollments/<int:enrollment_id>/confirm/", views.TrainerConfirmEnrollmentView.as_view()),
    path("trainer/enrollments/<int:enrollment_id>/reject/", views.TrainerRejectEnrollmentView.as_view()),
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
