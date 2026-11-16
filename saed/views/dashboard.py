"""
Dashboard view.
"""
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from ..models import Connection, Course, CourseEnrollment, Profile
from .base import (
    _log_error, role_for, application_payload, program_payload,
    managed_programs_for, IsAuthenticatedAPI, attach_course_counts, progress_for,
)


def _trainer_counts():
    """All trainer headline numbers in ONE query."""
    from django.db.models import Count, Q
    return Profile.objects.filter(role="trainer").exclude(is_hidden=True).aggregate(
        total=Count("id"), approved=Count("id", filter=Q(is_authorized=True)),
        pending=Count("id", filter=Q(authorization_status="pending")),
        declined=Count("id", filter=Q(authorization_status="declined")),
        removed=Count("id", filter=Q(authorization_status="removed")),
        paid=Count("id", filter=Q(has_paid=True)),
        pending_payments=Count("id", filter=Q(is_authorized=True, has_paid=False)))


class DashboardView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response({"stats": {}, "applications": []})
        try:
            user = request.user
            user_role = role_for(user)
            payload = {"stats": {}, "applications": []}

            if user_role == "corps_member":
                from django.db.models import Count, Q
                enrollments = CourseEnrollment.objects.filter(student=user)
                agg = enrollments.aggregate(total=Count("id"), pending=Count("id", filter=Q(status="pending")),
                                            approved=Count("id", filter=Q(status="confirmed")))
                payload["stats"] = {
                    "applications": agg["total"], "pending": agg["pending"], "approved": agg["approved"],
                    "connections": Connection.objects.filter(corps_member=user).count(),
                }
                recent = list(enrollments.select_related(
                    "student", "student__profile", "course", "course__trainer", "course__trainer__profile",
                    "course__orientation_camp").order_by("-enrolled_at")[:5])
                attach_course_counts([e.course for e in recent])
                prog = progress_for(user, [e.course_id for e in recent])
                payload["applications"] = [application_payload(e, prog[e.course_id]) for e in recent]

            elif user_role == "trainer":
                from ..models import Lesson, LessonAccess
                my_courses = Course.objects.filter(trainer=user, is_active=True)
                my_corpers = Connection.objects.filter(trainer=user).count()
                trainer_programs = managed_programs_for(user).filter(is_active=True)
                payload["stats"] = {
                    "courses": my_courses.count(),
                    "corpers": my_corpers,
                    "programs": trainer_programs.count(),
                    "lessons": Lesson.objects.filter(course__trainer=user).count(),
                    "enrolled": CourseEnrollment.objects.filter(course__trainer=user, status="confirmed").count(),
                    "pendingAccessRequests": LessonAccess.objects.filter(
                        lesson__course__trainer=user, status="requested").count(),
                }
                payload["trainerPrograms"] = [program_payload(p) for p in trainer_programs[:4]]

            elif user_role == "saed_admin":
                t = _trainer_counts()
                payload["stats"] = {
                    "totalTrainers": t["total"], "approvedTrainers": t["approved"],
                    "pendingTrainers": t["pending"], "declinedTrainers": t["declined"], "removedTrainers": t["removed"],
                    "totalCorpers": Profile.objects.filter(role="corps_member").exclude(is_hidden=True).count(),
                    "totalConnections": Connection.objects.count(),
                    "totalCourses": Course.objects.filter(is_active=True).count(),
                }
                payload["partnerStats"] = payload["stats"]

            elif user_role == "dunis_admin":
                t = _trainer_counts()
                from ..models import Payment, Lesson
                from django.db.models import Sum
                ok = Payment.objects.filter(status="success")
                video_total = ok.filter(payment_type="video_upload").aggregate(s=Sum("expected_amount_kobo"))["s"] or 0
                lesson_total = ok.filter(payment_type="lesson_access").aggregate(s=Sum("expected_amount_kobo"))["s"] or 0
                payload["stats"] = {
                    "totalTrainers": t["total"], "approvedTrainers": t["approved"],
                    "pendingTrainers": t["pending"], "declinedTrainers": t["declined"], "removedTrainers": t["removed"],
                    "paidTrainers": t["paid"],
                    "pendingPayments": t["pending_payments"],
                    "videoUploadsPaid": ok.filter(payment_type="video_upload").count(),
                    "videoUploadRevenue": video_total / 100,
                    "lessonPayments": ok.filter(payment_type="lesson_access").count(),
                    "lessonPaymentVolume": lesson_total / 100,
                    "paymentsNeedingReview": Payment.objects.filter(status="mismatch").count(),
                    "totalCorpers": Profile.objects.filter(role="corps_member").exclude(is_hidden=True).count(),
                    "totalConnections": Connection.objects.count(),
                    "totalCourses": Course.objects.filter(is_active=True).count(),
                }
                payload["partnerStats"] = payload["stats"]

            return Response(payload)
        except Exception as exc:
            _log_error("Dashboard error", exc=exc)
            return Response({"error": "Failed to load dashboard."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
