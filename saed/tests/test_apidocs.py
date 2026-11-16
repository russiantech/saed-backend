import json

from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from saed.apidocs.builder import HIDDEN_PATHS, build_spec
from django.contrib.auth.models import User


def _routes(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _routes(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern)


class OpenAPITests(TestCase):
    def test_spec_is_valid_openapi_31(self):
        from openapi_spec_validator import validate
        validate(json.loads(json.dumps(build_spec())))

    def test_every_api_route_is_documented(self):
        import re
        documented = set(build_spec()["paths"])
        for r in _routes(get_resolver().url_patterns):
            if not r.startswith("api/"):
                continue
            r = r[4:]
            if r in HIDDEN_PATHS:
                continue
            self.assertIn("/" + re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", r), documented, r)

    def test_hidden_route_not_leaked(self):
        self.assertNotIn("_sys", json.dumps(build_spec()))

    def test_roles_reflected(self):
        op = build_spec()["paths"]["/payments/lesson/"]["post"]
        self.assertIn("corps_member", op["description"])

    @override_settings(API_DOCS="public")
    def test_public_mode_serves_everything(self):
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)
        r = self.client.get("/api/docs/")
        self.assertContains(r, "SwaggerUIBundle")
        self.assertIn("frame-ancestors 'none'", r["Content-Security-Policy"])
        self.assertContains(self.client.get("/api/redoc/"), "Redoc.init")
        self.assertEqual(self.client.get("/docs/").status_code, 302)

    @override_settings(API_DOCS="off")
    def test_off_mode_404(self):
        for u in ("/api/openapi.json", "/api/docs/", "/api/redoc/"):
            self.assertEqual(self.client.get(u).status_code, 404)

    @override_settings(API_DOCS="staff")
    def test_staff_mode_requires_admin(self):
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 404)
        User.objects.create_user("plain", "p@x.com", "pw12345678!")
        self.client.login(username="plain", password="pw12345678!")
        self.assertEqual(self.client.get("/api/docs/").status_code, 404)
        User.objects.create_user("st", "s@x.com", "pw12345678!", is_staff=True)
        self.client.login(username="st", password="pw12345678!")
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)
