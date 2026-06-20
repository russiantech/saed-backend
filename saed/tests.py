import json

from django.contrib.auth.models import User
from django.test import Client, TestCase

from .models import Application, Profile, Program


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
        Profile.objects.create(user=self.admin, role="saed_admin")
        self.program = Program.objects.create(
            title="ICT Skills",
            category="ict",
            description="Digital skills",
            duration_weeks=4,
            capacity=20,
            trainer=self.trainer,
            trainer_name="Lead Trainer",
            location="Lagos",
        )
        self.other_program = Program.objects.create(
            title="Food Skills",
            category="food_processing",
            description="Food business skills",
            duration_weeks=6,
            capacity=10,
            trainer=self.other_trainer,
            trainer_name="Other Trainer",
            location="Abuja",
        )
        self.application = Application.objects.create(applicant=self.member, program=self.program)
        self.other_application = Application.objects.create(applicant=self.admin, program=self.other_program)

    def login(self, user):
        client = Client()
        client.force_login(user)
        return client

    def test_trainer_can_update_application_status(self):
        client = self.login(self.trainer)
        response = patch_json(client, f"/api/manage/applications/{self.application.id}/", {"status": "approved"})

        self.assertEqual(response.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, "approved")

    def test_member_cannot_manage_applications(self):
        client = self.login(self.member)
        response = client.get("/api/manage/applications/")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_trainer(self):
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

        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(email="new-trainer@example.com").profile.role, "trainer")

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

        self.assertEqual(response.status_code, 400)
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

        self.assertEqual(response.status_code, 400)
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
                "capacity": 30,
                "trainerId": self.trainer.id,
                "location": "Abuja",
                "isActive": True,
            },
        )

        self.assertEqual(response.status_code, 201)
        program = Program.objects.get(title="Agro Enterprise")
        self.assertEqual(program.trainer, self.trainer)
        self.assertEqual(program.trainer_name, self.trainer.email)

    def test_trainer_cannot_create_program(self):
        client = self.login(self.trainer)
        response = post_json(
            client,
            "/api/manage/programs/",
            {
                "title": "Agro Enterprise",
                "category": "agro_allied",
                "description": "Farm business training",
                "durationWeeks": 6,
                "capacity": 30,
                "trainerId": self.trainer.id,
                "location": "Abuja",
                "isActive": True,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Program.objects.filter(title="Agro Enterprise").exists())

    def test_trainer_only_sees_own_programs(self):
        client = self.login(self.trainer)
        response = client.get("/api/manage/programs/")

        self.assertEqual(response.status_code, 200)
        program_ids = {item["id"] for item in response.json()["programs"]}
        self.assertIn(self.program.id, program_ids)
        self.assertNotIn(self.other_program.id, program_ids)

    def test_trainer_cannot_edit_program(self):
        client = self.login(self.trainer)
        response = patch_json(client, f"/api/manage/programs/{self.program.id}/", {"title": "Changed"})

        self.assertEqual(response.status_code, 403)
        self.program.refresh_from_db()
        self.assertEqual(self.program.title, "ICT Skills")

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
        response = post_json(client, "/api/auth/password-reset/", {"email": "member@example.com"})
        payload = response.json()

        response = post_json(
            client,
            "/api/auth/password-reset/confirm/",
            {"uid": payload["uid"], "token": payload["token"], "password": "NewPassword123!"},
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
        self.assertEqual(self.application.status, "approved")
