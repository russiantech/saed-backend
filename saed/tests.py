import datetime
import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import Connection, Course, CourseEnrollment, Profile, Module, Lesson, LessonProgress, AdminInvitation


def post_json(client, path, payload):
    return client.post(path, data=json.dumps(payload), content_type="application/json")


def patch_json(client, path, payload):
    return client.patch(path, data=json.dumps(payload), content_type="application/json")


class SaedApiTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user("member@example.com", "member@example.com", "Password123!")
        Profile.objects.create(user=self.member, role="corps_member", phone="0800")
        self.trainer = User.objects.create_user("trainer@example.com", "trainer@example.com", "Password123!")
        Profile.objects.create(user=self.trainer, role="trainer", is_authorized=True, has_paid=True, payment_verified=True)
        self.other_trainer = User.objects.create_user("other-trainer@example.com", "other-trainer@example.com", "Password123!")
        Profile.objects.create(user=self.other_trainer, role="trainer", is_authorized=True, has_paid=True, payment_verified=True)
        self.admin = User.objects.create_user("admin@example.com", "admin@example.com", "Password123!")
        Profile.objects.create(user=self.admin, role="saed_admin", is_email_verified=True)
        self.dunis_admin = User.objects.create_user("dunis@example.com", "dunis@example.com", "Password123!")
        Profile.objects.create(user=self.dunis_admin, role="dunis_admin", is_email_verified=True)
        self.pending_trainer = User.objects.create_user("pending-trainer@example.com", "pending-trainer@example.com", "Password123!")
        Profile.objects.create(user=self.pending_trainer, role="trainer", is_authorized=False, has_paid=False, authorization_status="pending", is_email_verified=True)
        self.program = Course.objects.create(
            title="ICT Skills",
            category="ict",
            description="Digital skills",
            duration_weeks=4,
            max_students=20,
            trainer=self.trainer,
            location="Lagos",
        )
        self.other_program = Course.objects.create(
            title="Food Skills",
            category="food_processing",
            description="Food business skills",
            duration_weeks=6,
            max_students=10,
            trainer=self.other_trainer,
            location="Abuja",
        )
        self.application = CourseEnrollment.objects.create(student=self.member, course=self.program)
        self.other_application = CourseEnrollment.objects.create(student=self.admin, course=self.other_program)

    def login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_trainer_can_update_application_status(self):
        client = self.login(self.trainer)
        response = patch_json(client, f"/api/manage/applications/{self.application.id}/", {"status": "approved"})

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "confirmed")

    def test_member_cannot_manage_applications(self):
        client = self.login(self.member)
        response = client.get("/api/manage/applications/")

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_create_trainer_via_api(self):
        client = self.login(self.admin)
        response = post_json(
            client,
            "/api/manage/users/",
            {
                "fullName": "New Trainer",
                "email": "new-trainer@example.com",
                "role": "trainer",
                "password": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 405)

    def test_admin_cannot_create_admin_account(self):
        client = self.login(self.admin)
        response = post_json(
            client,
            "/api/manage/users/",
            {
                "fullName": "New Admin",
                "email": "new-admin@example.com",
                "role": "admin",
                "password": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 405)
        self.assertFalse(User.objects.filter(email="new-admin@example.com").exists())

    def test_public_signup_cannot_create_trainer_account(self):
        response = post_json(
            Client(),
            "/api/auth/signup/",
            {
                "fullName": "Public Trainer",
                "email": "public-trainer@example.com",
                "role": "trainer",
                "password": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="public-trainer@example.com").exists())

    def test_public_signup_cannot_create_admin_account(self):
        response = post_json(
            Client(),
            "/api/auth/signup/",
            {
                "fullName": "Public Admin",
                "email": "public-admin@example.com",
                "role": "admin",
                "password": "Password123!",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(User.objects.filter(email="public-admin@example.com").exists())

    def test_admin_cannot_apply_to_program(self):
        client = self.login(self.admin)
        response = post_json(
            client,
            "/api/applications/create/",
            {"programId": self.program.id, "motivation": "Admin should not apply."},
        )

        self.assertEqual(response.status_code, 403)

    def test_trainer_cannot_access_member_applications_endpoint(self):
        client = self.login(self.trainer)
        response = client.get("/api/applications/")

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_deactivate_self(self):
        client = self.login(self.admin)
        response = patch_json(client, f"/api/manage/users/{self.admin.id}/", {"isActive": False})

        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_login_does_not_require_role_selection(self):
        response = post_json(
            Client(),
            "/api/auth/login/",
            {"email": "admin@example.com", "password": "Password123!"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["role"], "saed_admin")

    def test_email_verification_rejects_already_verified(self):
        profile = Profile.objects.create(
            user=User.objects.create_user(
                "verify@example.com", "verify@example.com", "Password123!"
            ),
            role="corps_member",
            phone="0801",
            email_verification_code="123456",
        )

        client = Client()
        first = post_json(client, "/api/auth/verify-code/", {"email": "verify@example.com", "code": "123456"})
        self.assertEqual(first.status_code, 200)
        profile.refresh_from_db()
        self.assertTrue(profile.is_email_verified)

        second = post_json(client, "/api/auth/verify-code/", {"email": "verify@example.com", "code": "123456"})
        self.assertEqual(second.status_code, 400)
        self.assertIn("already verified", second.json().get("error", "").lower())
        self.assertTrue(profile.is_email_verified)

    @override_settings(PAYSTACK_SECRET_KEY="test_secret")
    @patch("saed.views.payments.http.client.HTTPSConnection")
    def test_course_payment_resumes_blank_pending_enrollment(self, mock_conn_cls):
        mock_conn = mock_conn_cls.return_value
        mock_response = mock_conn.getresponse.return_value
        mock_response.read.return_value = b'{"status": true, "data": {"authorization_url": "https://pay.example/checkout", "access_code": "access"}}'

        course = Course.objects.create(
            trainer=self.trainer,
            title="Paid Course",
            category="ict",
            price="1000.00",
        )
        enrollment = CourseEnrollment.objects.create(
            student=self.member, course=course, status="pending", payment_reference=""
        )
        Connection.objects.create(
            corps_member=self.member, trainer=self.trainer, status="active"
        )

        response = post_json(self.login(self.member), "/api/courses/pay/", {"courseId": course.id})

        self.assertEqual(response.status_code, 200)
        enrollment.refresh_from_db()
        self.assertTrue(enrollment.payment_reference.startswith("SAED-COURSE-"))

    def test_saed_admin_cannot_create_program(self):
        client = self.login(self.admin)
        response = post_json(
            client,
            "/api/manage/programs/",
            {
                "title": "Agro Enterprise",
                "category": "agro_allied",
                "description": "Farm business training",
                "durationWeeks": 6,
                "maxStudents": 30,
                "price": 0,
                "location": "Abuja",
                "startDate": "2026-10-01",
                "endDate": "2026-12-01",
                "isActive": True,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_dunis_admin_can_create_program(self):
        client = self.login(self.dunis_admin)
        response = post_json(
            client,
            "/api/manage/programs/",
            {
                "title": "Agro Enterprise Dunis",
                "category": "agro_allied",
                "description": "Farm business training",
                "durationWeeks": 6,
                "maxStudents": 30,
                "price": 0,
                "location": "Abuja",
                "startDate": "2026-10-01",
                "endDate": "2026-12-01",
                "isActive": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        program = Course.objects.get(title="Agro Enterprise Dunis")
        self.assertEqual(program.trainer, self.dunis_admin)

    def test_trainer_can_create_program(self):
        client = self.login(self.trainer)
        response = post_json(
            client,
            "/api/manage/programs/",
            {
                "title": "Agro Enterprise",
                "category": "agro_allied",
                "description": "Farm business training",
                "durationWeeks": 6,
                "maxStudents": 30,
                "price": 0,
                "location": "Abuja",
                "startDate": "2026-10-01",
                "endDate": "2026-12-01",
                "isActive": True,
            },
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(Course.objects.filter(title="Agro Enterprise", trainer=self.trainer).exists())

    def test_trainer_only_sees_own_programs(self):
        client = self.login(self.trainer)
        response = client.get("/api/manage/programs/")

        self.assertEqual(response.status_code, 200)
        program_ids = {item["id"] for item in response.json()["programs"]}
        self.assertIn(self.program.id, program_ids)
        self.assertNotIn(self.other_program.id, program_ids)

    def test_trainer_can_edit_own_program(self):
        client = self.login(self.trainer)
        response = patch_json(client, f"/api/manage/programs/{self.program.id}/", {"title": "Changed"})

        self.assertEqual(response.status_code, 200)
        self.program.refresh_from_db()
        self.assertEqual(self.program.title, "Changed")

    def test_trainer_only_sees_own_program_applications(self):
        client = self.login(self.trainer)
        response = client.get("/api/manage/applications/")

        self.assertEqual(response.status_code, 200)
        application_ids = {item["id"] for item in response.json()["applications"]}
        self.assertIn(self.application.id, application_ids)
        self.assertNotIn(self.other_application.id, application_ids)

    def test_trainer_cannot_update_other_trainers_application(self):
        client = self.login(self.trainer)
        response = patch_json(client, f"/api/manage/applications/{self.other_application.id}/", {"status": "approved"})

        self.assertEqual(response.status_code, 404)
        self.other_application.refresh_from_db()
        self.assertEqual(self.other_application.status, "pending")

    def test_trainer_dashboard_includes_own_program_applicants(self):
        client = self.login(self.trainer)
        response = client.get("/api/dashboard/")

        self.assertEqual(response.status_code, 200)
        programs = response.json()["trainerPrograms"]
        self.assertEqual([item["id"] for item in programs], [self.program.id])

    def test_signup_returns_field_errors(self):
        response = post_json(Client(), "/api/auth/signup/", {"fullName": "A", "email": "bad", "password": "123"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("fields", response.json())
        self.assertIn("email", response.json()["fields"])

    def test_password_reset_changes_password(self):
        client = Client()
        response = post_json(client, "/api/auth/forgot-password/", {"email": "member@example.com"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        token = payload["token"]

        profile = Profile.objects.get(user=self.member)
        code = profile.password_reset_code

        response = post_json(
            client,
            "/api/auth/reset-password/",
            {"email": "member@example.com", "token": token, "code": code, "password": "NewPassword123!"},
        )

        self.assertEqual(response.status_code, 200)
        self.member.refresh_from_db()
        self.assertTrue(self.member.check_password("NewPassword123!"))

    def test_trainer_cannot_change_completed_application(self):
        self.application.status = "completed"
        self.application.save(update_fields=["status"])

        client = self.login(self.trainer)
        response = patch_json(
            client,
            f"/api/manage/applications/{self.application.id}/",
            {"status": "approved"},
        )

        self.assertEqual(response.status_code, 400)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "completed")

    def test_admin_can_change_completed_application(self):
        self.application.status = "completed"
        self.application.save(update_fields=["status"])

        client = self.login(self.admin)
        response = patch_json(
            client,
            f"/api/manage/applications/{self.application.id}/",
            {"status": "approved"},
        )

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "confirmed")

    def test_pending_trainer_cannot_initialize_payment(self):
        client = self.login(self.pending_trainer)
        response = post_json(client, "/api/paystack/initialize/", {"email": self.pending_trainer.email})
        self.assertEqual(response.status_code, 400)
        self.assertIn("under review", response.json().get("error", "").lower())

    @override_settings(PAYSTACK_SECRET_KEY="test_secret")
    @patch("saed.views.payments.http.client.HTTPSConnection")
    def test_admin_approving_trainer_sends_email_and_enables_payment(self, mock_conn_cls):
        mock_conn = mock_conn_cls.return_value
        mock_response = mock_conn.getresponse.return_value
        mock_response.read.return_value = b'{"status": true, "data": {"authorization_url": "https://pay.example/checkout", "access_code": "access"}}'

        admin_client = self.login(self.admin)
        patch_res = patch_json(
            admin_client,
            f"/api/manage/users/{self.pending_trainer.id}/",
            {"authorizationStatus": "approved"},
        )
        self.assertEqual(patch_res.status_code, 200)
        self.pending_trainer.profile.refresh_from_db()
        self.assertTrue(self.pending_trainer.profile.is_authorized)
        self.assertEqual(self.pending_trainer.profile.authorization_status, "approved")

        # Now trainer should be able to initialize payment
        trainer_client = self.login(self.pending_trainer)
        pay_res = post_json(trainer_client, "/api/paystack/initialize/", {"email": self.pending_trainer.email})
        self.assertEqual(pay_res.status_code, 200)
        self.assertTrue(pay_res.json().get("ok"))
        self.assertEqual(pay_res.json().get("authorization_url"), "https://pay.example/checkout")

    def test_password_reset_brute_force_lockout(self):
        client = Client()
        res = post_json(client, "/api/auth/forgot-password/", {"email": "member@example.com"})
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]

        # Attempt 1-4 with invalid code
        for _ in range(4):
            fail_res = post_json(client, "/api/auth/verify-reset-code/", {
                "email": "member@example.com",
                "code": "000000",
                "token": token,
            })
            self.assertEqual(fail_res.status_code, 400)

        # 5th attempt triggers lockout
        lockout_res = post_json(client, "/api/auth/verify-reset-code/", {
            "email": "member@example.com",
            "code": "000000",
            "token": token,
        })
        self.assertEqual(lockout_res.status_code, 400)
        self.assertIn("invalidated", lockout_res.json().get("error", "").lower())

        self.member.profile.refresh_from_db()
        self.assertEqual(self.member.profile.password_reset_code, "")

    @override_settings(PAYSTACK_SECRET_KEY="test_secret")
    @patch("saed.views.payments.http.client.HTTPSConnection")
    def test_course_pay_refunded_enrollment_remains_pending(self, mock_conn_cls):
        mock_conn = mock_conn_cls.return_value
        mock_response = mock_conn.getresponse.return_value
        mock_response.read.return_value = b'{"status": true, "data": {"authorization_url": "https://pay.example/checkout", "access_code": "access"}}'

        paid_course = Course.objects.create(
            trainer=self.trainer,
            title="Refundable Paid Course",
            category="ict",
            price="2000.00",
        )
        Connection.objects.get_or_create(
            corps_member=self.member, trainer=self.trainer, defaults={"status": "active"}
        )
        enrollment = CourseEnrollment.objects.create(
            student=self.member, course=paid_course, status="refunded"
        )

        client = self.login(self.member)
        response = post_json(client, "/api/courses/pay/", {"courseId": paid_course.id})
        self.assertEqual(response.status_code, 200)

        enrollment.refresh_from_db()
        # Must be pending, NOT confirmed
        self.assertEqual(enrollment.status, "pending")

    def test_trainer_cannot_view_unconnected_corper_profile(self):
        client = self.login(self.other_trainer)
        # No connection exists between self.other_trainer and self.member
        response = client.get(f"/api/trainer/corpers/{self.member.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertIn("no connection exists", response.json().get("error", "").lower())

    def test_admin_can_manage_modules_and_lessons(self):
        client = self.login(self.admin)
        # Admin can view modules for any course
        res = client.get(f"/api/manage/modules/?courseId={self.program.id}")
        self.assertEqual(res.status_code, 200)

        # Admin can create a module on any course
        create_res = post_json(client, "/api/manage/modules/", {
            "courseId": self.program.id,
            "title": "Admin Created Module",
            "description": "Test",
        })
        self.assertEqual(create_res.status_code, 201)
        module_id = create_res.json()["module"]["id"]

        # Admin can create a lesson within that module
        lesson_res = post_json(client, "/api/manage/lessons/", {
            "moduleId": module_id,
            "title": "Admin Created Lesson",
            "contentType": "text",
            "textContent": "Hello",
        })
        self.assertEqual(lesson_res.status_code, 201)

    def test_clear_session_requires_post(self):
        client = Client()
        get_res = client.get("/api/auth/clear-session/")
        self.assertEqual(get_res.status_code, 405)

        post_res = client.post("/api/auth/clear-session/")
        self.assertEqual(post_res.status_code, 200)
        self.assertTrue(post_res.json().get("ok"))

    def test_trainee_can_request_refund_for_confirmed_course(self):
        self.application.status = "confirmed"
        self.application.save(update_fields=["status"])

        client = self.login(self.member)
        response = post_json(client, f"/api/courses/{self.program.id}/request-refund/", {
            "reason": "Relocated to another LGA for primary assignment.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("ok"))

        self.application.refresh_from_db()
        self.assertTrue(self.application.refund_requested)
        self.assertIn("Relocated to another LGA", self.application.refund_note)

    def test_trainee_cannot_request_duplicate_refund(self):
        self.application.status = "confirmed"
        self.application.refund_requested = True
        self.application.save(update_fields=["status", "refund_requested"])

        client = self.login(self.member)
        response = post_json(client, f"/api/courses/{self.program.id}/request-refund/", {
            "reason": "Another refund request.",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("already pending review", response.json().get("error", "").lower())

    def test_course_certificate_requires_completion(self):
        self.application.status = "confirmed"
        self.application.save(update_fields=["status"])

        mod = Module.objects.create(course=self.program, title="Module 1", order=1)
        Lesson.objects.create(module=mod, title="Lesson 1", content_type="text", text_content="Lesson", order=1)

        client = self.login(self.member)
        response = client.get(f"/api/courses/{self.program.id}/certificate/")
        self.assertEqual(response.status_code, 400)
        self.assertIn("not yet completed", response.json().get("error", "").lower())

    def test_course_certificate_success_when_100_percent(self):
        self.application.status = "confirmed"
        self.application.save(update_fields=["status"])

        mod = Module.objects.create(course=self.program, title="Module 1", order=1)
        lesson = Lesson.objects.create(module=mod, title="Lesson 1", content_type="text", text_content="Lesson", order=1)
        LessonProgress.objects.create(student=self.member, lesson=lesson)

        client = self.login(self.member)
        response = client.get(f"/api/courses/{self.program.id}/certificate/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("certificate", data)
        cert = data["certificate"]
        self.assertTrue(cert["certificateNumber"].startswith(f"NYSC-SAED-{self.program.id:04d}-"))
        self.assertEqual(cert["courseTitle"], self.program.title)
        self.assertEqual(cert["studentName"], self.member.email)


@override_settings(PAYSTACK_SECRET_KEY="test_secret_key")
class PaymentWebhookTests(TestCase):
    def setUp(self):
        self.trainer = User.objects.create_user("trainer@example.com", "trainer@example.com", "Password123!")
        Profile.objects.create(user=self.trainer, role="trainer", payment_reference="SAED-TEST123")
        self.member = User.objects.create_user("member@example.com", "member@example.com", "Password123!")
        Profile.objects.create(user=self.member, role="corps_member")
        self.course = Course.objects.create(
            title="Test Course", category="ict", trainer=self.trainer,
            price=50000, max_students=20,
        )
        self.enrollment = CourseEnrollment.objects.create(
            student=self.member, course=self.course,
            payment_reference="SAED-COURSE-TEST123", amount_paid=50000,
        )

    def _sign(self, body):
        return hmac.new(
            b"test_secret_key", body.encode(), hashlib.sha512
        ).hexdigest()

    def test_webhook_rejects_invalid_signature(self):
        client = Client()
        body = json.dumps({"event": "charge.success", "data": {}})
        response = client.post(
            "/api/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid_sig",
        )
        self.assertEqual(response.status_code, 400)

    def test_webhook_accepts_valid_signature(self):
        client = Client()
        body = json.dumps({"event": "charge.success", "data": {"reference": "SAED-TEST123", "metadata": {"type": "trainer_activation"}}})
        sig = self._sign(body)
        response = client.post(
            "/api/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 200)
        self.trainer.profile.refresh_from_db()
        self.assertTrue(self.trainer.profile.has_paid)

    def test_webhook_handles_course_payment(self):
        client = Client()
        body = json.dumps({"event": "charge.success", "data": {"reference": "SAED-COURSE-TEST123", "metadata": {"type": "course_payment"}}})
        sig = self._sign(body)
        response = client.post(
            "/api/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 200)
        self.enrollment.refresh_from_db()
        self.assertTrue(self.enrollment.payment_verified)
        self.assertEqual(self.enrollment.status, "confirmed")

    def test_webhook_ignores_non_success_events(self):
        client = Client()
        body = json.dumps({"event": "charge.failed", "data": {"reference": "SAED-TEST123"}})
        sig = self._sign(body)
        response = client.post(
            "/api/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 200)
        self.trainer.profile.refresh_from_db()
        self.assertFalse(self.trainer.profile.has_paid)

    def test_webhook_idempotent_for_already_processed(self):
        self.trainer.profile.has_paid = True
        self.trainer.profile.save(update_fields=["has_paid"])
        client = Client()
        body = json.dumps({"event": "charge.success", "data": {"reference": "SAED-TEST123", "metadata": {"type": "trainer_activation"}}})
        sig = self._sign(body)
        response = client.post(
            "/api/webhooks/paystack/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=sig,
        )
        self.assertEqual(response.status_code, 200)


class AdminInvitationTests(TestCase):
    def setUp(self):
        self.superadmin = User.objects.create_user("super@example.com", "super@example.com", "Password123!")
        Profile.objects.create(user=self.superadmin, role="dunis_admin", is_email_verified=True)
        self.saed_admin = User.objects.create_user("saed@example.com", "saed@example.com", "Password123!")
        Profile.objects.create(user=self.saed_admin, role="saed_admin", is_email_verified=True)
        self.member = User.objects.create_user("member@example.com", "member@example.com", "Password123!")
        Profile.objects.create(user=self.member, role="corps_member", is_email_verified=True)

    def login(self, user):
        client = Client()
        client.force_login(user)
        return client

    @patch("saed.views.base._send_email_async")
    def test_admin_can_generate_and_email_20_char_invitation(self, mock_email):
        client = self.login(self.superadmin)
        res = post_json(
            client,
            "/api/manage/admin-invitations/",
            {"email": "newadmin@example.com", "role": "saed_admin"},
        )
        self.assertEqual(res.status_code, 201)
        data = res.json()
        inv_data = data["invitation"]
        secret_key = inv_data["secretKey"]

        # Verify key length is strictly 20 characters
        self.assertEqual(len(secret_key), 20)

        # Verify database record
        inv = AdminInvitation.objects.get(secret_key=secret_key)
        self.assertEqual(inv.email, "newadmin@example.com")
        self.assertEqual(inv.role, "saed_admin")
        self.assertFalse(inv.is_used)
        self.assertFalse(inv.is_expired)

        # Verify 10-minute expiry window (approx 600s)
        time_diff = (inv.expires_at - inv.created_at).total_seconds()
        self.assertAlmostEqual(time_diff, 600, delta=15)

        # Verify email dispatch was triggered
        self.assertTrue(mock_email.called)
        call_kwargs = mock_email.call_args[1]
        self.assertIn("newadmin@example.com", call_kwargs.get("recipient_list", []))
        self.assertIn(secret_key, call_kwargs.get("html_message", ""))

    def test_intended_admin_can_signup_with_20_char_key(self):
        # Create an active invitation
        inv = AdminInvitation.objects.create(
            email="brandnewadmin@example.com",
            role="saed_admin",
            secret_key="A1B2C3D4E5F6G7H8J9K2",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

        client = Client()
        res = post_json(
            client,
            "/api/auth/admin-signup/",
            {
                "fullName": "Brand New Admin",
                "username": "brandnewadmin",
                "email": "brandnewadmin@example.com",
                "password": "SecurePassword123!",
                "secret": "A1B2C3D4E5F6G7H8J9K2",
            },
        )
        self.assertEqual(res.status_code, 201)

        # Verify user and profile
        user = User.objects.get(email="brandnewadmin@example.com")
        self.assertEqual(user.profile.role, "saed_admin")
        self.assertTrue(user.profile.is_email_verified)

        # Verify invitation marked as used
        inv.refresh_from_db()
        self.assertTrue(inv.is_used)
        self.assertEqual(inv.used_by, user)
        self.assertIsNotNone(inv.used_at)

    def test_expired_20_char_key_rejected(self):
        # Invitation expired 1 minute ago
        inv = AdminInvitation.objects.create(
            email="expiredadmin@example.com",
            role="saed_admin",
            secret_key="EXPIRED1234567890ABC",
            expires_at=timezone.now() - datetime.timedelta(minutes=1),
        )

        client = Client()
        res = post_json(
            client,
            "/api/auth/admin-signup/",
            {
                "fullName": "Expired Admin",
                "username": "expiredadmin",
                "email": "expiredadmin@example.com",
                "password": "SecurePassword123!",
                "secret": "EXPIRED1234567890ABC",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("expired", res.json().get("error", "").lower())

    def test_used_key_cannot_be_reused(self):
        inv = AdminInvitation.objects.create(
            email="usedadmin@example.com",
            role="saed_admin",
            secret_key="USED1234567890ABCDEF",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
            is_used=True,
        )

        client = Client()
        res = post_json(
            client,
            "/api/auth/admin-signup/",
            {
                "fullName": "Second Admin",
                "username": "secondadmin",
                "email": "usedadmin@example.com",
                "password": "SecurePassword123!",
                "secret": "USED1234567890ABCDEF",
            },
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("already been used", res.json().get("error", "").lower())

    def test_mismatched_email_rejected(self):
        inv = AdminInvitation.objects.create(
            email="intended@example.com",
            role="saed_admin",
            secret_key="INTENDED1234567890AB",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

        client = Client()
        res = post_json(
            client,
            "/api/auth/admin-signup/",
            {
                "fullName": "Imposter Admin",
                "username": "imposteradmin",
                "email": "imposter@example.com",
                "password": "SecurePassword123!",
                "secret": "INTENDED1234567890AB",
            },
        )
        self.assertEqual(res.status_code, 400)

    def test_regular_user_cannot_invite_admin(self):
        client = self.login(self.member)
        res = post_json(
            client,
            "/api/manage/admin-invitations/",
            {"email": "hack@example.com", "role": "saed_admin"},
        )
        self.assertEqual(res.status_code, 403)

    def test_saed_admin_cannot_invite_admin(self):
        client = self.login(self.saed_admin)
        res = post_json(
            client,
            "/api/manage/admin-invitations/",
            {"email": "forbidden@example.com", "role": "saed_admin"},
        )
        self.assertEqual(res.status_code, 403)

    def test_admin_can_revoke_invitation(self):
        inv = AdminInvitation.objects.create(
            email="revokeme@example.com",
            role="saed_admin",
            secret_key="REVOKE1234567890ABCD",
            expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )
        client = self.login(self.superadmin)
        res = client.delete(f"/api/manage/admin-invitations/{inv.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(AdminInvitation.objects.filter(id=inv.id).exists())

    @patch("saed.views.base._send_email_async")
    def test_resend_admin_key(self, mock_email):
        inv = AdminInvitation.objects.create(
            email="resendme@example.com",
            role="saed_admin",
            secret_key="RESEND1234567890ABCD",
            expires_at=timezone.now() + datetime.timedelta(minutes=2),
        )
        # Advance updated_at past the 60-second cooldown
        AdminInvitation.objects.filter(id=inv.id).update(
            updated_at=timezone.now() - datetime.timedelta(seconds=65)
        )
        client = Client()
        res = post_json(
            client,
            "/api/auth/resend-admin-key/",
            {"email": "resendme@example.com"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(mock_email.called)
        inv.refresh_from_db()
        # Verify expiry was renewed to ~10 minutes
        time_left = (inv.expires_at - timezone.now()).total_seconds()
        self.assertGreater(time_left, 500)

        # Immediate follow-up request within 60s must trigger 429 cooldown
        res_repeat = post_json(
            client,
            "/api/auth/resend-admin-key/",
            {"email": "resendme@example.com"},
        )
        self.assertEqual(res_repeat.status_code, 429)

        # Uninvited email returns generic 200 (no user enumeration)
        res_unknown = post_json(
            client,
            "/api/auth/resend-admin-key/",
            {"email": "unknown@example.com"},
        )
        self.assertEqual(res_unknown.status_code, 200)


class SecurityVulnerabilityTests(TestCase):
    def setUp(self):
        self.dunis_admin = User.objects.create_user("super@example.com", "super@example.com", "SuperPassword123!")
        Profile.objects.create(user=self.dunis_admin, role="dunis_admin", is_email_verified=True)

        self.saed_admin = User.objects.create_user("saed@example.com", "saed@example.com", "SaedPassword123!")
        Profile.objects.create(user=self.saed_admin, role="saed_admin", is_email_verified=True)

        self.trainer = User.objects.create_user("trainer@example.com", "trainer@example.com", "TrainerPassword123!")
        self.trainer_profile = Profile.objects.create(
            user=self.trainer, role="trainer", is_authorized=True, has_paid=True,
            can_upload_fast_track=False, is_email_verified=True
        )

        self.client = Client()

    def login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_finding_1_saed_admin_cannot_demote_or_tamper_with_admin(self):
        client = self.login(self.saed_admin)

        # Attempt to demote dunis_admin
        res = patch_json(client, f"/api/manage/users/{self.dunis_admin.id}/", {"role": "trainer"})
        self.assertEqual(res.status_code, 403)
        self.dunis_admin.profile.refresh_from_db()
        self.assertEqual(self.dunis_admin.profile.role, "dunis_admin")

        # Attempt to tamper with dunis_admin details
        res = patch_json(client, f"/api/manage/users/{self.dunis_admin.id}/", {"fullName": "Hacked Name"})
        self.assertEqual(res.status_code, 403)

        # Attempt to grant fast track as saed_admin
        res = patch_json(client, f"/api/manage/users/{self.trainer.id}/", {"canUploadFastTrack": True})
        self.assertEqual(res.status_code, 403)
        self.trainer_profile.refresh_from_db()
        self.assertFalse(self.trainer_profile.can_upload_fast_track)

        # Dunis admin cannot demote admin accounts to trainer via this endpoint
        dunis_client = self.login(self.dunis_admin)
        res = patch_json(dunis_client, f"/api/manage/users/{self.saed_admin.id}/", {"role": "trainer"})
        self.assertEqual(res.status_code, 400)
        self.saed_admin.profile.refresh_from_db()
        self.assertEqual(self.saed_admin.profile.role, "saed_admin")

    def test_finding_2_trainer_fast_track_paywall_enforcement(self):
        trainer_client = self.login(self.trainer)

        # Trainer without can_upload_fast_track tries to create course with hasFastTrack=True
        res = post_json(
            trainer_client,
            "/api/manage/programs/",
            {
                "title": "Bypassed Course",
                "category": "ict",
                "price": 5000,
                "startDate": "2026-11-01",
                "endDate": "2026-12-01",
                "hasFastTrack": True,
            },
        )
        self.assertEqual(res.status_code, 403)

        # Create normal course via /api/manage/programs/
        res = post_json(
            trainer_client,
            "/api/manage/programs/",
            {
                "title": "Legit Course",
                "category": "ict",
                "price": 5000,
                "startDate": "2026-11-01",
                "endDate": "2026-12-01",
                "hasFastTrack": False,
            },
        )
        self.assertEqual(res.status_code, 201)
        course_id = (res.json().get("program") or res.json().get("course"))["id"]

        # Trainer tries to update existing course with hasFastTrack=True
        res = patch_json(trainer_client, f"/api/manage/programs/{course_id}/", {"hasFastTrack": True})
        self.assertEqual(res.status_code, 403)

        # Also test /api/manage/courses/ creation without fast track
        res_courses = post_json(
            trainer_client,
            "/api/manage/courses/",
            {
                "title": "Bypassed Course 2",
                "category": "ict",
                "price": 5000,
                "startDate": "2026-11-01",
                "endDate": "2026-12-01",
                "hasFastTrack": True,
            },
        )
        self.assertEqual(res_courses.status_code, 403)

        # Now grant fast track to trainer and verify update succeeds
        self.trainer_profile.can_upload_fast_track = True
        self.trainer_profile.save(update_fields=["can_upload_fast_track"])

        res = patch_json(trainer_client, f"/api/manage/programs/{course_id}/", {"hasFastTrack": True})
        self.assertEqual(res.status_code, 200)
        updated_data = res.json().get("program") or res.json().get("course")
        self.assertTrue(updated_data["hasFastTrack"])

    def test_finding_3_email_verification_brute_force_lockout(self):
        user = User.objects.create_user("verifyvictim@example.com", "verifyvictim@example.com", "Victim123!")
        profile = Profile.objects.create(
            user=user,
            role="corps_member",
            email_verification_code="123456",
            email_verification_code_at=timezone.now(),
            email_verification_attempts=0,
            is_email_verified=False,
        )

        client = Client()

        # 4 invalid attempts: returns 400 with attempts remaining
        for attempt in range(1, 5):
            res = post_json(client, "/api/auth/verify-code/", {"email": user.email, "code": "999999"})
            self.assertEqual(res.status_code, 400)
            profile.refresh_from_db()
            self.assertEqual(profile.email_verification_attempts, attempt)

        # 5th invalid attempt: invalidates the code
        res = post_json(client, "/api/auth/verify-code/", {"email": user.email, "code": "999999"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("invalidated", res.json()["error"])
        profile.refresh_from_db()
        self.assertEqual(profile.email_verification_code, "")

        # Now attempting with the original valid code fails because it was cleared
        res = post_json(client, "/api/auth/verify-code/", {"email": user.email, "code": "123456"})
        self.assertEqual(res.status_code, 400)
        profile.refresh_from_db()
        self.assertFalse(profile.is_email_verified)

    @override_settings(DEBUG=False)
    def test_finding_4_docs_and_schema_hidden_when_debug_false(self):
        from django.urls import clear_url_caches
        import importlib
        import config.urls

        clear_url_caches()
        importlib.reload(config.urls)

        client = Client()
        res_docs = client.get("/api/docs/")
        res_redoc = client.get("/api/redoc/")
        res_schema = client.get("/api/schema/")

        self.assertEqual(res_docs.status_code, 404)
        self.assertEqual(res_redoc.status_code, 404)
        self.assertEqual(res_schema.status_code, 404)
