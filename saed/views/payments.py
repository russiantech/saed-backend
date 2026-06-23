"""
Payment views: Paystack init/verify, enrollments, refunds.
"""

import json
import urllib.request
import urllib.error
from django.conf import settings as django_settings
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Course, CourseEnrollment, Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async, _notify_admins,
    read_json, validation_error, HasRole, IsAuthenticatedAPI,
)


class PaystackInitializeView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        data = request.data
        email = data.get("email", "")
        default_amount = getattr(django_settings, "PAYSTACK_DEFAULT_AMOUNT", 50000)
        amount = data.get("amount", default_amount)

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
            profile = Profile.objects.filter(user__email=email, role="trainer").first()
            if profile:
                profile.payment_reference = reference
                profile.save(update_fields=["payment_reference"])
        except Exception as exc:
            _log_error("Paystack profile update error", exc=exc)

        amount_kobo = int(float(amount) * 100)
        payload = json.dumps({
            "email": email, "amount": amount_kobo,
            "reference": reference, "metadata": {"reference": reference},
        }).encode()

        api_url = getattr(django_settings, "PAYSTACK_API_URL", "https://api.paystack.co")
        req = urllib.request.Request(
            f"{api_url}/transaction/initialize", data=payload,
            headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            if body.get("status"):
                return Response({
                    "ok": True, "reference": reference,
                    "authorization_url": body["data"]["authorization_url"],
                    "access_code": body["data"]["access_code"],
                    "message": "Payment initialized.",
                })
            return Response({"error": body.get("message", "Payment initialization failed.")},
                            status=status.HTTP_400_BAD_REQUEST)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode()) if e.readable() else {}
            return Response({"error": body.get("message", "Payment gateway error.")},
                            status=status.HTTP_400_BAD_REQUEST)
        except urllib.error.URLError:
            return Response({"error": "Unable to connect to payment gateway."},
                            status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            _log_error("Paystack unexpected error", exc=exc)
            return Response({"error": "Payment initialization failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CoursePayInitializeView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        data = request.data
        course_id = data.get("courseId")
        if not course_id:
            return Response({"error": "Course ID is required.",
                             "fields": {"courseId": "Course ID is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            course = Course.objects.get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        if course.price <= 0:
            return Response({"error": "This course is free."}, status=status.HTTP_400_BAD_REQUEST)

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
            if enrollment.status == "pending":
                return Response({"error": "Payment already pending trainer confirmation.", "pending": True},
                                status=status.HTTP_400_BAD_REQUEST)
            if enrollment.status == "refunded":
                enrollment.status = "pending"
                enrollment.refund_requested = False
                enrollment.refund_requested_at = None
                enrollment.refund_processed = False
                enrollment.refund_processed_at = None
                enrollment.refund_note = ""

            reference = f"SAED-COURSE-{get_random_string(12).upper()}"
            enrollment.payment_reference = reference
            enrollment.amount_paid = course.price
            enrollment.save(update_fields=[
                "payment_reference", "amount_paid", "status",
                "refund_requested", "refund_requested_at",
                "refund_processed", "refund_processed_at", "refund_note",
            ])

            secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
            if not secret_key:
                return Response({"error": "Payment is not configured."},
                                status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            amount_kobo = int(float(course.price) * 100)
            payload = json.dumps({
                "email": request.user.email, "amount": amount_kobo,
                "reference": reference,
                "metadata": {"reference": reference, "course_id": course.id},
            }).encode()

            api_url = getattr(django_settings, "PAYSTACK_API_URL", "https://api.paystack.co")
            req = urllib.request.Request(
                f"{api_url}/transaction/initialize", data=payload,
                headers={"Authorization": f"Bearer {secret_key}", "Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            if body.get("status"):
                return Response({
                    "ok": True, "reference": reference,
                    "authorization_url": body["data"]["authorization_url"],
                    "access_code": body["data"]["access_code"],
                    "amount": str(course.price), "courseTitle": course.title,
                })
            return Response({"error": body.get("message", "Payment initialization failed.")},
                            status=status.HTTP_400_BAD_REQUEST)
        except urllib.error.HTTPError as e:
            body = json.loads(e.read().decode()) if e.readable() else {}
            return Response({"error": body.get("message", "Payment gateway error.")},
                            status=status.HTTP_400_BAD_REQUEST)
        except urllib.error.URLError:
            return Response({"error": "Unable to connect to payment gateway."},
                            status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            _log_error("Course payment init error", exc=exc)
            return Response({"error": "Payment initialization failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CoursePayVerifyView(APIView):
    permission_classes = [IsAuthenticatedAPI]

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
            if enrollment.status == "pending":
                return Response({"ok": True, "message": "Payment already pending trainer confirmation."})
            if enrollment.status == "confirmed":
                return Response({"ok": True, "message": "Already verified."})

            secret_key = getattr(django_settings, "PAYSTACK_SECRET_KEY", "")
            if secret_key:
                api_url = getattr(django_settings, "PAYSTACK_API_URL", "https://api.paystack.co")
                req = urllib.request.Request(
                    f"{api_url}/transaction/verify/{reference}",
                    headers={"Authorization": f"Bearer {secret_key}"},
                )
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        body = json.loads(resp.read().decode())
                    if not body.get("status") or body.get("data", {}).get("status") != "success":
                        return Response({"error": body.get("message", "Payment not successful.")},
                                        status=status.HTTP_400_BAD_REQUEST)
                except Exception as exc:
                    _log_error("Payment verification gateway error", exc=exc)
                    return Response({"error": "Unable to verify payment with gateway."},
                                    status=status.HTTP_502_BAD_GATEWAY)

            enrollment.status = "pending"
            enrollment.amount_paid = enrollment.course.price
            enrollment.save(update_fields=["status", "amount_paid"])
            return Response({"ok": True, "message": "Payment submitted. Waiting for trainer confirmation."})
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


class TrainerPendingEnrollmentsView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        try:
            enrollments = CourseEnrollment.objects.filter(
                course__trainer=request.user, status="pending"
            ).select_related("student", "course")
            result = []
            for e in enrollments:
                result.append({
                    "id": e.id,
                    "studentName": e.student.get_full_name() or e.student.email,
                    "studentEmail": e.student.email,
                    "courseTitle": e.course.title,
                    "courseId": e.course.id,
                    "amount": str(e.amount_paid),
                    "paymentReference": e.payment_reference,
                    "enrolledAt": e.enrolled_at.isoformat(),
                })
            return Response({"enrollments": result})
        except Exception as exc:
            _log_error("Pending enrollments error", exc=exc)
            return Response({"error": "Failed to load enrollments."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrainerConfirmEnrollmentView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, enrollment_id):
        try:
            enrollment = CourseEnrollment.objects.select_related(
                "student", "course"
            ).get(id=enrollment_id, course__trainer=request.user, status="pending")
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Enrollment not found."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            enrollment.status = "confirmed"
            enrollment.confirmed_by = request.user
            enrollment.confirmed_at = now()
            enrollment.save(update_fields=["status", "confirmed_by", "confirmed_at"])

            _send_email_async(
                subject="SAED IMS - Course Enrollment Confirmed",
                message=f"Hello {enrollment.student.get_full_name()},\n\nYour payment for \"{enrollment.course.title}\" has been confirmed.",
                recipient_list=[enrollment.student.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Enrollment Confirmed</h2>'
                    f'<p>Your payment for <strong>{enrollment.course.title}</strong> has been confirmed.</p></div></div>'
                ),
            )
            return Response({"ok": True, "message": "Enrollment confirmed."})
        except Exception as exc:
            _log_error(f"Enrollment confirmation error for {enrollment_id}", exc=exc)
            return Response({"error": "Failed to confirm enrollment."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrainerRejectEnrollmentView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, enrollment_id):
        try:
            enrollment = CourseEnrollment.objects.select_related(
                "student", "course"
            ).get(id=enrollment_id, course__trainer=request.user, status="pending")
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Enrollment not found."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            enrollment.status = "rejected"
            enrollment.confirmed_by = request.user
            enrollment.confirmed_at = now()
            enrollment.refund_requested = True
            enrollment.refund_requested_at = now()
            enrollment.save(update_fields=[
                "status", "confirmed_by", "confirmed_at",
                "refund_requested", "refund_requested_at",
            ])

            _send_email_async(
                subject="SAED IMS - Course Payment Not Verified",
                message=f"Hello {enrollment.student.get_full_name()},\n\nYour payment could not be verified. A refund has been initiated.",
                recipient_list=[enrollment.student.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#c0392b;margin-top:0;">Payment Not Verified</h2>'
                    f'<p>Your payment for <strong>{enrollment.course.title}</strong> could not be verified. A refund of <strong>\u20a6{enrollment.amount_paid}</strong> has been initiated.</p></div></div>'
                ),
            )
            _notify_admins(
                title="Refund Required",
                message=f"Payment rejected for {enrollment.student.get_full_name()} ({enrollment.course.title}).",
                reason="admin_update",
            )
            return Response({"ok": True, "message": "Enrollment rejected. Refund flagged."})
        except Exception as exc:
            _log_error(f"Enrollment rejection error for {enrollment_id}", exc=exc)
            return Response({"error": "Failed to reject enrollment."},
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
            enrollment.refund_processed = True
            enrollment.refund_processed_at = now()
            enrollment.refund_note = note
            enrollment.status = "refunded"
            enrollment.save(update_fields=[
                "refund_processed", "refund_processed_at", "refund_note", "status"
            ])
            _send_email_async(
                subject="SAED IMS - Refund Processed",
                message=f"Hello {enrollment.student.get_full_name()},\n\nYour refund of \u20a6{enrollment.amount_paid} has been processed.",
                recipient_list=[enrollment.student.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Refund Processed</h2>'
                    f'<p>Your refund of <strong>\u20a6{enrollment.amount_paid}</strong> for <strong>{enrollment.course.title}</strong> has been processed.</p></div></div>'
                ),
            )
            return Response({"ok": True, "message": "Refund processed."})
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
