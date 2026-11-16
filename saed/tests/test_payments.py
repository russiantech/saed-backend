import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from ..models import Lesson, LessonAccess, Payment, PlatformSetting, Profile, WebhookEvent
from ..services import config, paystack
from ..services import payments as svc
from .helpers import (gateway_success, login, mk_course, mk_lesson, mk_user, mp4, pdf, post, patch as jpatch, sign)

SECRET = "sk_test_secret"


class AmountCheckTests(TestCase):
    """The reported bug: Paid 2548224 vs Expected 2500000."""

    def test_fee_inclusive_amount_matches_requested_amount(self):
        data = {"amount": 2548224, "fees": 48224, "requested_amount": 2500000}
        ok, detail = paystack.check_amount(data, 2500000)
        self.assertTrue(ok, detail)

    def test_wrong_requested_amount_rejected(self):
        ok, _ = paystack.check_amount({"amount": 2548224, "fees": 48224, "requested_amount": 2400000}, 2500000)
        self.assertFalse(ok)

    def test_underpayment_rejected_no_tolerance(self):
        ok, _ = paystack.check_amount({"amount": 2499999, "requested_amount": 2499999}, 2500000)
        self.assertFalse(ok)
        ok, _ = paystack.check_amount({"amount": 2499999}, 2500000)
        self.assertFalse(ok)

    def test_without_requested_amount_exact_or_fee_adjusted_only(self):
        self.assertTrue(paystack.check_amount({"amount": 2500000}, 2500000)[0])
        self.assertTrue(paystack.check_amount({"amount": 2548224, "fees": 48224}, 2500000)[0])
        self.assertFalse(paystack.check_amount({"amount": 2548224, "fees": 100}, 2500000)[0])   # no 5% fudge

    def test_naira_to_kobo_is_decimal_safe(self):
        self.assertEqual(config.naira_to_kobo("19.99"), 1999)
        self.assertEqual(config.naira_to_kobo(0.1 + 0.2), 30)
        self.assertEqual(config.naira_to_kobo("25000.00"), 2500000)

    def test_signature(self):
        with override_settings(PAYSTACK_SECRET_KEY=SECRET):
            body = b'{"a":1}'
            self.assertTrue(paystack.verify_signature(body, sign(SECRET, body)))
            self.assertFalse(paystack.verify_signature(body, "bad"))
            self.assertFalse(paystack.verify_signature(body, ""))


@override_settings(PAYSTACK_SECRET_KEY=SECRET, PAYSTACK_PUBLIC_KEY="pk_test_x")
class LessonPaymentTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("trainer@x.com", "trainer", bank_verified=True, paystack_subaccount_code="ACCT_abc")
        self.student = mk_user("student@x.com", "corps_member")
        self.other = mk_user("other@x.com", "corps_member")
        self.course = mk_course(self.trainer)
        self.lesson = mk_lesson(self.course, title="Premium", price="25000.00", is_locked=True)
        from ..models import CourseEnrollment
        CourseEnrollment.objects.create(student=self.student, course=self.course, status="confirmed")
        CourseEnrollment.objects.create(student=self.other, course=self.course, status="confirmed")
        self.c = login(self.student)
        self.dunis_user = mk_user("dunis0@x.com", "dunis_admin")

    def _init(self, client=None):
        with patch("saed.services.paystack.initialize_transaction") as init:
            init.return_value = {"status": True, "data": {"access_code": "AC1", "authorization_url": "https://pay/x"}}
            r = post(client or self.c, "/api/payments/lesson/", {"lessonId": self.lesson.id})
        return r, init

    def _verify(self, ref, data, client=None):
        with patch("saed.services.paystack.verify_transaction") as v:
            v.return_value = {"status": True, "data": data}
            return post(client or self.c, "/api/payments/verify/", {"reference": ref})

    def test_initialize_records_split_and_uses_subaccount(self):
        r, init = self._init()
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertEqual(body["amountKobo"], 2500000)
        self.assertEqual(body["accessCode"], "AC1")
        self.assertEqual(body["publicKey"], "pk_test_x")
        p = Payment.objects.get(reference=body["reference"])
        self.assertEqual((p.platform_fee_kobo, p.trainer_share_kobo), (250000, 2250000))   # default 10 %
        kwargs = init.call_args.kwargs
        self.assertEqual(kwargs["subaccount"], "ACCT_abc")
        self.assertEqual(kwargs["transaction_charge_kobo"], 250000)
        self.assertEqual(p.payer, self.student)
        self.assertEqual(p.trainer, self.trainer)

    def test_repeated_initialize_reuses_pending_payment(self):
        self._init()
        r, _ = self._init()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Payment.objects.filter(payment_type="lesson_access").count(), 1)

    def test_success_with_gateway_fee_included_unlocks_lesson(self):
        ref = self._init()[0].json()["reference"]
        data = gateway_success(ref, 2500000, "student@x.com", fees=48224, bearer_fees=True)
        self.assertEqual(data["amount"], 2548224)
        r = self._verify(ref, data)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["status"], "success")
        acc = LessonAccess.objects.get(student=self.student, lesson=self.lesson)
        self.assertEqual((acc.status, acc.source, acc.payment_reference), ("active", "paystack", ref))
        p = Payment.objects.get(reference=ref)
        self.assertEqual((p.status, p.paid_amount_kobo, p.requested_amount_kobo, p.gateway_fees_kobo),
                         ("success", 2548224, 2500000, 48224))
        # learner can now see the content; trainer was notified
        self.assertTrue(self.student.notifications.filter(reason="payment_success").exists())
        self.assertTrue(self.trainer.notifications.filter(reason="payment_success").exists())

    def test_verifying_twice_is_idempotent_and_never_reports_failure(self):
        ref = self._init()[0].json()["reference"]
        data = gateway_success(ref, 2500000, "student@x.com")
        first, second = self._verify(ref, data), self._verify(ref, data)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(second.json()["status"], "success")
        self.assertTrue(second.json()["alreadyProcessed"])
        self.assertEqual(LessonAccess.objects.filter(student=self.student, lesson=self.lesson).count(), 1)
        self.assertEqual(self.student.notifications.filter(reason="payment_success").count(), 1)

    def test_amount_mismatch_does_not_unlock_and_flags_for_review(self):
        ref = self._init()[0].json()["reference"]
        r = self._verify(ref, gateway_success(ref, 100000, "student@x.com"))   # paid ₦1,000 instead of ₦25,000
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["status"], "mismatch")
        self.assertFalse(LessonAccess.objects.filter(student=self.student, status="active").exists())
        self.assertEqual(Payment.objects.get(reference=ref).status, "mismatch")
        self.assertTrue(self.dunis_user.notifications.filter(reason="payment_failed").exists())

    def test_currency_and_customer_and_reference_mismatch(self):
        for mod in ({"currency": "USD"}, {"customer": {"email": "someone@else.com"}}, {"reference": "WRONG"}):
            Payment.objects.all().delete()
            ref = self._init()[0].json()["reference"]
            data = gateway_success(ref, 2500000, "student@x.com")
            data.update(mod)
            r = self._verify(ref, data)
            self.assertEqual(r.status_code, 409, mod)
            self.assertFalse(LessonAccess.objects.filter(status="active").exists(), mod)

    def test_pending_failed_abandoned_states(self):
        ref = self._init()[0].json()["reference"]
        r = self._verify(ref, {"status": "ongoing", "reference": ref})
        self.assertEqual((r.status_code, r.json()["status"], r.json()["ok"]), (200, "pending", False))
        r = self._verify(ref, {"status": "abandoned", "reference": ref})
        self.assertEqual(r.json()["status"], "abandoned")
        r = self._verify(ref, {"status": "failed", "reference": ref, "gateway_response": "Declined"})
        self.assertEqual(r.json()["status"], "failed")
        # an abandoned/failed payment may still succeed later
        r = self._verify(ref, gateway_success(ref, 2500000, "student@x.com"))
        self.assertEqual(r.json()["status"], "success")

    def test_unknown_reference_and_other_users_reference(self):
        r = post(self.c, "/api/payments/verify/", {"reference": "NOPE"})
        self.assertEqual(r.status_code, 404)
        ref = self._init()[0].json()["reference"]
        r = self._verify(ref, gateway_success(ref, 2500000, "student@x.com"), client=login(self.other))
        self.assertEqual(r.status_code, 404)
        self.assertFalse(LessonAccess.objects.filter(status="active").exists())

    def test_gateway_unreachable_returns_502_not_failure(self):
        ref = self._init()[0].json()["reference"]
        with patch("saed.services.paystack.verify_transaction", side_effect=paystack.PaystackError("down")):
            r = post(self.c, "/api/payments/verify/", {"reference": ref})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(Payment.objects.get(reference=ref).status, "pending")

    def test_free_unenrolled_and_already_unlocked_rejected(self):
        free = mk_lesson(self.course, title="free", order=2)
        r = post(self.c, "/api/payments/lesson/", {"lessonId": free.id})
        self.assertEqual(r.status_code, 400)
        outsider = mk_user("out@x.com", "corps_member")
        r = post(login(outsider), "/api/payments/lesson/", {"lessonId": self.lesson.id})
        self.assertEqual(r.status_code, 403)
        LessonAccess.objects.create(student=self.student, lesson=self.lesson, status="active")
        self.assertEqual(self._init()[0].status_code, 400)

    def test_trainer_cannot_pay_for_lesson_and_failed_init_marks_failed(self):
        r = post(login(self.trainer), "/api/payments/lesson/", {"lessonId": self.lesson.id})
        self.assertEqual(r.status_code, 403)
        with patch("saed.services.paystack.initialize_transaction", side_effect=paystack.PaystackError("x")):
            r = post(self.c, "/api/payments/lesson/", {"lessonId": self.lesson.id})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(Payment.objects.get().status, "failed")

    # ── webhook ──────────────────────────────────────────────────────────
    def _webhook(self, payload, sig=None):
        body = json.dumps(payload).encode()
        return self.client.post("/api/webhooks/paystack/", data=body, content_type="application/json",
                                HTTP_X_PAYSTACK_SIGNATURE=sig if sig is not None else sign(SECRET, body))

    def test_webhook_signature_required(self):
        ref = self._init()[0].json()["reference"]
        payload = {"event": "charge.success", "data": gateway_success(ref, 2500000, "student@x.com")}
        self.assertEqual(self._webhook(payload, sig="bad").status_code, 401)
        self.assertEqual(self._webhook(payload, sig="").status_code, 401)
        self.assertFalse(LessonAccess.objects.exists())

    def test_webhook_unlocks_and_retries_are_idempotent(self):
        ref = self._init()[0].json()["reference"]
        payload = {"event": "charge.success", "data": gateway_success(ref, 2500000, "student@x.com", fees=48224, bearer_fees=True)}
        for _ in range(3):                                     # Paystack retries
            self.assertEqual(self._webhook(payload).status_code, 200)
        self.assertEqual(LessonAccess.objects.filter(status="active").count(), 1)
        ev = WebhookEvent.objects.get()
        self.assertEqual((ev.outcome, ev.attempts), ("success", 3))
        # verify endpoint after webhook: still success, not failure
        r = post(self.c, "/api/payments/verify/", {"reference": ref})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "success"))

    def test_webhook_wrong_amount_not_granted_unknown_ref_and_other_events_ok(self):
        ref = self._init()[0].json()["reference"]
        self._webhook({"event": "charge.success", "data": gateway_success(ref, 500, "student@x.com", tx_id=7)})
        self.assertFalse(LessonAccess.objects.exists())
        self.assertEqual(Payment.objects.get(reference=ref).status, "mismatch")
        r = self._webhook({"event": "charge.success", "data": gateway_success("UNKNOWN", 1, "a@b.c", tx_id=8)})
        self.assertEqual(r.status_code, 200)
        r = self._webhook({"event": "transfer.success", "data": {"reference": ref, "id": 9}})
        self.assertEqual(r.status_code, 200)

    def test_dunis_can_resolve_mismatch(self):
        ref = self._init()[0].json()["reference"]
        self._verify(ref, gateway_success(ref, 100, "student@x.com"))
        dunis = login(mk_user("dunis@x.com", "dunis_admin"))
        r = post(dunis, f"/api/dunis/payments/{ref}/resolve/", {"action": "approve", "note": "checked bank"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(LessonAccess.objects.filter(student=self.student, status="active").exists())
        r = post(dunis, f"/api/dunis/payments/{ref}/resolve/", {"action": "approve"})
        self.assertEqual(r.status_code, 400)                    # cannot resolve twice
        r = post(login(self.trainer), f"/api/dunis/payments/{ref}/resolve/", {"action": "approve"})
        self.assertEqual(r.status_code, 403)


@override_settings(PAYSTACK_SECRET_KEY=SECRET, PAYSTACK_PUBLIC_KEY="pk_test_x")
class VideoUploadFeeTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("trainer@x.com", "trainer")
        self.course = mk_course(self.trainer)
        self.l1 = mk_lesson(self.course, title="One", content_type="video")
        self.l2 = mk_lesson(self.course, title="Two", content_type="video", order=2)
        self.c = login(self.trainer)

    def _pay(self, lesson):
        with patch("saed.services.paystack.initialize_transaction") as init:
            init.return_value = {"status": True, "data": {"access_code": "AC", "authorization_url": "u"}}
            r = post(self.c, "/api/payments/video-upload/", {"lessonId": lesson.id})
        self.assertEqual(r.status_code, 200, r.content)
        ref = r.json()["reference"]
        with patch("saed.services.paystack.verify_transaction") as v:
            v.return_value = {"status": True, "data": gateway_success(ref, r.json()["amountKobo"], "trainer@x.com", fees=3000, bearer_fees=True)}
            return post(self.c, "/api/payments/verify/", {"reference": ref}), r.json()

    def test_default_fee_is_2000_and_configurable_not_hardcoded(self):
        self.assertEqual(config.video_upload_fee()["amountKobo"], 200000)
        PlatformSetting.set(config.KEY_VIDEO_FEE, {"amount": 3500.5, "enabled": True})
        self.assertEqual(config.video_upload_fee()["amountKobo"], 350050)

    def test_video_upload_blocked_until_fee_paid_then_works_for_that_lesson_only(self):
        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["requiresVideoUploadPayment"])
        self.assertEqual(r.json()["feeAmount"], 2000.0)

        verify, init = self._pay(self.l1)
        self.assertEqual(verify.json()["status"], "success")
        self.l1.refresh_from_db()
        self.assertTrue(self.l1.video_upload_paid)

        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 200, r.content)
        self.l1.refresh_from_db()
        self.assertTrue(self.l1.video_file.name)
        self.assertEqual(self.l1.content_type, "video")
        # a different lesson is NOT unlocked by that payment
        r = self.c.post(f"/api/manage/lessons/{self.l2.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 402)
        # fee recorded against trainer + lesson + course, as platform revenue
        p = Payment.objects.get(payment_type="video_upload")
        self.assertEqual((p.payer, p.lesson, p.course, p.platform_fee_kobo), (self.trainer, self.l1, self.course, 200000))

    def test_documents_and_text_are_free(self):
        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "document", "file": pdf()})
        self.assertEqual(r.status_code, 200, r.content)
        r = jpatch(self.c, f"/api/manage/lessons/{self.l1.id}/", {"textContent": "hello"})
        self.assertEqual(r.status_code, 200)

    def test_external_video_link_also_requires_fee(self):
        r = jpatch(self.c, f"/api/manage/lessons/{self.l1.id}/", {"videoLink": "https://youtu.be/x"})
        self.assertEqual(r.status_code, 402)

    def test_disabled_fee_allows_upload_and_blocks_initialisation(self):
        PlatformSetting.set(config.KEY_VIDEO_FEE, {"amount": 2000, "enabled": False})
        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 200, r.content)
        r = post(self.c, "/api/payments/video-upload/", {"lessonId": self.l2.id})
        self.assertEqual(r.status_code, 400)

    def test_upload_validation_and_ownership(self):
        PlatformSetting.set(config.KEY_VIDEO_FEE, {"amount": 2000, "enabled": False})
        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4("evil.mp4", b"<html>not a video</html>" * 10)})
        self.assertEqual(r.status_code, 400)
        r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4("x.exe")})
        self.assertEqual(r.status_code, 400)
        with override_settings(SAED_MAX_VIDEO_BYTES=1000):
            r = self.c.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4()})
            self.assertEqual(r.status_code, 400)
            self.assertIn("too large", r.json()["error"])
        other = login(mk_user("t2@x.com", "trainer"))
        r = other.post(f"/api/manage/lessons/{self.l1.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 404)

    def test_generic_media_endpoint_rejects_videos_and_documents(self):
        for f in (mp4(), pdf()):
            r = self.c.post("/api/media/upload/", {"file": f})
            self.assertEqual(r.status_code, 400)

    def test_cannot_pay_for_other_trainers_lesson(self):
        other = login(mk_user("t2@x.com", "trainer"))
        r = post(other, "/api/payments/video-upload/", {"lessonId": self.l1.id})
        self.assertEqual(r.status_code, 404)

    def test_trainer_activation_via_unified_service(self):
        t = mk_user("new@x.com", "trainer", has_paid=False, payment_verified=False, is_authorized=True)
        c = login(t)
        with patch("saed.services.paystack.initialize_transaction") as init:
            init.return_value = {"status": True, "data": {"access_code": "AC", "authorization_url": "u"}}
            r = post(c, "/api/paystack/initialize/", {})
        self.assertEqual(r.status_code, 200, r.content)
        ref = r.json()["reference"]
        self.assertEqual(r.json()["amountKobo"], 50000)
        with patch("saed.services.paystack.verify_transaction") as v:
            v.return_value = {"status": True, "data": gateway_success(ref, 50000, "new@x.com", fees=1200, bearer_fees=True)}
            r = post(c, "/api/paystack/trainer-verify/", {"reference": ref})
        self.assertEqual(r.status_code, 200, r.content)
        t.profile.refresh_from_db()
        self.assertTrue(t.profile.has_paid and t.profile.payment_verified)
