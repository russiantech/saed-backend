"""
DUNIS admin views.
"""
import json
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Course, Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async,
    read_json, user_payload, HasRole,
)


class DunisPendingPaymentsView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def get(self, request):
        try:
            profiles = Profile.objects.filter(
                role="trainer", is_authorized=True, has_paid=False
            ).select_related("user")
            result = []
            for p in profiles:
                result.append({
                    "id": p.user.id,
                    "fullName": p.user.get_full_name() or p.user.email,
                    "email": p.user.email,
                    "phone": p.phone,
                    "specialization": p.specialization,
                    "companyName": p.company_name,
                    "hasPaid": p.has_paid,
                    "paymentVerified": p.payment_verified,
                    "authorizedAt": p.authorized_at.isoformat() if p.authorized_at else None,
                })
            return Response({"trainers": result})
        except Exception as exc:
            _log_error("DUNIS pending payments error", exc=exc)
            return Response({"error": "Failed to load pending payments."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DunisConfirmPaymentView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def post(self, request):
        data = request.data
        user_id = data.get("userId")
        reference = data.get("reference", "")

        if not user_id:
            return Response({"error": "User ID is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            from django.contrib.auth.models import User
            user = User.objects.select_related("profile").get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        profile = user.profile
        if profile.role != "trainer":
            return Response({"error": "This user is not a trainer."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            profile.has_paid = True
            profile.payment_verified = True
            profile.payment_reference = reference
            profile.payment_verified_at = now()
            profile.save(update_fields=[
                "has_paid", "payment_verified", "payment_reference", "payment_verified_at"
            ])

            frontend_url = getattr(__import__("django.conf", fromlist=["settings"]).settings, "FRONTEND_URL", "http://localhost:3002")
            _send_email_async(
                subject="SAED IMS - Account Activated!",
                message=f"Hello {user.get_full_name()},\n\nYour payment has been verified and your account has been activated.",
                recipient_list=[user.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Account Activated!</h2>'
                    f'<p>Your payment has been verified and your account has been <strong>activated</strong>.</p>'
                    f'<p>Payment Reference: {reference}</p></div></div>'
                ),
            )
            return Response({"ok": True, "message": "Payment confirmed. Account activated."})
        except Exception as exc:
            _log_error(f"Payment confirmation error for {user_id}", exc=exc)
            return Response({"error": "Failed to confirm payment."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DunisAllTrainersView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def get(self, request):
        try:
            profiles = Profile.objects.filter(role="trainer").select_related("user").order_by(
                "user__first_name"
            )
            result = []
            for p in profiles:
                result.append({
                    "id": p.user.id,
                    "fullName": p.user.get_full_name() or p.user.email,
                    "email": p.user.email,
                    "specialization": p.specialization,
                    "isAuthorized": p.is_authorized,
                    "isActive": p.user.is_active,
                    "hasPaid": p.has_paid,
                    "paymentVerified": p.payment_verified,
                    "paymentReference": p.payment_reference,
                    "canUploadFastTrack": p.can_upload_fast_track,
                    "authorizationStatus": p.authorization_status,
                })
            return Response({"trainers": result})
        except Exception as exc:
            _log_error("DUNIS trainers list error", exc=exc)
            return Response({"error": "Failed to load trainers."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DunisToggleFastTrackView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def patch(self, request, user_id):
        try:
            from django.contrib.auth.models import User
            user = User.objects.select_related("profile").get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        profile = user.profile
        if profile.role != "trainer":
            return Response({"error": "This user is not a trainer."},
                            status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        try:
            profile.can_upload_fast_track = bool(
                data.get("canUploadFastTrack", not profile.can_upload_fast_track)
            )
            profile.save(update_fields=["can_upload_fast_track"])

            if not profile.can_upload_fast_track:
                Course.objects.filter(trainer=user, has_fast_track=True).update(
                    has_fast_track=False
                )

            return Response({"ok": True, "canUploadFastTrack": profile.can_upload_fast_track})
        except Exception as exc:
            _log_error("DUNIS toggle fast track error", exc=exc)
            return Response({"error": "Failed to toggle fast track."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
