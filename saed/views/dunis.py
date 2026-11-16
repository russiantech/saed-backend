"""Dunis Admin: platform fees, payments monitor, trainer payments, access activity."""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import LessonAccess, Payment, PlatformSetting, Profile
from ..services import access, config
from ..services import payments as svc
from .base import HasRole, IsAuthenticatedAPI, _log_error, paginate
from .payments import payment_payload


class DunisPendingPaymentsView(APIView):
    """Authorised trainers who have not completed the activation payment."""
    permission_classes = [HasRole("dunis_admin")]

    def get(self, request):
        profiles = Profile.objects.filter(role="trainer", is_authorized=True, has_paid=False) \
            .exclude(is_hidden=True).select_related("user")
        return Response({"trainers": [{
            "id": p.user.id, "fullName": p.user.get_full_name() or p.user.email, "email": p.user.email,
            "phone": p.phone, "specialization": p.specialization, "companyName": p.company_name,
            "hasPaid": p.has_paid, "paymentVerified": p.payment_verified, "paymentReference": p.payment_reference,
            "authorizedAt": p.authorized_at.isoformat() if p.authorized_at else None,
        } for p in profiles]})


class DunisConfirmPaymentView(APIView):
    """Re-verify a trainer's activation payment against Paystack (same rules as the automatic flow)."""
    permission_classes = [HasRole("dunis_admin")]

    def post(self, request):
        user_id = request.data.get("userId")
        reference = (request.data.get("reference") or "").strip()
        if not user_id:
            return Response({"error": "User ID is required."}, status=status.HTTP_400_BAD_REQUEST)
        profile = Profile.objects.select_related("user").filter(user_id=user_id).first() \
            if str(user_id).isdigit() else None
        if not profile:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if profile.role != "trainer":
            return Response({"error": "This user is not a trainer."}, status=status.HTTP_400_BAD_REQUEST)
        if not reference or reference != profile.payment_reference:
            return Response({"error": "Payment reference does not match this trainer's payment."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            result = svc.verify_reference(reference, request.user)
        except svc.PaymentError as exc:
            return Response({"error": exc.message}, status=exc.http_status)
        if result.state != "success":
            return Response({"error": f"Paystack verification did not confirm this payment ({result.state}).",
                             "status": result.state}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"ok": True, "message": "Payment confirmed. Account activated."})


class DunisAllTrainersView(APIView):
    permission_classes = [HasRole("dunis_admin")]

    def get(self, request):
        profiles = Profile.objects.filter(role="trainer").exclude(is_hidden=True).select_related("user") \
            .order_by("user__first_name")
        return Response({"trainers": [{
            "id": p.user.id, "fullName": p.user.get_full_name() or p.user.email, "email": p.user.email,
            "specialization": p.specialization, "isAuthorized": p.is_authorized, "isActive": p.user.is_active,
            "hasPaid": p.has_paid, "paymentVerified": p.payment_verified, "paymentReference": p.payment_reference,
            "authorizationStatus": p.authorization_status, "bankVerified": p.bank_verified,
            "hasPayoutAccount": bool(p.paystack_subaccount_code),
        } for p in profiles]})


class _AdminReadDunisWrite(BasePermission):
    def has_permission(self, request, view):
        role = access.role_of(request.user) if request.user and request.user.is_authenticated else None
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return role in ("saed_admin", "dunis_admin")
        return role == "dunis_admin"


def settings_payload():
    fee = config.video_upload_fee()
    return {
        "videoUploadFee": {"amount": float(fee["amount"]), "enabled": fee["enabled"], "currency": "NGN",
                           "applies": fee["applies"]},
        "lessonPlatformFeePercent": float(config.lesson_platform_fee_percent()),
        "trainerActivationFee": {"amount": float(config.kobo_to_naira(config.trainer_activation_fee_kobo())),
                                 "currency": "NGN"},
        "defaultDeactivationGraceDays": PlatformSetting.get("default_deactivation_grace_days", 7),
    }


def _bool(v):
    if isinstance(v, bool):
        return v
    if str(v).strip().lower() in ("true", "1", "yes", "on"):
        return True
    if str(v).strip().lower() in ("false", "0", "no", "off", ""):
        return False
    raise ValueError("Enter true or false.")


def _amount(value, minimum=Decimal(0)):
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ArithmeticError):
        raise ValueError("Enter a valid amount.")
    if not d.is_finite() or d < minimum or d > Decimal("100000000"):
        raise ValueError("Enter a valid amount.")
    return d.quantize(Decimal("0.01"))


class PlatformSettingsView(APIView):
    """Fees are configuration, not code. SAED Admin can read; only Dunis Admin can change."""
    permission_classes = [_AdminReadDunisWrite]

    def get(self, request):
        return Response(settings_payload())

    def patch(self, request):
        d = request.data
        errors = {}
        try:
          with transaction.atomic():
            if "videoUploadFee" in d:
                v = d["videoUploadFee"]
                cur = config.video_upload_fee()
                amount, enabled = cur["amount"], cur["enabled"]
                if isinstance(v, dict):
                    if "amount" in v:
                        amount = _amount(v["amount"])
                    if "enabled" in v:
                        enabled = _bool(v["enabled"])
                else:
                    amount = _amount(v)
                PlatformSetting.set(config.KEY_VIDEO_FEE, {"amount": float(amount), "currency": "NGN", "enabled": enabled})
            if "lessonPlatformFeePercent" in d:
                pct = _amount(d["lessonPlatformFeePercent"])
                if pct > 100:
                    raise ValueError("Percent must be between 0 and 100.")
                PlatformSetting.set(config.KEY_LESSON_PCT, float(pct))
            if "trainerActivationFee" in d:
                v = d["trainerActivationFee"]
                amt = _amount(v.get("amount") if isinstance(v, dict) else v, Decimal("1"))
                PlatformSetting.set(config.KEY_ACTIVATION, {"amount": float(amt), "currency": "NGN"})
            if "defaultDeactivationGraceDays" in d:
                days = int(d["defaultDeactivationGraceDays"])
                if days < 0 or days > 365:
                    raise ValueError("Grace days must be 0–365.")
                PlatformSetting.set("default_deactivation_grace_days", days)
        except (ValueError, TypeError) as exc:
            errors["error"] = str(exc) or "Invalid value."
        if errors:
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)
        return Response(settings_payload())


class DunisPaymentsView(APIView):
    """Every payment on the platform, filterable, with money totals."""
    permission_classes = [HasRole("dunis_admin")]

    def get(self, request):
        qs = Payment.objects.select_related("payer", "trainer", "lesson", "lesson__course", "course")
        g = request.GET
        if g.get("type"):
            qs = qs.filter(payment_type=g["type"])
        if g.get("status"):
            qs = qs.filter(status=g["status"])
        if g.get("trainerId", "").isdigit():
            qs = qs.filter(trainer_id=int(g["trainerId"]))
        q = (g.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(payer_email__icontains=q)
                           | Q(lesson__title__icontains=q) | Q(course__title__icontains=q))
        df, dt = parse_date(g.get("from") or ""), parse_date(g.get("to") or "")
        if df:
            qs = qs.filter(created_at__date__gte=df)
        if dt:
            qs = qs.filter(created_at__date__lte=dt)
        k = config.kobo_to_naira
        ok = qs.filter(status="success")
        by_type = {r["payment_type"]: r for r in ok.values("payment_type").annotate(
            total=Sum("expected_amount_kobo"), platform=Sum("platform_fee_kobo"), n=Count("id"))}

        def tot(t):
            r = by_type.get(t, {})
            return {"count": r.get("n", 0), "total": str(k(r.get("total"))), "platformShare": str(k(r.get("platform")))}

        counts = {r["status"]: r["n"] for r in qs.values("status").annotate(n=Count("id"))}
        items, pagination = paginate(request, qs, default_size=25, max_size=200)
        return Response({
            "payments": [payment_payload(p, include_admin=True) for p in items], "pagination": pagination,
            "summary": {"videoUploads": tot("video_upload"), "lessonAccess": tot("lesson_access"),
                        "trainerActivation": tot("trainer_activation"),
                        "statusCounts": {s: counts.get(s, 0) for s in
                                         ("pending", "success", "failed", "abandoned", "mismatch", "refunded")}},
        })


class DunisPaymentResolveView(APIView):
    """Final decision on a payment flagged for review (amount/currency/customer mismatch)."""
    permission_classes = [HasRole("dunis_admin")]

    def post(self, request, reference):
        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            p = svc.resolve_mismatch(reference, action == "approve", request.user, request.data.get("note", ""))
        except Payment.DoesNotExist:
            return Response({"error": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)
        except svc.PaymentError as exc:
            return Response({"error": exc.message}, status=exc.http_status)
        return Response({"ok": True, "payment": payment_payload(p, include_admin=True)})


class DunisAccessActivityView(APIView):
    """Corps-member lesson payments & access grants (who unlocked what, how)."""
    permission_classes = [HasRole("dunis_admin", "saed_admin")]

    def get(self, request):
        qs = LessonAccess.objects.select_related("student", "lesson", "lesson__course", "lesson__course__trainer")
        if request.GET.get("status"):
            qs = qs.filter(status=request.GET["status"])
        if request.GET.get("source"):
            qs = qs.filter(source=request.GET["source"])
        items, pagination = paginate(request, qs.order_by("-updated_at"), default_size=25, max_size=200)
        return Response({"activity": [{
            "id": a.id, "student": a.student.get_full_name() or a.student.email, "lessonId": a.lesson_id,
            "lesson": a.lesson.title, "course": a.lesson.course.title, "courseId": str(a.lesson.course.public_id),
            "trainer": (a.lesson.course.trainer.get_full_name() or a.lesson.course.trainer.email)
            if a.lesson.course.trainer else "",
            "status": a.status, "source": a.source, "amountPaid": str(a.amount_paid),
            "paymentReference": a.payment_reference, "updatedAt": a.updated_at.isoformat(),
        } for a in items], "pagination": pagination})
