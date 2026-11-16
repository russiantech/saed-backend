import os
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from ..models import Profile
from .helpers import PDF, login, mk_course, mk_lesson, mk_user, pdf

PRIV = tempfile.mkdtemp(prefix="saed-priv-")
PUB = tempfile.mkdtemp(prefix="saed-pub-")
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def tearDownModule():
    shutil.rmtree(PRIV, ignore_errors=True)
    shutil.rmtree(PUB, ignore_errors=True)


def letter(name="slip.pdf", data=PDF):
    return SimpleUploadedFile(name, data)


@override_settings(PRIVATE_MEDIA_ROOT=PRIV, MEDIA_ROOT=PUB)
class PartnershipLetterTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("t@x.com", "trainer")
        self.other = mk_user("t2@x.com", "trainer")
        self.student = mk_user("s@x.com", "corps_member")
        self.admin = mk_user("a@x.com", "saed_admin")
        self.tc = login(self.trainer)

    def upload(self, client, f):
        return client.patch("/api/auth/update-profile/", data=None) if f is None else client.post("/api/auth/update-profile/", {"partnershipLetter": f}, HTTP_X_HTTP_METHOD_OVERRIDE="PATCH")

    def put_letter(self, name="slip.pdf", data=PDF):
        p = self.trainer.profile
        p.partnership_letter.save(name, SimpleUploadedFile(name, data), save=True)
        return p

    def test_letter_is_private_and_streamed_inline_to_owner_and_admin(self):
        p = self.put_letter()
        self.assertTrue(p.partnership_letter.path.startswith(PRIV))
        for c in (self.tc, login(self.admin)):
            r = c.get(f"/api/users/{self.trainer.id}/partnership-letter/")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r["Content-Disposition"].startswith("inline"))
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertIn("frame-ancestors", r["Content-Security-Policy"])
            self.assertEqual(r["Cache-Control"], "private, no-store")
            self.assertNotIn("X-Frame-Options", r)

    def test_letter_hidden_from_others_and_anonymous(self):
        self.put_letter()
        for c in (login(self.other), login(self.student)):
            self.assertEqual(c.get(f"/api/users/{self.trainer.id}/partnership-letter/").status_code, 404)
        from django.test import Client
        self.assertIn(Client().get(f"/api/users/{self.trainer.id}/partnership-letter/").status_code, (401, 403))

    def test_payload_exposes_api_path_never_a_media_url(self):
        self.put_letter()
        me = self.tc.get("/api/auth/me/").json()["user"]
        self.assertEqual(me["partnershipLetter"], f"/api/users/{self.trainer.id}/partnership-letter/")
        self.assertTrue(me["partnershipLetterAvailable"])
        self.assertEqual(me["partnershipLetterKind"], "pdf")
        self.assertNotIn("/media/", me["partnershipLetter"])

    def test_missing_file_gives_clear_json_404_and_flag(self):
        p = self.put_letter()
        os.remove(p.partnership_letter.path)
        r = self.tc.get(f"/api/users/{self.trainer.id}/partnership-letter/")
        self.assertEqual(r.status_code, 404)
        self.assertTrue(r.json()["missing"])
        self.assertFalse(self.tc.get("/api/auth/me/").json()["user"]["partnershipLetterAvailable"])

    def test_legacy_public_file_is_still_found(self):
        p = self.trainer.profile
        p.partnership_letter.name = "partnership_letters/old.pdf"
        p.save()
        os.makedirs(os.path.join(PUB, "partnership_letters"), exist_ok=True)
        with open(os.path.join(PUB, "partnership_letters", "old.pdf"), "wb") as fh:
            fh.write(PDF)
        self.assertEqual(self.tc.get(f"/api/users/{self.trainer.id}/partnership-letter/").status_code, 200)

    def test_path_traversal_name_is_not_served(self):
        p = self.trainer.profile
        p.partnership_letter.name = "../../etc/passwd"
        p.save()
        self.assertEqual(self.tc.get(f"/api/users/{self.trainer.id}/partnership-letter/").status_code, 404)

    def test_upload_replace_deletes_old_file_and_rejects_bad_types(self):
        from rest_framework.test import APIClient
        c = APIClient(); c.force_login(self.trainer)
        r = c.patch("/api/auth/update-profile/", {"partnershipLetter": letter("a.pdf")}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        first = self.trainer.profile.__class__.objects.get(user=self.trainer).partnership_letter.path
        self.assertTrue(os.path.isfile(first))
        r = c.patch("/api/auth/update-profile/", {"partnershipLetter": letter("b.png", PNG)}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(os.path.isfile(first))                       # superseded file removed
        self.assertEqual(c.get("/api/auth/me/").json()["user"]["partnershipLetterKind"], "image")
        for bad in (letter("c.docx", b"PK\x03\x04" + b"0" * 30), letter("d.pdf", b"not a pdf at all")):
            r = c.patch("/api/auth/update-profile/", {"partnershipLetter": bad}, format="multipart")
            self.assertEqual(r.status_code, 400, bad.name)

    def test_admin_can_replace_a_trainers_letter(self):
        from rest_framework.test import APIClient
        c = APIClient(); c.force_login(self.admin)
        r = c.patch(f"/api/manage/users/{self.trainer.id}/", {"partnershipLetter": letter()}, format="multipart")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.get(f"/api/users/{self.trainer.id}/partnership-letter/").status_code, 200)

    def test_trainer_signup_validates_the_letter(self):
        from django.test import Client
        base = {"fullName": "New Trainer", "email": "nt@x.com", "phone": "08011112222", "password": "Str0ng!Passw0rd",
                "confirmPassword": "Str0ng!Passw0rd", "specialization": "ict", "partnerLgas": '["Ikeja"]'}
        r = Client().post("/api/auth/trainer-signup/", {**base, "partnershipLetter": letter("x.docx", b"PK\x03\x04" + b"0" * 30)})
        self.assertEqual(r.status_code, 400)
        self.assertIn("partnershipLetter", r.json().get("fields", {}))


@override_settings(PRIVATE_MEDIA_ROOT=PRIV, MEDIA_ROOT=PUB)
class LessonDocumentFormatTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("t@x.com", "trainer")
        self.course = mk_course(self.trainer)
        self.lesson = mk_lesson(self.course)
        self.tc = login(self.trainer)

    def test_only_in_app_formats_can_be_uploaded(self):
        url = f"/api/manage/lessons/{self.lesson.id}/upload/"
        self.assertEqual(self.tc.post(url, {"kind": "document", "file": pdf()}).status_code, 200)
        self.assertEqual(self.tc.post(url, {"kind": "document", "file": letter("n.txt", b"hello")}).status_code, 200)
        self.assertEqual(self.tc.post(url, {"kind": "document", "file": letter("i.png", PNG)}).status_code, 200)
        for name in ("a.docx", "a.pptx", "a.xlsx", "a.doc"):
            r = self.tc.post(url, {"kind": "document", "file": letter(name, b"PK\x03\x04" + b"0" * 30)})
            self.assertEqual(r.status_code, 400, name)

    def test_external_document_links_are_rejected(self):
        r = self.tc.patch(f"/api/manage/lessons/{self.lesson.id}/", data='{"documentLink": "https://x.com/a.pdf"}', content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("documentLink", r.json().get("fields", {}))

    def test_stream_is_always_inline_never_attachment(self):
        self.tc.post(f"/api/manage/lessons/{self.lesson.id}/upload/", {"kind": "document", "file": pdf()})
        r = self.tc.get(f"/api/lessons/{self.lesson.id}/media/document/")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Disposition"].startswith("inline"))

    def test_legacy_office_file_is_refused_not_downloaded(self):
        from ..models import Lesson
        self.lesson.document_file.save("old.docx", SimpleUploadedFile("old.docx", b"PK\x03\x04" + b"0" * 30), save=True)
        r = self.tc.get(f"/api/lessons/{self.lesson.id}/media/document/")
        self.assertEqual(r.status_code, 415)
        self.assertNotIn("Content-Disposition", r)


class InCampConsistencyTests(TestCase):
    def setUp(self):
        self.t1 = mk_user("t1@x.com", "trainer")
        self.t2 = mk_user("t2@x.com", "trainer")
        self.s = mk_user("s@x.com", "corps_member")
        self.admin = mk_user("a@x.com", "saed_admin")
        self.mine = mk_course(self.t1, title="Mine InCamp", course_type="in_camp")
        self.draft = mk_course(self.t1, title="Draft InCamp", course_type="in_camp", is_published=False)
        self.post_camp = mk_course(self.t1, title="Mine PostCamp", course_type="post_camp")
        self.theirs = mk_course(self.t2, title="Theirs InCamp", course_type="in_camp")

    def titles(self, user):
        r = login(user).get("/api/incamp/courses/")
        self.assertEqual(r.status_code, 200, r.content)
        return {c["title"] for c in r.json()["courses"]}

    def test_corper_sees_every_published_in_camp_course_only(self):
        self.assertEqual(self.titles(self.s), {"Mine InCamp", "Theirs InCamp"})

    def test_trainer_sees_only_own_in_camp_courses_same_shape(self):
        self.assertEqual(self.titles(self.t1), {"Mine InCamp", "Draft InCamp"})
        a = login(self.s).get("/api/incamp/courses/").json()["courses"][0]
        b = login(self.t1).get("/api/incamp/courses/").json()["courses"][0]
        self.assertEqual(set(a), set(b))

    def test_admin_sees_all_in_camp(self):
        self.assertEqual(self.titles(self.admin), {"Mine InCamp", "Draft InCamp", "Theirs InCamp"})

    def test_training_session_endpoints_are_gone(self):
        c = login(self.t1)
        self.assertEqual(c.get("/api/manage/training-sessions/").status_code, 404)


class InCampSkillSetTests(TestCase):
    """Skill-set filter + 'own skill set first' for the In-Camp catalogue."""

    def setUp(self):
        self.t = mk_user("t@x.com", "trainer")
        self.ict = mk_course(self.t, title="ICT A", category="ict", course_type="in_camp")
        self.agro = mk_course(self.t, title="Agro A", category="agro_allied", course_type="in_camp")
        self.cater = mk_course(self.t, title="Cater A", category="culinary_catering", course_type="in_camp")

    def get(self, user, qs=""):
        r = login(user).get(f"/api/incamp/courses/{qs}")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def corper(self, **p):
        return mk_user(f"c{Profile.objects.count()}@x.com", "corps_member", **p)

    def test_own_skill_set_first_with_labels_or_keys(self):
        # profiles store display labels from the signup form; legacy/keys must work too
        s = self.corper(skill_interests=["Agro-Allied"], skill_interest="Agro-Allied")
        d = self.get(s)
        self.assertEqual(d["skillMode"], "mine")
        self.assertEqual([c["title"] for c in d["courses"]][0], "Agro A")
        self.assertEqual([c["matchesMySkills"] for c in d["courses"]], [True, False, False])
        self.assertEqual(d["mySkills"], [{"value": "agro_allied", "label": "Agro-Allied"}])
        k = self.corper(skill_interest="culinary_catering")
        self.assertEqual(self.get(k)["courses"][0]["title"], "Cater A")

    def test_multi_select_skill_set(self):
        s = self.corper(skill_interests=["ICT", "Culinary & Catering"], skill_interest="ICT")
        d = self.get(s)
        self.assertEqual({c["title"] for c in d["courses"][:2]}, {"ICT A", "Cater A"})
        self.assertEqual(d["courses"][2]["title"], "Agro A")

    def test_nothing_in_my_skill_set_shows_nothing_with_flag(self):
        s = self.corper(skill_interests=["Cosmetology"], skill_interest="Cosmetology")
        d = self.get(s)
        self.assertTrue(d["noSkillMatch"])
        self.assertEqual(d["courses"], [])
        # ...but they can explore everything else on request
        d = self.get(s, "?skill=all")
        self.assertFalse(d["noSkillMatch"])
        self.assertEqual(len(d["courses"]), 3)
        self.assertEqual(d["skillMode"], "all")

    def test_explicit_skill_filter_and_empty_result(self):
        s = self.corper(skill_interests=["ICT"], skill_interest="ICT")
        d = self.get(s, "?skill=agro_allied")
        self.assertEqual([c["title"] for c in d["courses"]], ["Agro A"])
        self.assertEqual(d["selectedSkill"], {"value": "agro_allied", "label": "Agro-Allied"})
        d = self.get(s, "?skill=cosmetology")
        self.assertEqual(d["courses"], [])
        self.assertFalse(d["noSkillMatch"])
        self.assertEqual(d["selectedSkill"]["label"], "Cosmetology")
        # labels are accepted as filter values too
        self.assertEqual(len(self.get(s, "?skill=Agro-Allied")["courses"]), 1)

    def test_corper_without_skill_set_sees_everything(self):
        d = self.get(self.corper())
        self.assertEqual(len(d["courses"]), 3)
        self.assertFalse(d["noSkillMatch"])
        self.assertEqual(d["skillMode"], "all")

    def test_trainer_is_not_skill_reordered_but_can_filter(self):
        d = self.get(self.t)
        self.assertEqual(len(d["courses"]), 3)
        self.assertFalse(any(c["matchesMySkills"] for c in d["courses"]))
        self.assertEqual(len(self.get(self.t, "?skill=ict")["courses"]), 1)
        self.assertEqual(len(d["skills"]), 11)

    def test_pagination_keeps_matches_first(self):
        s = self.corper(skill_interests=["Education"], skill_interest="Education")
        for i in range(14):
            mk_course(self.t, title=f"Other {i}", category="ict", course_type="in_camp")
        mk_course(self.t, title="Edu Z", category="education", course_type="in_camp")
        self.assertEqual(self.get(s)["courses"][0]["title"], "Edu Z")


class PerformanceGuardTests(TestCase):
    """Query-count budgets: these endpoints must not regress to N+1."""

    def setUp(self):
        self.t = mk_user("pt@x.com", "trainer")
        self.s = mk_user("ps@x.com", "corps_member")
        for i in range(8):
            c = mk_course(self.t, title=f"C{i}", course_type="in_camp" if i % 2 else "post_camp")
            for j in range(3):
                mk_lesson(c, title=f"L{j}", order=j)
            from ..models import CourseEnrollment
            CourseEnrollment.objects.create(student=self.s, course=c, status="confirmed")

    def budget(self, user, path, limit):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        c = login(user)
        c.get(path)
        with CaptureQueriesContext(connection) as q:
            r = c.get(path)
        self.assertEqual(r.status_code, 200, path)
        self.assertLessEqual(len(q), limit, f"{path}: {len(q)} queries")

    def test_query_budgets(self):
        for path, limit in (("/api/trainers/", 10), ("/api/dashboard/", 14), ("/api/my-courses/", 12),
                            ("/api/incamp/courses/", 12), ("/api/courses/", 8)):
            self.budget(self.s, path, limit)

    def test_course_detail_of_in_camp_course_works_for_every_role(self):
        from ..models import Course
        camp_course = Course.objects.filter(course_type="in_camp").first()
        admin = mk_user("pa@x.com", "saed_admin")
        for u in (self.s, self.t, admin):
            r = login(u).get(f"/api/courses/{camp_course.public_id}/")
            self.assertEqual(r.status_code, 200, r.content[:200])
            self.assertNotIn("sessions", r.json())

    def test_json_is_gzipped_but_media_is_not(self):
        c = login(self.s)
        r = c.get("/api/courses/", HTTP_ACCEPT_ENCODING="gzip")
        self.assertEqual(r.get("Content-Encoding"), "gzip" if len(r.content) > 200 else None)


class CampAdminTests(TestCase):
    def setUp(self):
        self.admin = mk_user("ca@x.com", "saed_admin")
        self.trainer = mk_user("ct@x.com", "trainer")
        self.c = login(self.admin)

    def mk(self, **kw):
        from .helpers import post
        body = {"name": "Camp A", "state": "Lagos", "location": "Iyana-Ipaja", "startDate": "2026-11-01", "endDate": "2026-11-21", **kw}
        return post(self.c, "/api/manage/orientation-camps/", body)

    def test_admin_can_add_edit_list_and_public_sees_active_only(self):
        from .helpers import patch
        r = self.mk()
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()["camp"]["id"]
        self.assertEqual(self.mk(name="Camp B", isActive=False).status_code, 201)
        listed = self.c.get("/api/manage/orientation-camps/").json()["camps"]
        self.assertEqual({k["name"] for k in listed}, {"Camp A", "Camp B"})
        self.assertIn("courseCount", listed[0])
        self.assertEqual(patch(self.c, f"/api/manage/orientation-camps/{cid}/", {"location": "New place"}).json()["camp"]["location"], "New place")
        from django.test import Client
        self.assertEqual({k["name"] for k in Client().get("/api/orientation-camps/").json()["camps"]}, {"Camp A"})

    def test_validation_and_duplicates(self):
        self.assertEqual(self.mk(endDate="2026-10-01").status_code, 400)
        self.assertEqual(self.mk(deactivationGraceDays=999).status_code, 400)
        self.assertEqual(self.mk().status_code, 201)
        self.assertEqual(self.mk().status_code, 409)

    def test_non_admins_cannot_manage_camps(self):
        for u in (self.trainer, mk_user("cc@x.com", "corps_member")):
            self.assertEqual(login(u).get("/api/manage/orientation-camps/").status_code, 403)

    def test_camp_in_use_cannot_be_deleted_but_unused_can(self):
        cid = self.mk().json()["camp"]["id"]
        from ..models import OrientationCamp
        mk_course(self.trainer, course_type="in_camp", orientation_camp=OrientationCamp.objects.get(id=cid))
        r = self.c.delete(f"/api/manage/orientation-camps/{cid}/")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Deactivate", r.json()["error"])
        free = self.mk(name="Free Camp").json()["camp"]["id"]
        self.assertEqual(self.c.delete(f"/api/manage/orientation-camps/{free}/").status_code, 200)
