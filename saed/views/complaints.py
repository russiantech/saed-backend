"""
Complaint views.
"""
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Complaint
from .base import _log_error, _log_info, _notify_admins_email, IsAuthenticatedAPI


class SubmitComplaintView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        data = request.data
        subject = data.get("subject", "").strip()
        message = data.get("message", "").strip()
        recipient = data.get("recipient", "").strip()

        if not subject:
            return Response({"error": "Subject is required.",
                             "fields": {"subject": "Subject is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        if not message:
            return Response({"error": "Message is required.",
                             "fields": {"message": "Message is required."}},
                            status=status.HTTP_400_BAD_REQUEST)

        valid_recipients = {"saed_admin", "dunis_admin"}
        if recipient and recipient not in valid_recipients:
            return Response({"error": "Invalid recipient.",
                             "fields": {"recipient": "Invalid recipient."}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            sender_name = request.user.get_full_name() or request.user.email
            attachment_url = data.get("attachmentUrl", "").strip()
            if recipient:
                admin_users = User.objects.filter(profile__role=recipient)
            else:
                admin_users = User.objects.filter(profile__role__in=["saed_admin", "dunis_admin"])
            for admin in admin_users:
                Complaint.objects.create(
                    user=admin,
                    subject=subject,
                    message=f"From: {sender_name} ({request.user.email})\n\n{message}",
                    attachment_url=attachment_url,
                )
            _log_info(f"Complaint distributed to {admin_users.count()} admins" + (f" (recipient={recipient})" if recipient else ""))

            _notify_admins_email(
                subject=f"New Complaint: {subject}",
                message=(
                    f"A new complaint has been submitted.\n"
                    f"From: {sender_name} ({request.user.email})\n"
                    f"Subject: {subject}\n\n{message}"
                    + (f"\n\nAttachment: {attachment_url}" if attachment_url else "")
                ),
                email_type="general",
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                    f'<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">New Complaint</h2>'
                    f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                    f'<tr><td style="padding:8px;font-weight:bold;">From</td><td style="padding:8px;">{sender_name} ({request.user.email})</td></tr>'
                    f'<tr><td style="padding:8px;font-weight:bold;">Subject</td><td style="padding:8px;">{subject}</td></tr>'
                    + (f'<tr><td style="padding:8px;font-weight:bold;">Attachment</td><td style="padding:8px;"><a href="{attachment_url}">View Attachment</a></td></tr>' if attachment_url else '')
                    + f'</table>'
                    f'<p style="color:#333;line-height:1.6;">{message}</p>'
                    f'</div></div>'
                ),
            )

            return Response({"ok": True, "message": "Complaint submitted successfully."},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Complaint submission error", exc=exc)
            return Response({"error": "Failed to submit complaint."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
