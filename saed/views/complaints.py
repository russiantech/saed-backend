"""
Complaint views.
"""
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
            complaint = Complaint.objects.create(
                user=request.user, subject=subject, message=message,
            )
            _log_info(f"Complaint created: {complaint.id}")
            return Response({"ok": True, "message": "Complaint submitted."},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Complaint submission error", exc=exc)
            return Response({"error": "Failed to submit complaint."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
