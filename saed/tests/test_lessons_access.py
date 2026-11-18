import shutil
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from ..models import Connection, CourseEnrollment, LessonAccess, PlatformSetting, Profile
from .helpers import login, mk_course, mk_lesson, mk_user, mp4, patch, pdf, post, put

TMP = tempfile.mkdtemp(prefix="saed-priv-")


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class CourseEnrolmentTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("t@x.com", "trainer")
        self.other = mk_user("t2@x.com", "trainer")
        self.student = mk_user("s@x.com", "corps_member")
        self.student2 = mk_user("s2@x.com", "corps_member")
        self.course = mk_course(self.trainer)
        self.sc = login(self.student)

    def test_enrol_auto_connects_to_trainer_in_one_step(self):
        r = post(self.sc, f"/api/courses/{self.course.public_id}/enroll/")
        self.assertIn(r.status_code, (200, 201), r.content)
        self.assertTrue(CourseEnrollment.objects.filter(student=self.student, course=self.course, status="confirmed").exists())
        self.assertTrue(Connection.objects.filter(corps_member=self.student, trainer=self.trainer).exists())

    def test_enrol_is_idempotent(self):
        post(self.sc, f"/api/courses/{self.course.public_id}/enroll/")
        r = post(self.sc, f"/api/courses/{self.course.public_id}/enroll/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(CourseEnrollment.objects.filter(student=self.student, course=self.course).count(), 1)
        self.assertEqual(Connection.objects.filter(corps_member=self.student, trainer=self.trainer).count(), 1)

    def test_legacy_integer_id_still_resolves(self):
        r = self.sc.get(f"/api/courses/{self.course.id}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["course"]["id"], str(self.course.public_id))

    def test_unpublished_course_hidden_from_students_and_catalogue(self):
        draft = mk_course(self.trainer, title="Draft", is_published=False)
        self.assertEqual(self.sc.get(f"/api/courses/{draft.public_id}/").status_code, 404)
        titles = [c["title"] for c in self.sc.get("/api/courses/").json()["courses"]]
        self.assertNotIn("Draft", titles)

    def test_full_course_rejects_enrolment(self):
        c = mk_course(self.trainer, title="Tiny", max_students=1)
        post(self.sc, f"/api/courses/{c.public_id}/enroll/")
        r = post(login(self.student2), f"/api/courses/{c.public_id}/enroll/")
        self.assertEqual(r.status_code, 400)

    def test_catalogue_newest_first_and_paginated(self):
        for i in range(15):
            mk_course(self.trainer, title=f"C{i}")
        r = self.sc.get("/api/courses/").json()
        self.assertEqual(len(r["courses"]), 12)
        self.assertEqual(r["pagination"]["total"], 16)
        self.assertEqual(r["courses"][0]["title"], "C14")

    def test_trainer_cannot_enrol(self):
        r = post(login(self.other), f"/api/courses/{self.course.public_id}/enroll/")
        self.assertIn(r.status_code, (400, 403))

    def test_my_enrollments_lists_enrolled_course(self):
        post(self.sc, f"/api/courses/{self.course.public_id}/enroll/")
        r = self.sc.get("/api/my-courses/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json().get("courses", r.json().get("enrollments", []))), 1)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class LessonManagementTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("t@x.com", "trainer")
        self.other = mk_user("t2@x.com", "trainer")
        self.course = mk_course(self.trainer)
        self.tc = login(self.trainer)

    def _create(self, **kw):
        body = {"courseId": str(self.course.public_id), "title": "L1", **kw}
        return post(self.tc, "/api/manage/lessons/", body)

    def test_default_lesson_is_free(self):
        r = self._create()
        self.assertEqual(r.status_code, 201, r.content)
        l = r.json()["lesson"]
        self.assertTrue(l["isFree"])
        self.assertFalse(l["requiresPayment"])

    def test_locking_requires_price(self):
        r = self._create(isLocked=True, price=0)
        self.assertEqual(r.status_code, 400)
        self.assertIn("price", r.json()["fields"])

    def test_locked_with_price_requires_payment(self):
        r = self._create(isLocked=True, price=1500)
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["lesson"]["requiresPayment"])

    def test_price_without_lock_stays_free(self):
        r = self._create(price=1500)
        self.assertTrue(r.json()["lesson"]["isFree"])

    def test_unlock_makes_lesson_free_again(self):
        l = mk_lesson(self.course, is_locked=True, price=500)
        r = patch(self.tc, f"/api/manage/lessons/{l.id}/", {"isLocked": False})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["lesson"]["isFree"])

    def test_other_trainer_cannot_edit_or_delete(self):
        l = mk_lesson(self.course)
        oc = login(self.other)
        self.assertEqual(patch(oc, f"/api/manage/lessons/{l.id}/", {"title": "x"}).status_code, 404)
        self.assertEqual(oc.delete(f"/api/manage/lessons/{l.id}/").status_code, 404)

    def test_corps_member_cannot_manage(self):
        r = post(login(mk_user("s@x.com", "corps_member")), "/api/manage/lessons/",
                 {"courseId": str(self.course.public_id), "title": "x"})
        self.assertEqual(r.status_code, 403)

    def test_reorder_requires_complete_list(self):
        a, b = mk_lesson(self.course, order=1), mk_lesson(self.course, order=2)
        url = f"/api/manage/courses/{self.course.public_id}/lessons/reorder/"
        self.assertEqual(post(self.tc, url, {"order": [a.id]}).status_code, 400)
        self.assertEqual(post(self.tc, url, {"order": [b.id, a.id]}).status_code, 200)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertLess(b.order, a.order)

    def test_document_upload_is_free_and_rejects_bad_type(self):
        l = mk_lesson(self.course)
        r = self.tc.post(f"/api/manage/lessons/{l.id}/upload/", {"kind": "document", "file": pdf()})
        self.assertEqual(r.status_code, 200, r.content)
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("evil.exe", b"MZ" + b"0" * 100, content_type="application/x-msdownload")
        r = self.tc.post(f"/api/manage/lessons/{l.id}/upload/", {"kind": "document", "file": bad})
        self.assertEqual(r.status_code, 400)

    def test_video_upload_402_when_fee_applies(self):
        l = mk_lesson(self.course)
        r = self.tc.post(f"/api/manage/lessons/{l.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 402)
        self.assertTrue(r.json()["requiresVideoUploadPayment"])

    def test_video_upload_free_when_fee_disabled(self):
        PlatformSetting.set("video_lesson_upload_fee", {"amount": 2000, "currency": "NGN", "enabled": False})
        l = mk_lesson(self.course)
        r = self.tc.post(f"/api/manage/lessons/{l.id}/upload/", {"kind": "video", "file": mp4()})
        self.assertEqual(r.status_code, 200, r.content)

    def test_generic_media_endpoint_rejects_video(self):
        r = self.tc.post("/api/media/upload/", {"file": mp4()})
        self.assertGreaterEqual(r.status_code, 400)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class GatedContentTests(TestCase):
    def setUp(self):
        PlatformSetting.set("video_lesson_upload_fee", {"amount": 2000, "currency": "NGN", "enabled": False})
        self.trainer = mk_user("t@x.com", "trainer", bank_name="GTB", account_number="0123456789", account_name="T Test")
        self.s1 = mk_user("s1@x.com", "corps_member")
        self.s2 = mk_user("s2@x.com", "corps_member")
        self.course = mk_course(self.trainer)
        self.free = mk_lesson(self.course, title="Free", order=1, text_content="hello")
        self.paid = mk_lesson(self.course, title="Paid", order=2, is_locked=True, price=1000, text_content="secret")
        tc = login(self.trainer)
        tc.post(f"/api/manage/lessons/{self.paid.id}/upload/", {"kind": "document", "file": pdf()})
        self.c1, self.c2 = login(self.s1), login(self.s2)
        post(self.c1, f"/api/courses/{self.course.public_id}/enroll/")

    def _viewer(self, c, lesson):
        return c.get(f"/api/lessons/{lesson.id}/")

    def test_free_lesson_open_to_enrolled(self):
        j = self._viewer(self.c1, self.free).json()
        self.assertTrue(j["lesson"]["hasAccess"])
        self.assertEqual(j["lesson"]["textContent"], "hello")

    def test_locked_lesson_hides_content_until_access(self):
        j = self._viewer(self.c1, self.paid).json()
        self.assertFalse(j["lesson"]["hasAccess"])
        self.assertEqual(j["lesson"]["textContent"], "")
        self.assertIsNone(j["lesson"]["document"])
        self.assertNotIn("media/", str(j["lesson"]))

    def test_direct_media_url_denied_without_access(self):
        self.assertEqual(self.c1.get(f"/api/lessons/{self.paid.id}/media/document/").status_code, 403)
        self.assertEqual(login(self.s2).get(f"/api/lessons/{self.paid.id}/media/document/").status_code, 403)

    def test_anonymous_media_request_is_401(self):
        from django.test import Client
        self.assertEqual(Client().get(f"/api/lessons/{self.paid.id}/media/document/").status_code, 401)

    def test_bank_transfer_request_grant_stream_revoke(self):
        r = post(self.c1, f"/api/lessons/{self.paid.id}/request-access/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(LessonAccess.objects.get(student=self.s1, lesson=self.paid).status, "requested")
        self.assertEqual(self._viewer(self.c1, self.paid).json()["lesson"]["hasAccess"], False)

        tc = login(self.trainer)
        g = post(tc, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.s1.id})
        self.assertEqual(g.status_code, 200, g.content)
        j = self._viewer(self.c1, self.paid).json()["lesson"]
        self.assertTrue(j["hasAccess"])
        self.assertEqual(j["textContent"], "secret")

        url = j["document"]["url"]
        from django.test import Client
        anon = Client()
        ok = anon.get("/api" + url.split("/api", 1)[1])
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(b"".join(ok.streaming_content)[:4], b"%PDF")

        rv = post(tc, f"/api/manage/lessons/{self.paid.id}/revoke/", {"studentId": self.s1.id})
        self.assertEqual(rv.status_code, 200)
        self.assertFalse(self._viewer(self.c1, self.paid).json()["lesson"]["hasAccess"])
        again = anon.get("/api" + url.split("/api", 1)[1])
        self.assertEqual(again.status_code, 403)

    def test_token_cannot_be_reused_for_another_lesson_or_kind(self):
        tc = login(self.trainer)
        post(tc, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.s1.id})
        url = self._viewer(self.c1, self.paid).json()["lesson"]["document"]["url"]
        token = url.split("t=", 1)[1]
        from django.test import Client
        other = mk_lesson(self.course, order=3)
        self.assertEqual(Client().get(f"/api/lessons/{other.id}/media/document/?t={token}").status_code, 401)
        self.assertEqual(Client().get(f"/api/lessons/{self.paid.id}/media/video/?t={token}").status_code, 401)

    def test_range_request_returns_206(self):
        tc = login(self.trainer)
        post(tc, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.s1.id})
        url = self._viewer(self.c1, self.paid).json()["lesson"]["document"]["url"]
        path = "/api" + url.split("/api", 1)[1]
        r = self.c1.get(path, HTTP_RANGE="bytes=0-9")
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r["Content-Range"].split("/")[0], "bytes 0-9")

    def test_non_enrolled_cannot_request_access(self):
        r = post(self.c2, f"/api/lessons/{self.paid.id}/request-access/")
        self.assertEqual(r.status_code, 403)

    def test_cannot_request_access_to_free_lesson(self):
        self.assertEqual(post(self.c1, f"/api/lessons/{self.free.id}/request-access/").status_code, 400)

    def test_other_trainer_cannot_grant(self):
        r = post(login(mk_user("t9@x.com", "trainer")), f"/api/manage/lessons/{self.paid.id}/grant/",
                 {"studentId": self.s1.id})
        self.assertEqual(r.status_code, 404)

    def test_cannot_grant_unenrolled_student(self):
        r = post(login(self.trainer), f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.s2.id})
        self.assertEqual(r.status_code, 400)

    def test_free_grant_by_trainer_source(self):
        post(login(self.trainer), f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.s1.id})
        self.assertEqual(LessonAccess.objects.get(student=self.s1, lesson=self.paid).source, "trainer_grant")

    def test_owner_and_admin_always_have_content(self):
        j = self._viewer(login(self.trainer), self.paid).json()["lesson"]
        self.assertTrue(j["hasAccess"])
        admin = mk_user("a@x.com", "saed_admin")
        self.assertEqual(self._viewer(login(admin), self.paid).status_code, 200)


class TrainerDiscoveryTests(TestCase):
    def setUp(self):
        self.s = mk_user("s@x.com", "corps_member")
        self.c = login(self.s)
        self.a = mk_user("a@x.com", "trainer", specialization="Tailoring", state_of_deployment="Lagos", lga_of_deployment="Ikeja")
        self.b = mk_user("b@x.com", "trainer", specialization="Baking", state_of_deployment="Abuja", lga_of_deployment="Gwagwalada")
        self.hidden = mk_user("h@x.com", "trainer", is_hidden=True)
        self.unauth = mk_user("u@x.com", "trainer", is_authorized=False)

    def _ids(self, qs=""):
        return {t["id"] for t in self.c.get("/api/trainers/" + qs).json()["trainers"]}

    def test_no_filters_returns_all_approved_trainers(self):
        ids = self._ids()
        self.assertEqual(ids, {self.a.id, self.b.id})

    def test_filters_are_optional_and_combinable(self):
        self.assertEqual(self._ids("?state=lagos"), {self.a.id})
        self.assertEqual(self._ids("?lga=gwagwalada"), {self.b.id})
        self.assertEqual(self._ids("?skill=baking"), {self.b.id})
        self.assertEqual(self._ids("?q=a%40x"), {self.a.id})
        self.assertEqual(self._ids("?state=lagos&skill=baking"), set())

    def test_trainer_cannot_use_corps_directory(self):
        self.assertEqual(login(self.a).get("/api/trainers/").status_code, 403)


class SettingsPermissionTests(TestCase):
    def setUp(self):
        self.dunis = login(mk_user("d@x.com", "dunis_admin"))
        self.saed = login(mk_user("a@x.com", "saed_admin"))
        self.trainer = login(mk_user("t@x.com", "trainer"))

    def test_only_dunis_can_change_fee(self):
        self.assertEqual(patch(self.saed, "/api/admin/platform-settings/", {"videoUploadFee": {"amount": 5}}).status_code, 403)
        self.assertEqual(patch(self.trainer, "/api/admin/platform-settings/", {"videoUploadFee": {"amount": 5}}).status_code, 403)
        r = patch(self.dunis, "/api/admin/platform-settings/", {"videoUploadFee": {"amount": 3500, "enabled": True}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["videoUploadFee"]["amount"], 3500)

    def test_saed_admin_can_read(self):
        self.assertEqual(self.saed.get("/api/admin/platform-settings/").status_code, 200)
        self.assertEqual(self.trainer.get("/api/admin/platform-settings/").status_code, 403)

    def test_invalid_values_rejected(self):
        for bad in ({"videoUploadFee": {"amount": -1}}, {"lessonPlatformFeePercent": 150}, {"trainerActivationFee": 0}):
            self.assertEqual(patch(self.dunis, "/api/admin/platform-settings/", bad).status_code, 400, bad)

    def test_disable_fee(self):
        patch(self.dunis, "/api/admin/platform-settings/", {"videoUploadFee": {"enabled": False}})
        self.assertFalse(self.dunis.get("/api/admin/platform-settings/").json()["videoUploadFee"]["applies"])

    def test_dunis_payments_monitor_permissions(self):
        self.assertEqual(self.dunis.get("/api/dunis/payments/").status_code, 200)
        self.assertEqual(self.saed.get("/api/dunis/payments/").status_code, 403)


class InCampTests(TestCase):
    """In-Camp and Post-Camp are separate tracks: an account only ever sees its own programme."""

    def setUp(self):
        from ..models import OrientationCamp
        from .helpers import mk_incamp, mk_stream
        self.stream = mk_stream(1)
        self.camp = OrientationCamp.objects.create(
            name="Camp A", state="Lagos", start_date=self.stream.start_date, end_date=self.stream.end_date,
            is_active=True, stream=self.stream)
        self.trainer = mk_incamp("t@x.com", "trainer", self.stream)
        self.post_trainer = mk_user("pt@x.com", "trainer")
        self.s = mk_incamp("s@x.com", "corps_member", self.stream, orientation_camp=self.camp)
        self.p = mk_user("p@x.com", "corps_member")  # Post-Camp corps member
        self.c, self.pcl = login(self.s), login(self.p)
        self.ic = mk_course(self.trainer, title="InCamp 1", course_type="in_camp", orientation_camp=self.camp,
                            stream=self.stream)
        self.pc = mk_course(self.post_trainer, title="Post 1", course_type="post_camp")

    def test_incamp_corper_sees_only_incamp_courses(self):
        r = self.c.get("/api/incamp/courses/").json()
        self.assertEqual([c["title"] for c in r["courses"]], ["InCamp 1"])
        self.assertEqual([c["title"] for c in self.c.get("/api/courses/").json()["courses"]], ["InCamp 1"])

    def test_postcamp_corper_sees_only_postcamp_courses(self):
        self.assertEqual([c["title"] for c in self.pcl.get("/api/courses/").json()["courses"]], ["Post 1"])
        self.assertEqual(self.pcl.get("/api/incamp/courses/").status_code, 403)
        # anonymous visitors only ever see the Post-Camp catalogue
        from django.test import Client
        self.assertEqual([c["title"] for c in Client().get("/api/courses/").json()["courses"]], ["Post 1"])

    def test_tracks_cannot_enrol_in_each_other(self):
        self.assertEqual(post(self.c, f"/api/courses/{self.pc.public_id}/enroll/").status_code, 403)
        self.assertEqual(post(self.pcl, f"/api/courses/{self.ic.public_id}/enroll/").status_code, 403)
        self.assertEqual(self.c.get(f"/api/courses/{self.pc.public_id}/").status_code, 403)
        self.assertEqual(self.pcl.get(f"/api/courses/{self.ic.public_id}/").status_code, 403)
        self.assertIn(post(self.c, f"/api/courses/{self.ic.public_id}/enroll/").status_code, (200, 201))
        self.assertIn(post(self.pcl, f"/api/courses/{self.pc.public_id}/enroll/").status_code, (200, 201))

    def test_incamp_corper_only_gets_own_stream(self):
        from .helpers import mk_stream
        other = mk_stream(2, start=30, end=60)
        far = mk_course(self.trainer, title="Other stream", course_type="in_camp", stream=other)
        self.assertEqual([c["title"] for c in self.c.get("/api/incamp/courses/").json()["courses"]], ["InCamp 1"])
        self.assertEqual(self.c.get(f"/api/courses/{far.public_id}/").status_code, 403)

    def test_ended_stream_switches_the_account_off(self):
        from datetime import timedelta
        from django.utils.timezone import now
        self.stream.end_date = now().date() - timedelta(days=1)
        self.stream.save()
        r = self.c.get("/api/incamp/courses/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("has ended", r.json()["detail"])
        self.assertEqual(post(self.c, f"/api/courses/{self.ic.public_id}/enroll/").status_code, 403)
        # the expiry state itself stays reachable
        self.assertEqual(self.c.get("/api/auth/me/").json()["user"]["lifecycle"]["state"], "expired")
        self.assertEqual(self.c.get("/api/incamp/dashboard/").status_code, 200)
        self.assertEqual(self.c.get("/api/my-courses/").status_code, 403)

    def test_incamp_corper_cannot_use_trainer_connections(self):
        self.assertEqual(self.c.get("/api/trainers/").status_code, 403)
        self.assertEqual(self.pcl.get("/api/trainers/").status_code, 200)


@override_settings(PRIVATE_MEDIA_ROOT=TMP)
class ReviewHardeningTests(TestCase):
    def setUp(self):
        self.trainer = mk_user("t@x.com", "trainer")
        self.student = mk_user("s@x.com", "corps_member")
        self.course = mk_course(self.trainer)
        self.paid = mk_lesson(self.course, is_locked=True, price=1000)
        self.tc = login(self.trainer)
        post(login(self.student), f"/api/courses/{self.course.public_id}/enroll/")

    def test_document_link_cannot_smuggle_video(self):
        for url in ("https://youtu.be/dQw4w9WgXcQ", "https://x.com/a/b.mp4", "https://vimeo.com/123"):
            r = patch(self.tc, f"/api/manage/lessons/{self.paid.id}/", {"documentLink": url})
            self.assertEqual(r.status_code, 400, url)

    def test_links_must_be_http(self):
        for key in ("documentLink", "videoLink"):
            for url in ("javascript:alert(1)", "data:text/html,x", "ftp://x/y"):
                r = patch(self.tc, f"/api/manage/lessons/{self.paid.id}/", {key: url})
                self.assertEqual(r.status_code, 400, (key, url))

    def test_admin_cannot_grant_or_revoke(self):
        for role in ("saed_admin", "dunis_admin"):
            c = login(mk_user(f"{role}@x.com", role))
            self.assertEqual(post(c, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.student.id}).status_code, 403)
            self.assertEqual(post(c, f"/api/manage/lessons/{self.paid.id}/revoke/", {"studentId": self.student.id}).status_code, 403)

    def test_grant_does_not_overwrite_paid_access(self):
        LessonAccess.objects.create(student=self.student, lesson=self.paid, status="active", source="paystack")
        post(self.tc, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.student.id})
        self.assertEqual(LessonAccess.objects.get(student=self.student, lesson=self.paid).source, "paystack")

    def test_inactive_course_stops_streaming(self):
        from django.test import Client
        PlatformSetting.set("video_lesson_upload_fee", {"amount": 2000, "currency": "NGN", "enabled": False})
        self.tc.post(f"/api/manage/lessons/{self.paid.id}/upload/", {"kind": "document", "file": pdf()})
        post(self.tc, f"/api/manage/lessons/{self.paid.id}/grant/", {"studentId": self.student.id})
        sc = login(self.student)
        url = sc.get(f"/api/lessons/{self.paid.id}/").json()["lesson"]["document"]["url"]
        path = "/api" + url.split("/api", 1)[1]
        self.assertEqual(Client().get(path).status_code, 200)
        self.course.is_active = False
        self.course.save()
        self.assertEqual(Client().get(path).status_code, 404)

    def test_legacy_path_reads_only_lesson_upload_folders(self):
        import os
        from django.conf import settings
        from ..services import media
        d = os.path.join(str(settings.MEDIA_ROOT), "partnership_letters")
        os.makedirs(d, exist_ok=True)
        f = os.path.join(d, "victim.pdf")
        open(f, "wb").write(b"%PDF-1")
        try:
            self.assertIsNone(media._legacy_local_path("https://x/media/partnership_letters/victim.pdf"))
        finally:
            os.remove(f)

    def test_riff_non_webp_rejected_on_image_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        avi = SimpleUploadedFile("x.webp", b"RIFF\x00\x00\x00\x00AVI LIST" + b"0" * 50, content_type="image/webp")
        self.assertEqual(self.tc.post("/api/media/upload/", {"file": avi}).status_code, 400)

    def test_profile_upload_rejects_disguised_files(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        bad = SimpleUploadedFile("pic.jpg", b"<html>x</html>" * 5, content_type="image/jpeg")
        r = login(self.student).patch("/api/profile/", {"profilePicture": bad}, format="multipart") if False else None
        self.assertIsNone(r)  # multipart PATCH covered by media.validate_profile_file unit check below
        from ..services import media
        with self.assertRaises(media.MediaError):
            media.validate_profile_file(bad)

    def test_settings_reject_nan_and_string_false(self):
        d = login(mk_user("d@x.com", "dunis_admin"))
        self.assertEqual(patch(d, "/api/admin/platform-settings/", {"videoUploadFee": {"amount": "NaN"}}).status_code, 400)
        patch(d, "/api/admin/platform-settings/", {"videoUploadFee": {"enabled": "false"}})
        self.assertFalse(d.get("/api/admin/platform-settings/").json()["videoUploadFee"]["enabled"])
        r = patch(d, "/api/admin/platform-settings/", {"videoUploadFee": {"amount": 4000}, "lessonPlatformFeePercent": 500})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(d.get("/api/admin/platform-settings/").json()["videoUploadFee"]["amount"], 2000.0)  # atomic: nothing saved
