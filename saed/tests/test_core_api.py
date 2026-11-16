import hashlib
import hmac
import json
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings

from ..models import Connection, Course, CourseEnrollment, Profile
from .helpers import login, mk_user


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

    def test_email_verification_is_idempotent(self):
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
        self.assertEqual(second.status_code, 200)
        self.assertTrue(profile.is_email_verified)

    def test_admin_can_create_program(self):
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

        self.assertEqual(response.status_code, 201)
        program = Course.objects.get(title="Agro Enterprise")
        self.assertEqual(program.trainer, self.admin)

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
        self.assertIn(str(self.program.public_id), program_ids)
        self.assertNotIn(str(self.other_program.public_id), program_ids)

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
        self.assertEqual([item["id"] for item in programs], [str(self.program.public_id)])

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


class NotificationLinkTests(TestCase):
    def test_notification_list_includes_link(self):
        from ..models import Notification
        u = mk_user("n@x.com", "corps_member")
        Notification.objects.create(user=u, title="t", message="m", reason="course_published", link="/app/courses/abc")
        r = login(u).get("/api/notifications/").json()
        self.assertEqual(r["notifications"][0]["link"], "/app/courses/abc")
