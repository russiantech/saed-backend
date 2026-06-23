"""
Dashboard view.
"""
from django.db.models import Count, Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Application, Connection, Course, CourseEnrollment, Program, Profile
from .base import _log_error, role_for, IsAuthenticatedAPI


class DashboardView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        try:
            user = request.user
            user_role = role_for(user)
            data = {"role": user_role}

            if user_role == "corps_member":
                data["applications"] = Application.objects.filter(applicant=user).count()
                data["programs"] = Program.objects.filter(is_active=True, is_restricted=False).count()
                data["connections"] = Connection.objects.filter(
                    corps_member=user, status="active"
                ).count()
                data["enrolledCourses"] = CourseEnrollment.objects.filter(
                    student=user, status="confirmed"
                ).count()

            elif user_role == "trainer":
                data["courses"] = Course.objects.filter(trainer=user).count()
                data["activeCourses"] = Course.objects.filter(trainer=user, is_active=True).count()
                data["connections"] = Connection.objects.filter(
                    trainer=user, status="active"
                ).count()
                data["pendingEnrollments"] = CourseEnrollment.objects.filter(
                    course__trainer=user, status="pending"
                ).count()

            elif user_role in ("saed_admin", "dunis_admin"):
                data["totalUsers"] = Profile.objects.count()
                data["totalTrainers"] = Profile.objects.filter(role="trainer").count()
                data["totalCorpsMembers"] = Profile.objects.filter(role="corps_member").count()
                data["totalPrograms"] = Program.objects.count()
                data["totalCourses"] = Course.objects.count()
                data["pendingApplications"] = Application.objects.filter(status="pending").count()
                data["pendingRefunds"] = CourseEnrollment.objects.filter(
                    refund_requested=True, refund_processed=False
                ).count()

            return Response(data)
        except Exception as exc:
            _log_error("Dashboard error", exc=exc)
            return Response({"error": "Failed to load dashboard."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
