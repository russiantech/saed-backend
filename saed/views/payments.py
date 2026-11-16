"""Payment endpoints. All business logic lives in services/payments.py; these are thin."""
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CourseEnrollment, Lesson, LessonAccess, Payment
from ..services import access, config, paystack
from ..services import payments as svc
from ..services.notify import notify
from .base import HasRole, IsAuthenticatedAPI, _log_error, _log_warning, paginate, role_for
from .lessons import video_fee_payload


def payment_payload(p: Payment, include_admin=False):
    data = {
        "reference": p.reference, "type": p.payment_type, "status": p.status,
        "amount": str(config.kobo_to_naira(p.expected_amount_kobo)), "amountKobo": p.expected_amount_kobo,
        "currency": p.currency, "lessonId": p.lesson_id, "lessonTitle": p.lesson.title if p.lesson else None,
        "courseId": str(p.course.public_id) if p.course else (str(p.lesson.course.public_id) if p.lesson else None),
        "courseTitle": p.course.title if p.course else (p.lesson.course.title if p.lesson else None),
        "createdAt": p.created_at.isoformat(), "verifiedAt": p.verified_at.isoformat() if p.verified_at else None,
        "channel": p.channel, "message": p.gateway_message,
    }
    if include_admin:
        data.update({
            "payerId": p.payer_id, "payerName": (p.payer.get_full_name() or p.payer.email) if p.payer else None,
            "payerEmail": p.payer_email, "trainerId": p.trainer_id,
            "trainerName": (p.trainer.get_full_name() or p.trainer.email) if p.trainer else None,
            "paidAmountKobo": p.paid_amount_kobo, "requestedAmountKobo": p.requested_amount_kobo,
            "gatewayFeesKobo": p.gateway_fees_kobo, "platformFeeKobo": p.platform_fee_kobo,
            "trainerShareKobo": p.trainer_share_kobo, "subaccountCode": p.subaccount_code,
            "gatewayStatus": p.gateway_status, "metadata": p.metadata if p.status == "mismatch" else {},
        })
    return data


def _err(exc: svc.PaymentError):
    return Response({"error": exc.message, **exc.extra}, status=exc.http_status)


class PaymentConfigView(APIView):
    """Public checkout configuration for the frontend (never contains secrets)."""
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        fee = config.video_upload_fee()
        return Response({
            "publicKey": paystack.public_key(), "currency": "NGN",
            "videoUploadFee": {"amount": float(fee["amount"]), "amountKobo": fee["amountKobo"],
                               "enabled": fee["enabled"], "applies": fee["applies"]},
            "trainerActivationFeeKobo": config.trainer_activation_fee_kobo(),
        })


class TrainerActivationInitView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request):
        profile = request.user.profile
        if profile.has_paid and profile.payment_verified:
            return Response({"error": "Your trainer account is already activated."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = svc.initialize(payment_type="trainer_activation", payer=request.user,
                                  expected_kobo=config.trainer_activation_fee_kobo(), trainer=request.user,
                                  success_title="Trainer activation payment started.")
        except svc.PaymentError as exc:
            return _err(exc)
        profile.payment_reference = data["reference"]
        profile.save(update_fields=["payment_reference"])
        # legacy snake_case keys kept for the old trainer-activation screen
        return Response({"ok": True, **data, "authorization_url": data["authorizationUrl"],
                         "access_code": data["accessCode"]})


class VideoUploadInitView(APIView):
    """Trainer pays the platform fee to attach a video to ONE lesson."""
    permission_classes = [HasRole("trainer")]

    def post(self, request):
        lid = request.data.get("lessonId")
        try:
            lesson = Lesson.objects.select_related("course").get(pk=lid, course__trainer=request.user)
        except (Lesson.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Lesson not found."}, status=status.HTTP_404_NOT_FOUND)
        fee = config.video_upload_fee()
        if not fee["applies"]:
            return Response({"error": "No upload fee applies right now — you can upload your video directly.",
                             "feeApplies": False}, status=status.HTTP_400_BAD_REQUEST)
        if lesson.video_upload_paid:
            return Response({"error": "The upload fee for this lesson is already paid.", "alreadyPaid": True},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            data = svc.initialize(payment_type="video_upload", payer=request.user, expected_kobo=fee["amountKobo"],
                                  trainer=request.user, course=lesson.course, lesson=lesson,
                                  success_title=f"Video upload fee for “{lesson.title}” started.")
        except svc.PaymentError as exc:
            return _err(exc)
        return Response({"ok": True, **data, "lessonId": lesson.id, "lessonTitle": lesson.title})


class LessonPayInitView(APIView):
    """Corps member pays (Paystack) to unlock one premium lesson."""
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        lid = request.data.get("lessonId")
        try:
            lesson = Lesson.objects.select_related("course", "course__trainer", "course__trainer__profile").get(
                pk=lid, is_published=True)
        except (Lesson.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Lesson not found."}, status=status.HTTP_404_NOT_FOUND)
        course = lesson.course
        if course.is_restricted or not course.is_published or not course.is_active:
            return Response({"error": "Lesson not found."}, status=status.HTTP_404_NOT_FOUND)
        if not lesson.requires_payment():
            return Response({"error": "This lesson is free.", "isFree": True}, status=status.HTTP_400_BAD_REQUEST)
        if not access.can_consume_course(request.user, course):
            return Response({"error": "Enrol in the course before unlocking its lessons.", "enrolRequired": True},
                            status=status.HTTP_403_FORBIDDEN)
        if LessonAccess.objects.filter(student=request.user, lesson=lesson, status="active").exists():
            return Response({"error": "You already have access to this lesson.", "hasAccess": True},
                            status=status.HTTP_400_BAD_REQUEST)
        kobo = config.naira_to_kobo(lesson.price)
        platform, share = config.split_lesson_amount(kobo)
        prof = getattr(course.trainer, "profile", None)
        sub = prof.paystack_subaccount_code if prof and prof.bank_verified else ""
        try:
            data = svc.initialize(payment_type="lesson_access", payer=request.user, expected_kobo=kobo,
                                  trainer=course.trainer, course=course, lesson=lesson, subaccount=sub or "",
                                  platform_fee_kobo=platform, trainer_share_kobo=share,
                                  success_title=f"Payment for “{lesson.title}” started.")
        except svc.PaymentError as exc:
            return _err(exc)
        return Response({"ok": True, **data, "lessonId": lesson.id, "lessonTitle": lesson.title})


class PaymentVerifyView(APIView):
    """Server-side verification. Idempotent: verifying the same reference twice is safe and
    never reports a successful payment as failed."""
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        reference = (request.data.get("reference") or "").strip()
        if not reference:
            return Response({"error": "Reference is required.", "fields": {"reference": "Reference is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = svc.verify_reference(reference, request.user)
        except svc.PaymentError as exc:
            return _err(exc)
        except Exception as exc:
            _log_error("Payment verify error", exc=exc)
            return Response({"error": "Verification failed. Please retry.", "retry": True},
                            status=status.HTTP_502_BAD_GATEWAY)
        p = result.payment
        body = {"status": result.state, "reference": p.reference, "paymentType": p.payment_type,
                "alreadyProcessed": result.already_processed, "payment": payment_payload(p),
                "lessonId": p.lesson_id,
                "courseId": str(p.course.public_id) if p.course else None}
        if result.state == "success":
            body.update(ok=True, hasAccess=True, message="Payment confirmed.")
            return Response(body)
        if result.state == "mismatch":
            body.update(ok=False, error="Your payment could not be matched automatically. Our team has been notified; "
                                          "you have not lost your money.", details=result.detail)
            return Response(body, status=status.HTTP_409_CONFLICT)
        body.update(ok=False, message={"pending": "Payment not completed yet.",
                                       "failed": "Payment was not successful.",
                                       "abandoned": "Payment was cancelled."}.get(result.state, ""))
        return Response(body)


class MyPaymentsView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        qs = Payment.objects.filter(payer=request.user).select_related("lesson", "lesson__course", "course")
        items, pagination = paginate(request, qs, default_size=20, max_size=100)
        return Response({"payments": [payment_payload(p) for p in items], "pagination": pagination})


class PaymentDetailView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, reference):
        p = Payment.objects.select_related("lesson", "lesson__course", "course", "payer", "trainer").filter(reference=reference).first()
        if not p or (p.payer_id != request.user.id and p.trainer_id != request.user.id and not access.is_admin(request.user)):
            return Response({"error": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"payment": payment_payload(p, include_admin=access.is_admin(request.user))})


# ── Trainer earnings ──────────────────────────────────────────────────────────
class TrainerEarningsView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        user = request.user
        sales = Payment.objects.filter(trainer=user, payment_type="lesson_access", status="success")
        agg = sales.aggregate(gross=Sum("expected_amount_kobo"), platform=Sum("platform_fee_kobo"),
                              net=Sum("trainer_share_kobo"), n=Count("id"))
        settled = sales.exclude(subaccount_code="").aggregate(s=Sum("trainer_share_kobo"))["s"] or 0
        unsettled = (agg["net"] or 0) - settled
        fees_paid = Payment.objects.filter(payer=user, payment_type="video_upload", status="success") \
            .aggregate(s=Sum("expected_amount_kobo"), n=Count("id"))
        transfers = LessonAccess.objects.filter(lesson__course__trainer=user, source="bank_transfer", status="active")
        prof = user.profile
        recent_qs = Payment.objects.filter(trainer=user, payment_type="lesson_access").select_related(
            "lesson", "lesson__course", "course", "payer")
        status_f = request.GET.get("status")
        if status_f:
            recent_qs = recent_qs.filter(status=status_f)
        items, pagination = paginate(request, recent_qs, default_size=20, max_size=100)
        k = config.kobo_to_naira
        return Response({
            "summary": {
                "salesCount": agg["n"] or 0, "gross": str(k(agg["gross"])), "platformFees": str(k(agg["platform"])),
                "net": str(k(agg["net"])), "settledToBank": str(k(settled)), "pendingSettlement": str(k(unsettled)),
                "videoFeesPaid": str(k(fees_paid["s"])), "videoUploadsPaid": fees_paid["n"] or 0,
                "directTransferUnlocks": transfers.count(),
                "lessonPlatformFeePercent": float(config.lesson_platform_fee_percent()),
            },
            "payout": {"bankName": prof.bank_name, "accountName": prof.account_name,
                       "accountNumberMasked": ("•••• " + prof.account_number[-4:]) if prof.account_number else "",
                       "verified": prof.bank_verified, "hasSubaccount": bool(prof.paystack_subaccount_code)},
            "payments": [{**payment_payload(p), "studentName": (p.payer.get_full_name() or p.payer.email) if p.payer else "",
                          "platformFee": str(k(p.platform_fee_kobo)), "yourShare": str(k(p.trainer_share_kobo)),
                          "settlement": "bank (auto-split)" if p.subaccount_code else "pending payout"} for p in items],
            "pagination": pagination,
        })


# ── Webhook ───────────────────────────────────────────────────────────────────
@csrf_exempt
@require_POST
def paystack_webhook(request):
    code, text = svc.handle_webhook(request.body, request.headers.get("X-Paystack-Signature", ""))
    return HttpResponse(text, status=code)


# ── Legacy enrolment refunds (historic paid enrolments only) ──────────────────
class AdminPendingRefundsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        enrollments = CourseEnrollment.objects.filter(refund_requested=True, refund_processed=False) \
            .select_related("student", "course", "course__trainer")
        return Response({"refunds": [{
            "id": e.id, "studentName": e.student.get_full_name() or e.student.email, "studentEmail": e.student.email,
            "courseTitle": e.course.title,
            "trainerName": (e.course.trainer.get_full_name() or e.course.trainer.email) if e.course.trainer else "",
            "amount": str(e.amount_paid), "paymentReference": e.payment_reference, "status": e.status,
            "refundRequestedAt": e.refund_requested_at.isoformat() if e.refund_requested_at else None,
        } for e in enrollments]})


class AdminProcessRefundView(APIView):
    permission_classes = [HasRole("dunis_admin")]   # money decisions: Dunis has final authority

    def post(self, request, enrollment_id):
        note = request.data.get("note", "")
        try:
            e = CourseEnrollment.objects.select_related("student", "course").get(
                id=enrollment_id, refund_requested=True, refund_processed=False)
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Refund not found."}, status=status.HTTP_404_NOT_FOUND)
        ok, msg = False, ""
        if e.payment_reference:
            try:
                body = paystack.refund_transaction(e.payment_reference, config.naira_to_kobo(e.amount_paid),
                                                   note or f"Refund for {e.course.title}")
                ok, msg = bool(body.get("status")), body.get("message", "")
            except paystack.PaystackError as exc:
                _log_warning(f"Paystack refund failed: {exc}")
                return Response({"error": "Could not reach Paystack. Nothing was changed; please retry."},
                                status=status.HTTP_502_BAD_GATEWAY)
            if not ok:
                return Response({"error": msg or "Paystack refused the refund."}, status=status.HTTP_400_BAD_REQUEST)
        e.refund_processed, e.refund_processed_at = True, now()
        e.refund_note = note or msg
        e.status = "refunded"
        e.save(update_fields=["refund_processed", "refund_processed_at", "refund_note", "status"])
        notify(e.student, "Refund processed", f"Your refund of ₦{e.amount_paid} for “{e.course.title}” has been processed.",
               reason="payment_success", link="/app/applications")
        return Response({"ok": True, "message": "Refund processed."})


class AdminRejectRefundView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def post(self, request, enrollment_id):
        note = request.data.get("note", "")
        try:
            e = CourseEnrollment.objects.select_related("student", "course").get(
                id=enrollment_id, refund_requested=True, refund_processed=False)
        except CourseEnrollment.DoesNotExist:
            return Response({"error": "Refund not found."}, status=status.HTTP_404_NOT_FOUND)
        e.refund_processed, e.refund_processed_at = True, now()
        e.refund_note = note or "Refund denied by admin"
        e.save(update_fields=["refund_processed", "refund_processed_at", "refund_note"])
        notify(e.student, "Refund denied", f"Your refund request for “{e.course.title}” was denied.",
               reason="payment_failed", link="/app/applications")
        return Response({"ok": True, "message": "Refund denied."})
