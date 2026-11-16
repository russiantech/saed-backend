"""Unified payment service: initialise → verify (server-side) → finalise → entitle.

Used by the trainer activation fee, the per-lesson video upload fee and corps-member
premium lesson payments. Paid content is NEVER unlocked from a frontend claim: the
only way a Payment becomes ``success`` is `apply_gateway_result`, which validates the
Paystack transaction (status, reference, currency, exact requested amount, payer).
"""
import json
import logging
from datetime import timedelta
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils.crypto import get_random_string
from django.utils.timezone import now

from ..models import Lesson, LessonAccess, Payment, Profile, WebhookEvent
from . import config, paystack
from .notify import course_link, frontend_url, notify, notify_admins

logger = logging.getLogger(__name__)

REF_PREFIX = {"trainer_activation": "ACT", "video_upload": "VID", "lesson_access": "LES"}
REUSE_WINDOW_MINUTES = 30


class PaymentError(Exception):
    def __init__(self, message, http_status=400, extra=None):
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.extra = extra or {}


@dataclass
class Result:
    state: str                      # success | pending | failed | abandoned | mismatch
    payment: Payment
    already_processed: bool = False
    detail: dict = field(default_factory=dict)


def new_reference(payment_type: str) -> str:
    return f"SAED-{REF_PREFIX[payment_type]}-{get_random_string(16).upper()}"


def _callback_url(reference: str) -> str:
    return frontend_url(f"/app/payment/callback?reference={reference}")


def _init_payload(payment: Payment, data: dict) -> dict:
    return {
        "reference": payment.reference,
        "accessCode": data.get("access_code") or payment.metadata.get("access_code", ""),
        "authorizationUrl": data.get("authorization_url") or payment.metadata.get("authorization_url", ""),
        "publicKey": paystack.public_key(),
        "amount": str(config.kobo_to_naira(payment.expected_amount_kobo)),
        "amountKobo": payment.expected_amount_kobo,
        "currency": payment.currency,
        "paymentType": payment.payment_type,
        "email": payment.payer_email,
    }


def initialize(*, payment_type, payer, expected_kobo, trainer=None, course=None, lesson=None,
               metadata=None, subaccount="", platform_fee_kobo=0, trainer_share_kobo=0,
               success_title="") -> dict:
    """Create the Payment row, then the Paystack transaction. Reuses a recent pending
    payment for the same payer+resource so repeated clicks never create duplicates."""
    if not payer.email:
        raise PaymentError("An email address is required to pay.", 400)
    if expected_kobo <= 0:
        raise PaymentError("Nothing to pay for this item.", 400)
    try:
        paystack.secret_key()
    except paystack.PaystackNotConfigured:
        raise PaymentError("Payment is not configured.", 503)

    cutoff = now() - timedelta(minutes=REUSE_WINDOW_MINUTES)
    with transaction.atomic():
        if lesson is not None:   # serialise concurrent inits for the same lesson (no double charge)
            Lesson.objects.select_for_update().filter(pk=lesson.pk).first()
        existing = Payment.objects.filter(
            payer=payer, payment_type=payment_type, status="pending",
            lesson=lesson, expected_amount_kobo=expected_kobo, created_at__gte=cutoff,
        ).order_by("-created_at").first()
        if existing and existing.metadata.get("access_code"):
            return _init_payload(existing, {})
        if existing and (now() - existing.created_at).total_seconds() < 30:
            # another request is mid-initialisation: do not create a second charge
            raise PaymentError("A payment for this item is already starting. Please wait a moment and try again.", 409)
        reference = new_reference(payment_type)
        payment = Payment.objects.create(
            reference=reference, payment_type=payment_type, payer=payer, payer_email=payer.email.lower(),
            trainer=trainer, course=course, lesson=lesson, expected_amount_kobo=expected_kobo,
            platform_fee_kobo=platform_fee_kobo, trainer_share_kobo=trainer_share_kobo,
            subaccount_code=subaccount or "", metadata={**(metadata or {}), "type": payment_type, "payer_id": payer.id,
                                                     "lesson_id": lesson.id if lesson else None,
                                                     "course_id": course.id if course else None},
        )
    meta = payment.metadata
    try:
        body = paystack.initialize_transaction(
            email=payer.email, amount_kobo=expected_kobo, reference=reference,
            callback_url=_callback_url(reference), metadata=meta, subaccount=subaccount,
            transaction_charge_kobo=platform_fee_kobo if subaccount else None,
        )
    except paystack.PaystackError as exc:
        payment.status = "failed"
        payment.gateway_message = str(exc)[:255]
        payment.save(update_fields=["status", "gateway_message", "updated_at"])
        raise PaymentError("Unable to reach the payment gateway. Please try again.", 502)

    if not body.get("status"):
        payment.status = "failed"
        payment.gateway_message = (body.get("message") or "")[:255]
        payment.save(update_fields=["status", "gateway_message", "updated_at"])
        raise PaymentError(body.get("message") or "Payment initialisation failed.", 400)

    data = body.get("data") or {}
    payment.metadata = {**payment.metadata, "access_code": data.get("access_code", ""),
                        "authorization_url": data.get("authorization_url", "")}
    payment.save(update_fields=["metadata", "updated_at"])
    notify(payer, "Payment started",
           success_title or f"Payment of ₦{config.kobo_to_naira(expected_kobo):,.2f} started. "
                           "You'll be notified once it is confirmed.",
           reason="payment_initiated", link=f"/app/payment/callback?reference={reference}", email=False)
    return _init_payload(payment, data)


# ── Finalisation ─────────────────────────────────────────────────────────────
def _validate(payment: Payment, data: dict):
    problems = []
    if (data.get("reference") or "") != payment.reference:
        problems.append("reference")
    if (data.get("currency") or "").upper() != payment.currency:
        problems.append("currency")
    ok, detail = paystack.check_amount(data, payment.expected_amount_kobo)
    if not ok:
        problems.append("amount")
    email = ((data.get("customer") or {}).get("email") or "").lower()
    if payment.payer_email and email and email != payment.payer_email.lower():
        problems.append("customer")
    return problems, detail


@transaction.atomic
def apply_gateway_result(reference: str, data: dict, source: str = "verify") -> Result:
    """Idempotent. Safe to call from verify endpoint AND webhook, concurrently or repeatedly."""
    try:
        payment = Payment.objects.select_for_update().get(reference=reference)
    except Payment.DoesNotExist:
        raise PaymentError("Payment record not found.", 404)

    if payment.status == "success":
        return Result("success", payment, already_processed=True)
    if payment.status in ("refunded", "mismatch"):
        return Result(payment.status if payment.status == "mismatch" else "failed", payment, already_processed=True)

    gw_status = (data.get("status") or "").lower()
    payment.gateway_status = gw_status[:32]
    payment.gateway_message = (data.get("gateway_response") or "")[:255]
    payment.channel = (data.get("channel") or "")[:32]

    if gw_status == "success":
        problems, detail = _validate(payment, data)
        payment.paid_amount_kobo = int(data.get("amount") or 0)
        payment.requested_amount_kobo = int(data.get("requested_amount") or 0)
        payment.gateway_fees_kobo = int(data.get("fees") or 0)
        if problems:
            payment.status = "mismatch"
            payment.metadata = {**payment.metadata, "mismatch": problems, "detail": detail, "source": source}
            payment.save()
            logger.warning("Payment %s mismatch %s %s", reference, problems, detail)
            notify_admins("Payment needs review",
                          f"Payment {reference} was paid on Paystack but failed validation ({', '.join(problems)}). "
                          "Access was NOT granted.", reason="payment_failed",
                          link="/app/dunis-admin?tab=payments", roles=("dunis_admin",))
            if payment.payer:
                notify(payment.payer, "We're checking your payment",
                       "Your payment went through but could not be matched automatically. "
                       "Our team has been alerted and will resolve it shortly.",
                       reason="payment_failed", link=f"/app/payment/callback?reference={reference}")
            return Result("mismatch", payment, detail={**detail, "problems": problems})

        payment.status = "success"
        payment.verified_at = now()
        payment.save()
        _EFFECTS[payment.payment_type](payment)
        return Result("success", payment)

    if gw_status in ("failed", "reversed"):
        payment.status = "failed"
        payment.save()
        if payment.payer:
            notify(payment.payer, "Payment failed", f"Your payment {reference} was not successful. "
                   "You have not been charged. You can try again.", reason="payment_failed",
                   link=f"/app/payment/callback?reference={reference}")
        return Result("failed", payment)
    if gw_status == "abandoned":
        payment.status = "abandoned"
        payment.save()
        return Result("abandoned", payment)

    payment.save()
    return Result("pending", payment)


def verify_reference(reference: str, user=None) -> Result:
    """Server-side verification against Paystack for a reference the user owns."""
    try:
        payment = Payment.objects.get(reference=reference)
    except Payment.DoesNotExist:
        raise PaymentError("Payment record not found.", 404)
    if user is not None:
        from .access import is_admin
        if payment.payer_id != user.id and not is_admin(user):
            raise PaymentError("Payment record not found.", 404)
    if payment.status in ("success", "mismatch", "refunded"):
        return apply_gateway_result(reference, {}, "cache")
    try:
        body = paystack.verify_transaction(reference)
    except paystack.PaystackNotConfigured:
        raise PaymentError("Payment is not configured.", 503)
    except paystack.PaystackError:
        raise PaymentError("Unable to verify payment with the gateway right now. Please retry.", 502)
    if not body.get("status"):
        # e.g. "Transaction reference not found" – customer never completed checkout
        return Result("pending", payment, detail={"message": body.get("message", "")})
    return apply_gateway_result(reference, body.get("data") or {}, "verify")


# ── Effects (run inside the finalisation transaction) ───────────────────────
def _effect_trainer_activation(payment: Payment):
    profile = Profile.objects.select_for_update().get(user_id=payment.payer_id)
    if profile.has_paid and profile.payment_verified:
        return
    profile.has_paid = True
    profile.is_authorized = True
    profile.authorization_status = "approved"
    profile.authorized_at = now()
    profile.payment_verified = True
    profile.payment_reference = payment.reference
    profile.payment_verified_at = now()
    profile.save()
    payment.platform_fee_kobo = payment.expected_amount_kobo
    payment.save(update_fields=["platform_fee_kobo", "updated_at"])
    notify(payment.payer, "Trainer account activated",
           "Your payment was confirmed and your trainer account is active. You can now create courses.",
           reason="trainer_verified", link="/app/course-management", cta_label="Create a course")


def _effect_video_upload(payment: Payment):
    lesson = Lesson.objects.select_for_update().select_related("course").get(pk=payment.lesson_id)
    if lesson.video_upload_paid and lesson.video_upload_reference != payment.reference:
        # Paid twice for the same lesson: keep the money visible and flag it for a refund decision.
        payment.metadata = {**payment.metadata, "duplicate_of": lesson.video_upload_reference}
        payment.save(update_fields=["metadata", "updated_at"])
        notify_admins("Duplicate video upload payment",
                      f"Payment {payment.reference} duplicates {lesson.video_upload_reference} for lesson #{lesson.id}. "
                      "Consider a refund.", reason="payment_failed")
        return
    lesson.video_upload_paid = True
    lesson.video_upload_reference = payment.reference
    lesson.save(update_fields=["video_upload_paid", "video_upload_reference", "updated_at"])
    payment.platform_fee_kobo = payment.expected_amount_kobo
    payment.save(update_fields=["platform_fee_kobo", "updated_at"])
    notify(payment.payer, "Video upload unlocked",
           f"Payment confirmed. You can now upload the video for “{lesson.title}”.",
           reason="payment_success", link=course_link(lesson.course, lesson.id),
           cta_label="Upload video")


def _effect_lesson_access(payment: Payment):
    lesson = Lesson.objects.select_related("course", "course__trainer").get(pk=payment.lesson_id)
    access, _ = LessonAccess.objects.select_for_update().get_or_create(
        student_id=payment.payer_id, lesson=lesson,
        defaults={"status": "active", "source": "paystack"},
    )
    access.status = "active"
    access.source = "paystack"
    access.payment = payment
    access.payment_reference = payment.reference
    access.amount_paid = config.kobo_to_naira(payment.expected_amount_kobo)
    access.note = ""
    access.save()
    link = course_link(lesson.course, lesson.id)
    notify(payment.payer, "Lesson unlocked",
           f"Payment confirmed. “{lesson.title}” is now unlocked.", reason="payment_success",
           link=link, cta_label="Start lesson")
    if lesson.course.trainer:
        notify(lesson.course.trainer, "New lesson payment",
               f"{payment.payer.get_full_name() or payment.payer.email} paid "
               f"₦{config.kobo_to_naira(payment.expected_amount_kobo):,.2f} for “{lesson.title}”.",
               reason="payment_success", link="/app/earnings", cta_label="View earnings")


_EFFECTS = {
    "trainer_activation": _effect_trainer_activation,
    "video_upload": _effect_video_upload,
    "lesson_access": _effect_lesson_access,
}


# ── Webhook ──────────────────────────────────────────────────────────────────
def handle_webhook(body: bytes, signature: str):
    """→ (http_status, text). 401 bad signature; 200 for processed/duplicate/ignored; 500 → Paystack retries."""
    if not paystack.verify_signature(body, signature):
        logger.warning("Paystack webhook: invalid signature")
        return 401, "Invalid signature"
    try:
        event = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return 400, "Invalid payload"

    name = event.get("event", "")
    data = event.get("data") or {}
    reference = data.get("reference", "") or ""
    key = f"{name}:{data.get('id') or reference}"[:128]

    rec, created = WebhookEvent.objects.get_or_create(key=key, defaults={"event": name[:64], "reference": reference[:64]})
    if not created:
        WebhookEvent.objects.filter(pk=rec.pk).update(attempts=rec.attempts + 1)
        if rec.outcome in ("success", "pending", "failed", "abandoned", "mismatch", "ignored", "unknown_reference"):
            return 200, "OK (duplicate)"

    outcome = "ignored"
    try:
        if name == "charge.success" and reference:
            try:
                outcome = apply_gateway_result(reference, data, "webhook").state
            except PaymentError as exc:
                outcome = "unknown_reference" if exc.http_status == 404 else "error"
                if outcome == "error":
                    raise
    except Exception:
        logger.exception("Webhook processing failed for %s", key)
        WebhookEvent.objects.filter(pk=rec.pk).update(outcome="error")
        return 500, "Processing error"
    WebhookEvent.objects.filter(pk=rec.pk).update(outcome=outcome)
    return 200, "OK"


def resolve_mismatch(reference: str, approve: bool, admin_user, note: str = "") -> Payment:
    """Dunis Admin final decision on a payment that was paid but failed automatic validation."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(reference=reference)
        if payment.status != "mismatch":
            raise PaymentError("Only payments flagged for review can be resolved.", 400)
        payment.metadata = {**payment.metadata, "resolved_by": admin_user.id, "resolution_note": note[:300],
                            "resolved_at": now().isoformat(), "approved": approve}
        if approve:
            payment.status = "success"
            payment.verified_at = now()
            payment.save()
            _EFFECTS[payment.payment_type](payment)
        else:
            payment.status = "failed"
            payment.save()
            if payment.payer:
                notify(payment.payer, "Payment not accepted",
                       "After review your payment could not be accepted. Contact support for a refund.",
                       reason="payment_failed", link=f"/app/payment/callback?reference={reference}")
    return payment
