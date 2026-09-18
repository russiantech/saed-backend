"""
Payment views: Paystack init/verify, enrollments, refunds, webhooks.
"""

import hashlib
import hmac
import http.client
import json
import ssl
import warnings

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from django.conf import settings as django_settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.utils.crypto import get_random_string
from django.utils.timezone import now


_paystack_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
_paystack_ssl_ctx.check_hostname = False
_paystack_ssl_ctx.verify_mode = ssl.CERT_NONE
_paystack_ssl_ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
try:
    _paystack_ssl_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
except AttributeError:
    pass


def _paystack_request(method, path, data=None, headers=None, timeout=30):
    """Make an HTTPS request to Paystack using http.client (avoids requests/SSL issues on Python 3.14)."""
    url = path
    body = json.dumps(data) if data else None
    last_exc = None
    for attempt in range(3):
        conn = http.client.HTTPSConnection("api.paystack.co", timeout=timeout, context=_paystack_ssl_ctx)
        try:
            conn.request(method, url, body=body, headers=headers or {})
            resp = conn.getresponse()
            raw = resp.read().decode("utf-8")
            conn.close()
            return json.loads(raw)
        except Exception as exc:
            last_exc = exc
            try:
                conn.close()
            except Exception:
                pass
            if attempt < 2:
                import time
                time.sleep(0.5 * (attempt + 1))
                continue
            raise last_exc

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Course, CourseEnrollment, Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async, _notify_admins,
    _notify_admins_email,
    read_json, validation_error, HasRole, IsAuthenticatedAPI,
)


class PaystackInitializeView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != "trainer":
            return Response({"error": "Only trainer accounts can make this payment."},
                            status=status.HTTP_403_FORBIDDEN)
        if profile.has_paid and profile.is_authorized:
            return Response({"error": "This trainer payment has already been recorded."},
                            status=status.HTTP_400_BAD_REQUEST)
        email = request.user.email
        default_amount = getattr(django_settings, "PAYSTACK_DEFAULT_AMOUNT", 50000)
        amount = default_amount

        if not email:
            return Response({"error": "Email is required.",
                             "fields": {"email": "Email is required."}},
                            status=status.HTTP_400_BAD_REQUEST)

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response({"error": "Payment is not configured."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        reference = f"SAED-{get_random_string(12).upper()}"
        try:
            profile.payment_reference = reference
            profile.save(update_fields=["payment_reference"])
        except Exception as exc:
            _log_error("Paystack profile update error", exc=exc)

        # The configured trainer fee is expressed in Paystack's subunit
        # (kobo), matching PAYSTACK_DEFAULT_AMOUNT and the frontend display.
        amount_kobo = int(amount)
        frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3002").rstrip("/")

        last_exc = None
        for attempt in range(3):
            try:
                body = _paystack_request("POST", "/transaction/initialize", data={
                    "email": email, "amount": amount_kobo,
                    "reference": reference,
                    "metadata": {"reference": reference, "type": "trainer_activation"},
                    "currency": "NGN",
                    "callback_url": f"{frontend_url}/app/payment/callback?reference={reference}&type=trainer",
                }, headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"})
                if body.get("status"):
                    return Response({
                        "ok": True, "reference": reference,
                        "authorization_url": body["data"]["authorization_url"],
                        "access_code": body["data"]["access_code"],
                        "message": "Payment initialized.",
                    })
                return Response({"error": body.get("message", "Payment initialization failed.")},
                                status=status.HTTP_400_BAD_REQUEST)
            except Exception as exc:
                last_exc = exc
                _log_error(f"Paystack connect attempt {attempt+1}/3 failed", exc=exc)
                continue

        _log_error("Paystack all attempts failed", exc=last_exc)
        return Response({"error": "Unable to connect to payment gateway after retries."},
                        status=status.HTTP_502_BAD_GATEWAY)


class PaystackTrainerVerifyView(APIView):
    """Verify a trainer activation payment after Paystack redirect."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        reference = request.data.get("reference")
        if not reference:
            return Response({"error": "Reference is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != "trainer":
            return Response({"error": "Not a trainer account."},
                            status=status.HTTP_403_FORBIDDEN)
        if profile.has_paid:
            return Response({"ok": True, "message": "Already activated."})

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response({"error": "Payment is not configured."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)
        api_url = getattr(django_settings, "PAYSTACK_API_URL", "https://api.paystack.co")

        try:
            body = _paystack_request("GET", f"/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {secret_key}"})
            payment = body.get("data", {})
            expected_kobo = int(getattr(django_settings, "PAYSTACK_DEFAULT_AMOUNT", 50000))
            valid_payment = (
                body.get("status") and payment.get("status") == "success"
                and payment.get("reference") == reference
                and payment.get("amount") == expected_kobo
                and payment.get("currency") == "NGN"
            )
            if not valid_payment:
                return Response({"error": "Payment verification failed."},
                                status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Trainer verify gateway error", exc=exc)
            return Response({"error": "Unable to verify payment with gateway."},
                            status=status.HTTP_502_BAD_GATEWAY)

        profile.has_paid = True
        profile.is_authorized = True
        profile.authorization_status = "approved"
        profile.authorized_at = now()
        profile.payment_verified = True
        profile.payment_verified_at = now()
        profile.save(update_fields=["has_paid", "is_authorized", "authorization_status", "authorized_at", "payment_verified", "payment_verified_at"])
        _send_email_async(
            subject="SAED IMS - Trainer Activation Confirmed",
            message=f"Hello {profile.user.get_full_name()},\n\nYour trainer account has been activated.",
            recipient_list=[profile.user.email],
            html_message=(
                '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                '<h2 style="color:#1a5f2a;margin-top:0;">Trainer Account Activated</h2>'
                '<p>Your trainer account has been activated. You can now create courses and connect with corps members.</p></div></div>'
            ),
        )
        return Response({"ok": True, "message": "Trainer account activated."})


FAST_TRACK_AMOUNT = 2500000  # ₦25,000 in kobo


class FastTrackInitializeView(APIView):
    """Initialize payment for a trainer to enable fast track on their courses."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != "trainer":
            return Response({"error": "Only trainers can enable fast track."},
                            status=status.HTTP_403_FORBIDDEN)
        if profile.can_upload_fast_track:
            return Response({"error": "Fast track is already enabled."},
                            status=status.HTTP_400_BAD_REQUEST)

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response({"error": "Payment is not configured."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        reference = f"SAED-FT-{get_random_string(12).upper()}"
        email = request.user.email
        frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3002").rstrip("/")

        last_exc = None
        for attempt in range(3):
            try:
                body = _paystack_request("POST", "/transaction/initialize", data={
                    "email": email,
                    "amount": FAST_TRACK_AMOUNT,
                    "reference": reference,
                    "currency": "NGN",
                    "metadata": {"reference": reference, "type": "fast_track"},
                    "callback_url": f"{frontend_url}/app/payment/callback?reference={reference}&type=fast_track",
                }, headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"})
                if body.get("status"):
                    return Response({
                        "ok": True,
                        "reference": reference,
                        "authorization_url": body["data"]["authorization_url"],
                        "access_code": body["data"]["access_code"],
                    })
                return Response({"error": body.get("message", "Payment initialization failed.")},
                                status=status.HTTP_400_BAD_REQUEST)
            except Exception as exc:
                last_exc = exc
                _log_error(f"Fast track init attempt {attempt + 1}/3 failed", exc=exc)
        _log_error("Fast track init failed after 3 attempts", exc=last_exc)
        return Response({"error": "Payment gateway unreachable."},
                        status=status.HTTP_502_BAD_GATEWAY)


class FastTrackVerifyView(APIView):
    """Verify fast track payment and enable it for the trainer."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        reference = request.data.get("reference")
        if not reference:
            return Response({"error": "Reference is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(request.user, "profile", None)
        if not profile or profile.role != "trainer":
            return Response({"error": "Not a trainer account."},
                            status=status.HTTP_403_FORBIDDEN)
        if profile.can_upload_fast_track:
            return Response({"ok": True, "message": "Fast track already enabled."})

        secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            return Response({"error": "Payment is not configured."},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            body = _paystack_request("GET", f"/transaction/verify/{reference}",
                headers={"Authorization": f"Bearer {secret_key}"})
            payment = body.get("data", {})
            valid_payment = (
                body.get("status") and payment.get("status") == "success"
                and payment.get("reference") == reference
                and payment.get("amount") == FAST_TRACK_AMOUNT
                and payment.get("currency") == "NGN"
            )
            if not valid_payment:
                return Response({"error": "Payment verification failed."},
                                status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Fast track verify gateway error", exc=exc)
            return Response({"error": "Unable to verify payment with gateway."},
                            status=status.HTTP_502_BAD_GATEWAY)

        profile.can_upload_fast_track = True
        profile.save(update_fields=["can_upload_fast_track"])
        _send_email_async(
            subject="SAED IMS - Fast Track Enabled",
            message=f"Hello {profile.user.get_full_name()},\n\nFast track has been enabled for your courses.",
            recipient_list=[profile.user.email],
            html_message=(
                '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                '<h2 style="color:#1a5f2a;margin-top:0;">Fast Track Enabled</h2>'
                '<p>Fast track has been enabled. You can now upload fast track videos for your courses.</p></div></div>'
            ),
        )
        return Response({"ok": True, "message": "Fast track enabled."})


class CoursePayInitializeView(APIView):
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        course_id = data.get("courseId")
        if not course_id:
            return Response({"error": "Course ID is required.",
                             "fields": {"courseId": "Course ID is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            course = Course.objects.get(id=course_id, is_active=True, is_restricted=False)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        if course.price <= 0:
            return Response({"error": "This course is free."}, status=status.HTTP_400_BAD_REQUEST)

        if not Connection.objects.filter(
            corps_member=request.user, trainer=course.trainer, status="active"
        ).exists():
            return Response({"error": "Connect with this course's trainer before enrolling."},
                            status=status.HTTP_403_FORBIDDEN)

        try:
            confirmed_count = CourseEnrollment.objects.filter(
                course=course, status="confirmed"
            ).count()
            if confirmed_count >= course.max_students:
                return Response({"error": "This course is full.", "slotsFull": True},
                                status=status.HTTP_400_BAD_REQUEST)

            enrollment, _ = CourseEnrollment.objects.get_or_create(
                student=request.user, course=course,
                defaults={"amount_paid": course.price},
            )
            if enrollment.status == "confirmed":
                return Response({"error": "You already have access to this course."},
                                status=status.HTTP_400_BAD_REQUEST)
            if enrollment.status == "refunded":
                enrollment.status = "confirmed"
                enrollment.refund_requested = False
                enrollment.refund_requested_at = None
                enrollment.refund_processed = False
                enrollment.refund_processed_at = None
                enrollment.refund_note = ""

            reference = f"SAED-COURSE-{get_random_string(12).upper()}"
            enrollment.payment_reference = reference
            enrollment.payment_verified = False
            enrollment.amount_paid = course.price
            enrollment.save(update_fields=[
                "payment_reference", "payment_verified", "amount_paid", "status",
                "refund_requested", "refund_requested_at",
                "refund_processed", "refund_processed_at", "refund_note",
            ])

            secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
            if not secret_key:
                return Response({"error": "Payment is not configured."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            amount_kobo = int(float(course.price) * 100)
            callback_url = f"{getattr(django_settings, 'FRONTEND_URL', 'http://localhost:3002').rstrip('/')}/app/payment/verify?reference={reference}"

            body = _paystack_request("POST", "/transaction/initialize", data={
                "email": request.user.email, "amount": amount_kobo,
                "reference": reference,
                "currency": "NGN",
                "metadata": {"reference": reference, "course_id": course.id},
                "callback_url": callback_url,
            }, headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"})
            if body.get("status"):
                return Response({
                    "ok": True, "reference": reference,
                    "authorization_url": body["data"]["authorization_url"],
                    "access_code": body["data"]["access_code"],
                    "amount": str(course.price), "courseTitle": course.title,
                })
            return Response({"error": body.get("message", "Payment initialization failed.")},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Course payment init error", exc=exc)
            return Response({"error": "Payment initialization failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CoursePayVerifyView(APIView):
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        reference = data.get("reference", "")
        if not reference:
            return Response({"error": "Reference is required.",
                             "fields": {"reference": "Reference is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            enrollment = CourseEnrollment.objects.filter(
                student=request.user, payment_reference=reference
            ).first()
            if not enrollment:
                return Response({"error": "Payment record not found."},
                                status=status.HTTP_404_NOT_FOUND)
            if enrollment.status == "pending" and enrollment.payment_verified:
                return Response({"ok": True, "message": "Payment is being processed."})
            if enrollment.status == "confirmed":
                return Response({"ok": True, "message": "Already verified."})

            secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
            if not secret_key:
                return Response({"error": "Payment is not configured."},
                                status=status.HTTP_503_SERVICE_UNAVAILABLE)
            try:
                body = _paystack_request("GET", f"/transaction/verify/{reference}",
                    headers={"Authorization": f"Bearer {secret_key}"})
                payment = body.get("data", {})
                expected_kobo = int(float(enrollment.course.price) * 100)
                valid_payment = (
                    body.get("status") and payment.get("status") == "success"
                    and payment.get("reference") == reference
                    and payment.get("amount") == expected_kobo
                    and payment.get("currency") == "NGN"
                    and payment.get("customer", {}).get("email", "").lower() == request.user.email.lower()
                )
                if not valid_payment:
                    return Response({"error": "Payment details do not match this enrollment."},
                                    status=status.HTTP_400_BAD_REQUEST)
            except Exception as exc:
                _log_error("Payment verification gateway error", exc=exc)
                return Response({"error": "Unable to verify payment with gateway."},
                                status=status.HTTP_502_BAD_GATEWAY)

            enrollment.status = "confirmed"
            enrollment.payment_verified = True
            enrollment.amount_paid = enrollment.course.price
            enrollment.save(update_fields=["status", "payment_verified", "amount_paid"])
            return Response({"ok": True, "message": "Payment confirmed. You are enrolled."})
        except Exception as exc:
            _log_error("Payment verification error", exc=exc)
            return Response({"error": "Payment verification failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CourseEnrollmentStatusView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            enrollment = CourseEnrollment.objects.filter(
                student=request.user, course_id=course_id
            ).first()
            return Response({
                "isPaid": enrollment.status == "confirmed" if enrollment else False,
                "enrolled": enrollment is not None,
                "status": enrollment.status if enrollment else None,
            })
        except Exception as exc:
            _log_error("Enrollment status error", exc=exc)
            return Response({"error": "Failed to check enrollment."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminPendingRefundsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        try:
            enrollments = CourseEnrollment.objects.filter(
                refund_requested=True, refund_processed=False
            ).select_related("student", "course", "course__trainer")
            result = []
            for e in enrollments:
                result.append({
                    "id": e.id,
                    "studentName": e.student.get_full_name() or e.student.email,
                    "studentEmail": e.student.email,
                    "courseTitle": e.course.title,
                    "trainerName": e.course.trainer.get_full_name() or e.course.trainer.email,
                    "amount": str(e.amount_paid),
                    "paymentReference": e.payment_reference,
                    "status": e.status,
                    "refundRequestedAt": e.refund_requested_at.isoformat() if e.refund_requested_at else None,
                })
            return Response({"refunds": result})
        except Exception as exc:
            _log_error("Pending refunds error", exc=exc)
            return Response({"error": "Failed to load refunds."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminProcessRefundView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, enrollment_id):
        data = request.data
        note = data.get("note", "")
        try:
            enrollment = CourseEnrollment.objects.select_related(
                "student", "course"
            ).get(id=enrollment_id, refund_requested=True, refund_processed=False)
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Refund not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            refund_success = False
            refund_message = ""

            if enrollment.payment_reference:
                amount_kobo = int(float(enrollment.amount_paid) * 100)
                refund_success, refund_message = _paystack_refund(
                    enrollment.payment_reference,
                    amount_kobo=amount_kobo,
                    note=note or f"Refund for {enrollment.course.title}",
                )
                if not refund_success:
                    _log_warning(f"Paystack refund failed for {enrollment.payment_reference}: {refund_message}")

            enrollment.refund_processed = True
            enrollment.refund_processed_at = now()
            enrollment.refund_note = note or (f"Paystack refund: {refund_message}" if refund_message else "")
            enrollment.status = "refunded"
            enrollment.save(update_fields=[
                "refund_processed", "refund_processed_at", "refund_note", "status"
            ])
            _send_email_async(
                subject="SAED IMS - Refund Processed",
                message=f"Hello {enrollment.student.get_full_name()},\n\nYour refund of \u20a6{enrollment.amount_paid} has been processed.",
                recipient_list=[enrollment.student.email],
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Refund Processed</h2>'
                    f'<p>Your refund of <strong>\u20a6{enrollment.amount_paid}</strong> for <strong>{enrollment.course.title}</strong> has been processed.</p></div></div>'
                ),
            )
            message = "Refund processed."
            if not refund_success and refund_message:
                message += f" Note: {refund_message}"
            return Response({"ok": True, "message": message})
        except Exception as exc:
            _log_error(f"Refund processing error for {enrollment_id}", exc=exc)
            return Response({"error": "Failed to process refund."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminRejectRefundView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, enrollment_id):
        data = request.data
        note = data.get("note", "")
        try:
            enrollment = CourseEnrollment.objects.select_related(
                "student", "course"
            ).get(id=enrollment_id, refund_requested=True, refund_processed=False)
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Refund not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            enrollment.refund_processed = True
            enrollment.refund_processed_at = now()
            enrollment.refund_note = note or "Refund denied by admin"
            enrollment.save(update_fields=[
                "refund_processed", "refund_processed_at", "refund_note"
            ])
            _send_email_async(
                subject="SAED IMS - Refund Denied",
                message=f"Hello {enrollment.student.get_full_name()},\n\nYour refund request has been denied.",
                recipient_list=[enrollment.student.email],
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#c0392b;margin-top:0;">Refund Denied</h2>'
                    f'<p>Your refund request for <strong>\u20a6{enrollment.amount_paid}</strong> ({enrollment.course.title}) has been denied.</p></div></div>'
                ),
            )
            return Response({"ok": True, "message": "Refund denied."})
        except Exception as exc:
            _log_error(f"Refund rejection error for {enrollment_id}", exc=exc)
            return Response({"error": "Failed to reject refund."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ═══════════════════════════════════════════════════════════════════════════════
# PAYSTACK WEBHOOK
# ═══════════════════════════════════════════════════════════════════════════════

def _verify_paystack_signature(request_body, signature, secret_key):
    """Verify Paystack webhook signature using HMAC SHA512."""
    if not signature or not secret_key:
        return False
    try:
        computed = hmac.new(
            secret_key.encode("utf-8"),
            request_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(computed, signature)
    except Exception:
        return False


def _handle_trainer_activation(reference):
    """Handle successful trainer activation payment."""
    try:
        profile = Profile.objects.filter(
            payment_reference=reference, role="trainer"
        ).select_related("user").first()
        if not profile:
            _log_warning(f"Webhook: no trainer profile found for reference {reference}")
            return False
        if profile.has_paid:
            return True
        profile.has_paid = True
        profile.is_authorized = True
        profile.authorization_status = "approved"
        profile.authorized_at = now()
        profile.payment_verified = True
        profile.payment_verified_at = now()
        profile.save(update_fields=["has_paid", "is_authorized", "authorization_status", "authorized_at", "payment_verified", "payment_verified_at"])
        _send_email_async(
            subject="SAED IMS - Trainer Activation Confirmed",
            message=f"Hello {profile.user.get_full_name()},\n\nYour trainer account has been activated.",
            recipient_list=[profile.user.email],
            html_message=(
                '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                '<h2 style="color:#1a5f2a;margin-top:0;">Trainer Account Activated</h2>'
                '<p>Your trainer account has been activated. You can now create courses and connect with corps members.</p></div></div>'
            ),
        )
        _log_info(f"Webhook: trainer activation completed for {profile.user.email}")
        return True
    except Exception as exc:
        _log_error(f"Webhook: trainer activation error for {reference}", exc=exc)
        return False


def _handle_course_payment(reference):
    """Handle successful course payment."""
    try:
        enrollment = CourseEnrollment.objects.filter(
            payment_reference=reference
        ).select_related("student", "course", "course__trainer").first()
        if not enrollment:
            _log_warning(f"Webhook: no enrollment found for reference {reference}")
            return False
        if enrollment.payment_verified and enrollment.status == "confirmed":
            return True
        enrollment.payment_verified = True
        enrollment.status = "confirmed"
        enrollment.amount_paid = enrollment.course.price
        enrollment.save(update_fields=["payment_verified", "status", "amount_paid"])
        _send_email_async(
            subject="SAED IMS - Course Payment Received",
            message=f"Hello {enrollment.student.get_full_name()},\n\nYour payment for \"{enrollment.course.title}\" has been received.",
            recipient_list=[enrollment.student.email],
            html_message=(
                '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                '<h2 style="color:#1a5f2a;margin-top:0;">Payment Received</h2>'
                f'<p>Your payment for <strong>{enrollment.course.title}</strong> has been received. You are now enrolled.</p></div></div>'
            ),
        )
        _log_info(f"Webhook: course payment verified for {enrollment.student.email} ({enrollment.course.title})")
        return True
    except Exception as exc:
        _log_error(f"Webhook: course payment error for {reference}", exc=exc)
        return False


@csrf_exempt
@require_POST
def paystack_webhook(request):
    """
    Handle Paystack webhook events.

    Verifies the webhook signature and processes charge.success events
    to update payment status server-side.
    """
    signature = request.headers.get("X-Paystack-Signature", "")
    secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
    request_body = request.body

    if not _verify_paystack_signature(request_body, signature, secret_key):
        _log_warning("Webhook: invalid signature received")
        return HttpResponseBadRequest("Invalid signature")

    try:
        event = json.loads(request_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest("Invalid payload")

    event_type = event.get("event", "")
    data = event.get("data", {})
    reference = data.get("reference", "")

    _log_info(f"Webhook: received event {event_type} for reference {reference}")

    if event_type == "charge.success":
        metadata = data.get("metadata", {})
        payment_type = metadata.get("type", "")

        if payment_type == "trainer_activation" or reference.startswith("SAED-") and not reference.startswith("SAED-COURSE-"):
            _handle_trainer_activation(reference)
        elif payment_type == "course_payment" or reference.startswith("SAED-COURSE-"):
            _handle_course_payment(reference)
        else:
            _log_warning(f"Webhook: unknown payment type for reference {reference}")

    return HttpResponse("OK", status=200)


# ═══════════════════════════════════════════════════════════════════════════════
# PAYSTACK REFUND API
# ═══════════════════════════════════════════════════════════════════════════════

def _paystack_refund(transaction_reference, amount_kobo=None, note=None):
    """
    Initiate a refund via Paystack Refund API.
    Returns (success: bool, message: str).
    """
    secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
    if not secret_key:
        return False, "Payment not configured"

    payload = {"transaction": transaction_reference}
    if amount_kobo:
        payload["amount"] = amount_kobo
    if note:
        payload["note"] = note

    try:
        body = _paystack_request("POST", "/refund", data=payload,
            headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"})
        if body.get("status"):
            return True, body.get("message", "Refund initiated")
        return False, body.get("message", "Refund failed")
    except Exception as exc:
        _log_error("Paystack refund error", exc=exc)
        return False, "Refund processing failed"
