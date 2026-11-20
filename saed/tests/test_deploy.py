"""Deployment-facing behaviour: root route, docs reachability, cross-site cookie options, deployment checks."""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from saed import checks

BACKEND = Path(__file__).resolve().parents[2]


class RootAndDocsTests(TestCase):
    def test_root_is_a_json_status_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["health"], "/api/health/")

    @override_settings(API_DOCS="public")
    def test_docs_pages_point_at_the_api_they_were_served_from(self):
        html = self.client.get("/api/docs/").content.decode()
        self.assertIn('url:"/api/openapi.json"', html)
        self.assertIn("/api/csrf/", html)
        self.assertIn('Redoc.init("/api/openapi.json"', self.client.get("/api/redoc/").content.decode())

    @override_settings(API_DOCS="staff")
    def test_staff_mode_hides_docs_from_anonymous_users(self):
        self.assertEqual(self.client.get("/api/docs/").status_code, 404)
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 404)
        self.assertEqual(self.client.get("/").json()["docsAccess"], "staff")


class DeploymentCheckTests(SimpleTestCase):
    def ids(self, front, back, samesite="Lax"):
        with override_settings(FRONTEND_URL=front, BACKEND_URL=back, SESSION_COOKIE_SAMESITE=samesite, DEBUG=False):
            return [w.id for w in checks.frontend_and_api_sites(None)]

    def test_different_sites_with_lax_cookies_warn(self):
        self.assertIn("saed.W002", self.ids("https://saed.dunistech.ng", "https://saed-api.simplylovely.ng"))

    def test_same_site_subdomains_are_fine(self):
        self.assertEqual(self.ids("https://saed.dunistech.ng", "https://saed-api.dunistech.ng"), [])

    def test_cross_site_with_samesite_none_is_accepted(self):
        self.assertEqual(self.ids("https://a.example.com", "https://b.example.org", "None"), [])

    def test_second_level_country_domains(self):
        self.assertEqual(checks._site("https://app.example.com.ng"), "example.com.ng")
        self.assertEqual(checks._site("https://api.example.com.ng"), "example.com.ng")

    def test_missing_backend_url_warns(self):
        self.assertIn("saed.W001", self.ids("https://a.example.com", ""))


class SettingsSubprocessTests(SimpleTestCase):
    """Settings are evaluated at import time, so each case runs in a fresh interpreter."""

    def run_settings(self, expr, **env):
        e = {**os.environ, "DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "x", "DJANGO_ALLOWED_HOSTS": "api.example.com",
             "DATABASE_URL": "sqlite:////tmp/saed-settings-check.sqlite3", **env}
        e.pop("DJANGO_TESTING", None)
        code = f"import config.settings as s; print({expr})"
        out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=e, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip().splitlines()[-1]

    def test_cross_site_cookie_switch(self):
        self.assertEqual(self.run_settings("(s.SESSION_COOKIE_SAMESITE, s.CSRF_COOKIE_SAMESITE, s.SESSION_COOKIE_SECURE)",
                                           CROSS_SITE_COOKIES="1"), "('None', 'None', True)")
        self.assertEqual(self.run_settings("s.SESSION_COOKIE_SAMESITE"), "Lax")

    def test_cookie_domain_is_optional(self):
        self.assertEqual(self.run_settings("s.SESSION_COOKIE_DOMAIN"), "None")
        self.assertEqual(self.run_settings("s.SESSION_COOKIE_DOMAIN", SESSION_COOKIE_DOMAIN=".example.com"), ".example.com")

    def test_postgres_engine_alias_is_normalised(self):
        self.assertEqual(self.run_settings("s.DATABASES['default']['ENGINE']", DATABASE_URL="postgres://u:p@localhost:5432/db"),
                         "django.db.backends.postgresql")

    def test_passenger_entry_point_exposes_application(self):
        out = subprocess.run([sys.executable, "-c", "import passenger_wsgi; print(callable(passenger_wsgi.application))"],
                             cwd=BACKEND, env={**os.environ, "DJANGO_DEBUG": "1"}, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "True", out.stderr)


class CreateAdminCommandTests(TestCase):
    def run_cmd(self, *args):
        from django.core.management import call_command
        from io import StringIO
        out = StringIO()
        call_command("create_saed_admin", *args, stdout=out)
        return out.getvalue()

    def test_creates_an_admin_who_can_sign_in(self):
        out = self.run_cmd("--email", "Boss@Example.org", "--password", "Str0ng-Passw0rd!", "--phone", "08031234567")
        self.assertIn("Created saed_admin", out)
        r = self.client.post("/api/auth/login/", {"email": "boss@example.org", "password": "Str0ng-Passw0rd!"},
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["user"]["role"], "saed_admin")

    def test_is_idempotent_and_can_promote(self):
        self.run_cmd("--email", "a@example.org", "--password", "Str0ng-Passw0rd!")
        out = self.run_cmd("--email", "a@example.org", "--role", "dunis_admin")
        self.assertIn("Updated dunis_admin", out)

    def test_rejects_weak_password(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self.run_cmd("--email", "w@example.org", "--password", "123")
