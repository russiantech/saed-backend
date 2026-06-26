"""
Dashboard view.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Application, Connection, Course, Profile
from .base import (
    _log_error, role_for, application_payload, program_payload,
    managed_programs_for, IsAuthenticatedAPI,
)


class DashboardView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        try:
            user = request.user
            user_role = role_for(user)
            payload = {"stats": {}, "applications": []}

            if user_role == "corps_member":
                applications = Application.objects.filter(applicant=user).select_related("program")
                my_connections = Connection.objects.filter(corps_member=user).count()
                payload["stats"] = {
                    "applications": applications.count(),
                    "pending": applications.filter(status="pending").count(),
                    "approved": applications.filter(status="approved").count(),
                    "connections": my_connections,
                }
                payload["applications"] = [application_payload(item) for item in applications[:5]]

            elif user_role == "trainer":
                my_courses = Course.objects.filter(trainer=user, is_active=True)
                my_corpers = Connection.objects.filter(trainer=user).count()
                trainer_programs = managed_programs_for(user).filter(is_active=True)
                payload["stats"] = {
                    "courses": my_courses.count(),
                    "corpers": my_corpers,
                    "programs": trainer_programs.count(),
                }
                payload["trainerPrograms"] = [program_payload(p) for p in trainer_programs[:4]]

            elif user_role == "saed_admin":
                trainer_profiles = Profile.objects.filter(role="trainer").exclude(is_hidden=True)
                payload["stats"] = {
                    "totalTrainers": trainer_profiles.count(),
                    "approvedTrainers": trainer_profiles.filter(is_authorized=True).count(),
                    "pendingTrainers": trainer_profiles.filter(authorization_status="pending").count(),
                    "declinedTrainers": trainer_profiles.filter(authorization_status="declined").count(),
                    "removedTrainers": trainer_profiles.filter(authorization_status="removed").count(),
                    "totalCorpers": Profile.objects.filter(role="corps_member").exclude(is_hidden=True).count(),
                    "totalConnections": Connection.objects.count(),
                    "totalCourses": Course.objects.filter(is_active=True).count(),
                }
                payload["partnerStats"] = payload["stats"]

            elif user_role == "dunis_admin":
                trainer_profiles = Profile.objects.filter(role="trainer").exclude(is_hidden=True)
                pending_payments = trainer_profiles.filter(is_authorized=True, has_paid=False).count()
                fast_track_enabled = trainer_profiles.filter(can_upload_fast_track=True).count()
                payload["stats"] = {
                    "totalTrainers": trainer_profiles.count(),
                    "approvedTrainers": trainer_profiles.filter(is_authorized=True).count(),
                    "pendingTrainers": trainer_profiles.filter(authorization_status="pending").count(),
                    "declinedTrainers": trainer_profiles.filter(authorization_status="declined").count(),
                    "removedTrainers": trainer_profiles.filter(authorization_status="removed").count(),
                    "paidTrainers": trainer_profiles.filter(has_paid=True).count(),
                    "pendingPayments": pending_payments,
                    "fastTrackEnabled": fast_track_enabled,
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
