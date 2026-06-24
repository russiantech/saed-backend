"""
Complaint views.
"""
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Complaint
from .base import _log_error, _log_info, IsAuthenticatedAPI


class SubmitComplaintView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        data = request.data
        subject = data.get("subject", "").strip()
        message = data.get("message", "").strip()

        if not subject:
            return Response({"error": "Subject is required.",
                             "fields": {"subject": "Subject is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({"error": "Message is required.",
                             "fields": {"message": "Message is required."}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            sender_name = request.user.get_full_name() or request.user.email
            admin_users = User.objects.filter(profile__role__in=["saed_admin", "dunis_admin"])
            for admin in admin_users:
                Complaint.objects.create(
                    user=admin,
                    subject=subject,
                    message=f"From: {sender_name} ({request.user.email})\n\n{message}",
                )
            _log_info(f"Complaint distributed to {admin_users.count()} admins")
            return Response({"ok": True, "message": "Complaint submitted successfully."},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Complaint submission error", exc=exc)
            return Response({"error": "Failed to submit complaint."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
