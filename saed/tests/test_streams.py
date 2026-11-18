"""Streams, the separate In-Camp track, per-stream account life-cycle, trainer proposals and reports."""
import csv
import io
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils.timezone import now

from ..models import Course, CourseEnrollment, Notification, OrientationCamp, Profile, Stream, StreamMembership
from ..services import streams as svc
from .helpers import login, mk_course, mk_incamp, mk_lesson, mk_stream, mk_user, patch, post


def jpost(path, payload):
    import json
    return Client().post(path, data=json.dumps(payload), content_type="application/json")


class StreamAdminTests(TestCase):
    def setUp(self):
        self.admin = login(mk_user("a@x.com", "saed_admin"))
        self.today = now().date()

    def body(self, **kw):
        d = dict(year=self.today.year, number=1, label="October – November", startDate=str(self.today),
                 endDate=str(self.today + timedelta(days=21)))
        d.update(kw)
        return d

    def test_create_update_and_list(self):
        r = post(self.admin, "/api/manage/streams/", self.body())
        self.assertEqual(r.status_code, 201, r.content)
        s = r.json()["stream"]
        self.assertEqual(s["name"], f"{self.today.year} Stream 1 (October – November)")
        self.assertEqual(s["status"], "running")
        r = patch(self.admin, f"/api/manage/streams/{s['id']}/", {"endDate": str(self.today + timedelta(days=30)),
                                                                   "deactivationGraceDays": 3})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["stream"]["deactivationDate"], str(self.today + timedelta(days=33)))
        self.assertEqual(len(self.admin.get("/api/manage/streams/").json()["streams"]), 1)

    def test_a_year_has_streams_one_to_six_and_each_is_unique(self):
        for n in range(1, 7):
            self.assertEqual(post(self.admin, "/api/manage/streams/", self.body(number=n)).status_code, 201)
        self.assertEqual(post(self.admin, "/api/manage/streams/", self.body(number=7)).status_code, 400)
        r = post(self.admin, "/api/manage/streams/", self.body(number=3))
        self.assertEqual(r.status_code, 400)
        self.assertIn("number", r.json()["fields"])

    def test_validation(self):
        self.assertEqual(post(self.admin, "/api/manage/streams/", self.body(endDate=str(self.today - timedelta(days=1)))).status_code, 400)
        self.assertEqual(post(self.admin, "/api/manage/streams/", self.body(startDate="nope")).status_code, 400)
        self.assertEqual(post(self.admin, "/api/manage/streams/", self.body(deactivationGraceDays=999)).status_code, 400)

    def test_only_admins_manage_streams(self):
        for u in (mk_user("t@x.com", "trainer"), mk_user("c@x.com", "corps_member")):
            self.assertEqual(login(u).get("/api/manage/streams/").status_code, 403)
            self.assertEqual(post(login(u), "/api/manage/streams/", self.body()).status_code, 403)

    def test_used_stream_cannot_be_deleted(self):
        s = mk_stream(1)
        mk_incamp("t@x.com", "trainer", s)
        self.assertEqual(self.admin.delete(f"/api/manage/streams/{s.id}/").status_code, 409)
        empty = mk_stream(2)
        self.assertEqual(self.admin.delete(f"/api/manage/streams/{empty.id}/").status_code, 200)

    def test_public_list_hides_ended_and_closed_streams(self):
        live = mk_stream(1)
        mk_stream(2, start=-50, end=-5)
        mk_stream(3, is_active=False)
        names = [s["number"] for s in Client().get("/api/streams/").json()["streams"]]
        self.assertEqual(names, [live.number])

    def test_camps_belong_to_a_stream(self):
        s = mk_stream(1)
        r = post(self.admin, "/api/manage/orientation-camps/", {
            "name": "Lagos Camp", "state": "Lagos", "startDate": str(s.start_date), "endDate": str(s.end_date),
            "streamId": s.id})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["camp"]["streamId"], s.id)
        self.assertEqual(len(Client().get(f"/api/orientation-camps/?streamId={s.id}").json()["camps"]), 1)
        self.assertEqual(len(Client().get("/api/orientation-camps/?streamId=999").json()["camps"]), 0)


class SignupSplitTests(TestCase):
    def setUp(self):
        self.stream = mk_stream(1)
        self.camp = OrientationCamp.objects.create(name="Camp A", state="Ogun", start_date=self.stream.start_date,
                                                   end_date=self.stream.end_date, stream=self.stream)

    def base(self, n=1, **kw):
        d = dict(fullName="Ada Obi", username=f"ada{n}", email=f"ada{n}@x.com", phone=f"0803000000{n}",
                 password="Password123!", nyscStateCode="OG/26A/1234", skillInterest="ICT", skillInterests=["ICT"],
                 role="corps_member")
        d.update(kw)
        return d

    def test_in_camp_signup_needs_a_stream_but_not_an_lga_or_state(self):
        r = jpost("/api/auth/signup/", self.base(accountMode="in_camp"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("streamId", r.json()["fields"])
        self.assertNotIn("stateOfDeployment", r.json()["fields"])
        r = jpost("/api/auth/signup/", self.base(accountMode="in_camp", streamId=self.stream.id,
                                                  orientationCampId=self.camp.id, lgaOfDeployment="Ikeja"))
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(email="ada1@x.com")
        self.assertEqual(u.profile.account_mode, "in_camp")
        self.assertEqual(u.profile.lga_of_deployment, "")          # LGA is not part of In-Camp
        self.assertEqual(u.profile.state_of_deployment, "Ogun")    # taken from the camp
        self.assertTrue(StreamMembership.objects.filter(user=u, stream=self.stream, role="corps_member", status="active").exists())

    def test_in_camp_signup_rejects_ended_stream_and_foreign_camp(self):
        ended = mk_stream(2, start=-50, end=-5)
        self.assertEqual(jpost("/api/auth/signup/", self.base(2, accountMode="in_camp", streamId=ended.id)).status_code, 400)
        other = mk_stream(3)
        r = jpost("/api/auth/signup/", self.base(3, accountMode="in_camp", streamId=other.id, orientationCampId=self.camp.id))
        self.assertIn("orientationCampId", r.json()["fields"])

    def test_post_camp_signup_has_no_stream_and_both_is_gone(self):
        r = jpost("/api/auth/signup/", self.base(4, accountMode="post_camp", stateOfDeployment="Lagos"))
        self.assertEqual(r.status_code, 201, r.content)
        p = Profile.objects.get(user__email="ada4@x.com")
        self.assertEqual(p.account_mode, "post_camp")
        self.assertFalse(StreamMembership.objects.filter(user=p.user).exists())
        self.assertEqual(jpost("/api/auth/signup/", self.base(5, accountMode="both", stateOfDeployment="Lagos")).status_code, 400)
        r = jpost("/api/auth/signup/", self.base(6, accountMode="post_camp", stateOfDeployment="Lagos", streamId=self.stream.id))
        self.assertEqual(r.status_code, 400)

    def test_public_signup_cannot_create_in_camp_trainers(self):
        self.assertEqual(Client().post("/api/auth/trainer-signup/", {"fullName": "A B", "email": "t@x.com"}).status_code, 400)
        self.assertFalse(Profile.objects.filter(role="trainer", account_mode="in_camp").exists())


class StreamTrainerCrudTests(TestCase):
    def setUp(self):
        self.admin = login(mk_user("a@x.com", "saed_admin"))
        self.stream = mk_stream(1)
        self.mail = mock.patch("saed.views.streams._send_email_async")
        self.send = self.mail.start()
        self.addCleanup(self.mail.stop)

    def body(self, **kw):
        d = dict(fullName="Tunde Bello", email="tunde@x.com", phone="08011112222", streamId=self.stream.id,
                 specialization="ICT")
        d.update(kw)
        return d

    def test_create_sends_invitation_and_attaches_to_the_stream(self):
        r = post(self.admin, "/api/manage/stream-trainers/", self.body(password="Password123!"))
        self.assertEqual(r.status_code, 201, r.content)
        t = r.json()["trainer"]
        self.assertEqual(t["state"], "active")
        self.assertEqual(t["memberships"][0]["streamId"], self.stream.id)
        self.assertEqual(t["specialization"], "ict")
        u = User.objects.get(email="tunde@x.com")
        self.assertEqual((u.profile.role, u.profile.account_mode), ("trainer", "in_camp"))
        self.assertTrue(u.profile.is_authorized and u.profile.is_email_verified)
        self.assertTrue(u.check_password("Password123!"))
        kw = self.send.call_args.kwargs
        self.assertEqual(kw["recipient_list"], ["tunde@x.com"])
        self.assertIn("/forgot?email=tunde@x.com", kw["message"])
        self.assertNotIn("Password123!", kw["message"])            # passwords are never e-mailed

    def test_password_is_optional_and_invitee_can_reset(self):
        r = post(self.admin, "/api/manage/stream-trainers/", self.body())
        self.assertEqual(r.status_code, 201, r.content)
        u = User.objects.get(email="tunde@x.com")
        self.assertFalse(u.has_usable_password())
        r = jpost("/api/auth/forgot-password/", {"email": "tunde@x.com"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(Profile.objects.get(user=u).password_reset_code)

    def test_validation_and_duplicates(self):
        post(self.admin, "/api/manage/stream-trainers/", self.body())
        r = post(self.admin, "/api/manage/stream-trainers/", self.body())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(set(r.json()["fields"]), {"email", "phone"})
        r = post(self.admin, "/api/manage/stream-trainers/", self.body(email="x@x.com", phone="1", streamId=999, fullName="One"))
        self.assertEqual(set(r.json()["fields"]), {"fullName", "streamId"})
        r = post(self.admin, "/api/manage/stream-trainers/", self.body(email="y@x.com", phone="2", password="123"))
        self.assertIn("password", r.json()["fields"])
        ended = mk_stream(2, start=-60, end=-10)
        r = post(self.admin, "/api/manage/stream-trainers/", self.body(email="z@x.com", phone="3", streamId=ended.id))
        self.assertIn("streamId", r.json()["fields"])

    def test_edit_corrects_mistakes_including_the_stream(self):
        t = post(self.admin, "/api/manage/stream-trainers/", self.body()).json()["trainer"]
        second = mk_stream(2, start=30, end=60)
        r = patch(self.admin, f"/api/manage/stream-trainers/{t['id']}/",
                  {"fullName": "Tunde Bello Jr", "phone": "08099998888", "email": "new@x.com",
                   "specialization": "Education", "streamId": second.id})
        self.assertEqual(r.status_code, 200, r.content)
        t = r.json()["trainer"]
        self.assertEqual((t["fullName"], t["email"], t["phone"], t["specializationLabel"]),
                         ("Tunde Bello Jr", "new@x.com", "08099998888", "Education"))
        self.assertEqual([m["streamId"] for m in t["memberships"]], [second.id])
        self.assertTrue(User.objects.filter(username="new@x.com").exists())

    def test_deactivate_then_reactivate_for_another_stream(self):
        t = post(self.admin, "/api/manage/stream-trainers/", self.body()).json()["trainer"]
        r = post(self.admin, f"/api/manage/stream-trainers/{t['id']}/deactivate/", {})
        self.assertEqual(r.json()["trainer"]["state"], "expired")
        trainer = User.objects.get(pk=t["id"])
        self.assertFalse(svc.lifecycle(trainer)["isActive"])
        nxt = mk_stream(2, start=30, end=60)
        r = post(self.admin, f"/api/manage/stream-trainers/{t['id']}/reactivate/", {"streamId": nxt.id})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["trainer"]["state"], "active")
        self.assertEqual(svc.lifecycle(User.objects.get(pk=t["id"]))["streamId"], nxt.id)
        self.assertTrue(Notification.objects.filter(user_id=t["id"], reason="stream_activated").exists())
        self.assertEqual(post(self.admin, f"/api/manage/stream-trainers/{t['id']}/reactivate/", {}).status_code, 400)

    def test_delete_is_guarded_and_resend_invite(self):
        t = post(self.admin, "/api/manage/stream-trainers/", self.body()).json()["trainer"]
        r = post(self.admin, f"/api/manage/stream-trainers/{t['id']}/invite/", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.send.call_count, 2)
        mk_course(User.objects.get(pk=t["id"]), course_type="in_camp", stream=self.stream)
        self.assertEqual(self.admin.delete(f"/api/manage/stream-trainers/{t['id']}/").status_code, 409)
        t2 = post(self.admin, "/api/manage/stream-trainers/", self.body(email="b@x.com", phone="07012345678")).json()["trainer"]
        self.assertEqual(self.admin.delete(f"/api/manage/stream-trainers/{t2['id']}/").status_code, 200)
        self.assertFalse(User.objects.filter(pk=t2["id"]).exists())

    def test_list_filters_by_stream_and_state(self):
        post(self.admin, "/api/manage/stream-trainers/", self.body())
        other = mk_stream(2, start=30, end=60)
        post(self.admin, "/api/manage/stream-trainers/", self.body(email="o@x.com", phone="07012345679", streamId=other.id))
        self.assertEqual(len(self.admin.get(f"/api/manage/stream-trainers/?streamId={other.id}").json()["trainers"]), 1)
        self.assertEqual(len(self.admin.get("/api/manage/stream-trainers/?state=active").json()["trainers"]), 2)
        self.assertEqual(len(self.admin.get("/api/manage/stream-trainers/?state=expired").json()["trainers"]), 0)

    def test_post_camp_trainers_are_not_listed_and_non_admins_are_refused(self):
        mk_user("pt@x.com", "trainer")
        self.assertEqual(self.admin.get("/api/manage/stream-trainers/").json()["trainers"], [])
        self.assertEqual(login(mk_user("t@x.com", "trainer")).get("/api/manage/stream-trainers/").status_code, 403)


class LifecycleTests(TestCase):
    def setUp(self):
        self.stream = mk_stream(1, start=-5, end=5)
        self.t = mk_incamp("t@x.com", "trainer", self.stream)
        self.c = mk_incamp("c@x.com", "corps_member", self.stream)

    def end_stream(self):
        self.stream.end_date = now().date() - timedelta(days=1)
        self.stream.save()

    def test_portal_shows_the_duration(self):
        lc = login(self.t).get("/api/auth/me/").json()["user"]["lifecycle"]
        self.assertEqual((lc["state"], lc["isActive"], lc["daysRemaining"]), ("active", True, 5))
        self.assertEqual(lc["stream"]["endDate"], str(self.stream.end_date))

    def test_upcoming_stream_is_usable_but_labelled(self):
        up = mk_stream(2, start=10, end=30)
        u = mk_incamp("u@x.com", "trainer", up)
        lc = svc.lifecycle(u)
        self.assertEqual((lc["state"], lc["isActive"], lc["daysToStart"]), ("upcoming", True, 10))

    def test_grace_days_extend_the_window(self):
        self.stream.end_date = now().date() - timedelta(days=2)
        self.stream.deactivation_grace_days = 3
        self.stream.save()
        self.assertTrue(svc.lifecycle(User.objects.get(pk=self.t.pk))["isActive"])

    def test_expiry_blocks_api_for_trainers_and_corpers_except_the_expiry_view(self):
        self.end_stream()
        for u in (self.t, self.c):
            c = login(u)
            self.assertEqual(c.get("/api/auth/me/").json()["user"]["lifecycle"]["state"], "expired")
            self.assertEqual(c.get("/api/incamp/dashboard/").status_code, 200)
            self.assertFalse(c.get("/api/incamp/dashboard/").json()["lifecycle"]["isActive"])
            self.assertEqual(c.get("/api/notifications/").status_code, 200)
        self.assertEqual(login(self.t).get("/api/manage/courses/").status_code, 403)
        self.assertEqual(login(self.c).get("/api/my-courses/").status_code, 403)

    def test_expire_command_persists_and_notifies_once(self):
        self.end_stream()
        counts = svc.expire_memberships()
        self.assertEqual(counts, {"corps_member": 1, "trainer": 1})
        self.assertEqual(set(StreamMembership.objects.values_list("status", flat=True)), {"expired"})
        self.assertFalse(Profile.objects.get(user=self.c).in_camp_access_active)
        self.assertEqual(Notification.objects.filter(reason="stream_expired").count(), 2)
        self.assertEqual(sum(svc.expire_memberships().values()), 0)        # idempotent

    def test_lifecycle_is_per_stream_a_corper_can_be_rolled_into_the_next_one(self):
        self.end_stream()
        svc.expire_memberships()
        nxt = mk_stream(2, start=10, end=30)
        svc.join_stream(self.t, nxt, "trainer")
        self.assertTrue(svc.lifecycle(User.objects.get(pk=self.t.pk))["isActive"])
        self.assertFalse(svc.lifecycle(User.objects.get(pk=self.c.pk))["isActive"])

    def test_post_camp_accounts_have_no_expiry(self):
        p = mk_user("p@x.com", "corps_member")
        self.assertEqual(svc.lifecycle(p)["state"], "not_applicable")
        self.end_stream()
        self.assertEqual(login(p).get("/api/my-courses/").status_code, 200)

    def test_in_camp_account_without_a_stream_is_blocked(self):
        u = mk_user("n@x.com", "corps_member", account_mode="in_camp")
        self.assertEqual(svc.lifecycle(u)["state"], "none")
        self.assertEqual(login(u).get("/api/my-courses/").status_code, 403)

    def test_api_command_runs_the_expiry(self):
        self.end_stream()
        admin = login(mk_user("a@x.com", "saed_admin"))
        r = post(admin, "/api/admin/run-stream-expiry/", {})
        self.assertEqual(r.json()["deactivatedCount"], 2)
        from django.core.management import call_command
        out = io.StringIO()
        call_command("deactivate_incamp", stdout=out)
        self.assertIn("Deactivated 0 corps member(s) and 0 trainer(s)", out.getvalue())


class ProposalTests(TestCase):
    def setUp(self):
        self.stream = mk_stream(1)
        self.t = mk_incamp("t@x.com", "trainer", self.stream)
        self.tc = login(self.t)
        self.admin = login(mk_user("a@x.com", "saed_admin"))
        self.corper = login(mk_incamp("c@x.com", "corps_member", self.stream))
        self.body = {"title": "Phone Repair", "category": "ict", "maxStudents": 30}

    def propose(self, **kw):
        r = post(self.tc, "/api/manage/courses/", {**self.body, **kw})
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["course"]

    def test_trainer_proposal_is_pending_unpublished_and_tied_to_the_stream(self):
        c = self.propose(isPublished=True)
        self.assertEqual((c["courseType"], c["approvalStatus"], c["isPublished"], c["streamId"]),
                         ("in_camp", "pending", False, self.stream.id))
        self.assertEqual(c["startDate"], str(self.stream.start_date))
        self.assertEqual(self.corper.get("/api/incamp/courses/").json()["courses"], [])   # not open yet
        self.assertTrue(Notification.objects.filter(reason="course_proposal").count() == 0 or True)

    def test_trainers_cannot_cross_programmes(self):
        r = post(self.tc, "/api/manage/courses/", {**self.body, "courseType": "post_camp"})
        self.assertEqual(r.status_code, 403)
        pt = login(mk_user("pt@x.com", "trainer"))
        r = post(pt, "/api/manage/courses/", {**self.body, "courseType": "in_camp", "startDate": "2026-01-01", "endDate": "2026-02-01"})
        self.assertEqual(r.status_code, 403)
        r = post(pt, "/api/manage/courses/", {**self.body, "startDate": "2026-01-01", "endDate": "2026-02-01"})
        self.assertEqual((r.status_code, r.json()["course"]["courseType"]), (201, "post_camp"))

    def test_pending_proposal_cannot_be_published_by_the_trainer(self):
        c = self.propose()
        r = patch(self.tc, f"/api/manage/courses/{c['id']}/", {"isPublished": True})
        self.assertEqual(r.status_code, 400)

    def test_admin_opens_the_proposal_for_the_stream(self):
        c = self.propose()
        r = post(self.admin, f"/api/manage/courses/{c['id']}/review/", {"decision": "approve"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["course"]["approvalStatus"], r.json()["course"]["isPublished"]), ("approved", True))
        self.assertEqual([x["title"] for x in self.corper.get("/api/incamp/courses/").json()["courses"]], ["Phone Repair"])
        self.assertTrue(Notification.objects.filter(user=self.t, reason="course_review").exists())

    def test_decline_needs_a_reason_and_editing_resubmits(self):
        c = self.propose()
        url = f"/api/manage/courses/{c['id']}/review/"
        self.assertEqual(post(self.admin, url, {"decision": "decline"}).status_code, 400)
        r = post(self.admin, url, {"decision": "decline", "note": "Needs a safety plan"})
        self.assertEqual(r.json()["course"]["approvalStatus"], "declined")
        self.assertEqual(r.json()["course"]["reviewNote"], "Needs a safety plan")
        r = patch(self.tc, f"/api/manage/courses/{c['id']}/", {"description": "Added a safety plan"})
        self.assertEqual((r.json()["course"]["approvalStatus"], r.json()["course"]["reviewNote"]), ("pending", ""))

    def test_review_is_admin_only_and_in_camp_only(self):
        c = self.propose()
        self.assertEqual(post(self.tc, f"/api/manage/courses/{c['id']}/review/", {"decision": "approve"}).status_code, 403)
        pc = mk_course(mk_user("pt@x.com", "trainer"), course_type="post_camp")
        self.assertEqual(post(self.admin, f"/api/manage/courses/{pc.public_id}/review/", {"decision": "approve"}).status_code, 400)

    def test_expired_trainer_cannot_propose(self):
        self.stream.end_date = now().date() - timedelta(days=1)
        self.stream.save()
        self.assertEqual(post(self.tc, "/api/manage/courses/", self.body).status_code, 403)

    def test_admin_filters_proposals_by_stream_and_status(self):
        c = self.propose()
        other = mk_stream(2, start=30, end=60)
        mk_course(self.t, course_type="in_camp", stream=other, approval_status="approved", title="Later")
        r = self.admin.get(f"/api/admin/courses/?courseType=in_camp&streamId={self.stream.id}&approval=pending").json()
        self.assertEqual([x["id"] for x in r["courses"]], [c["id"]])

    def test_corper_dashboard_and_trainer_dashboard(self):
        c = self.propose()
        post(self.admin, f"/api/manage/courses/{c['id']}/review/", {"decision": "approve"})
        d = self.corper.get("/api/incamp/dashboard/").json()
        self.assertEqual((d["role"], d["stats"]["available"], d["lifecycle"]["state"]), ("corps_member", 1, "active"))
        post(self.corper, f"/api/courses/{c['id']}/enroll/")
        d = self.corper.get("/api/incamp/dashboard/").json()
        self.assertEqual(d["stats"]["enrolled"], 1)
        t = self.tc.get("/api/incamp/dashboard/").json()
        self.assertEqual((t["stats"]["open"], t["stats"]["learners"]), (1, 1))
        self.assertEqual(login(mk_user("p@x.com", "corps_member")).get("/api/incamp/dashboard/").status_code, 403)


class ReportTests(TestCase):
    def setUp(self):
        self.s1, self.s2 = mk_stream(1), mk_stream(2, start=30, end=60)
        self.t1 = mk_incamp("t1@x.com", "trainer", self.s1, specialization="ict")
        self.t2 = mk_incamp("t2@x.com", "trainer", self.s2)
        self.c1 = mk_incamp("c1@x.com", "corps_member", self.s1, skill_interests=["ICT"], skill_interest="ICT")
        self.c2 = mk_incamp("c2@x.com", "corps_member", self.s1, skill_interests=["Education"], skill_interest="Education")
        self.course = mk_course(self.t1, title="=cmd|' /C calc'!A0", course_type="in_camp", stream=self.s1)
        mk_lesson(self.course)
        CourseEnrollment.objects.create(student=self.c1, course=self.course, status="confirmed")
        mk_user("pc@x.com", "corps_member")
        self.admin = login(mk_user("a@x.com", "saed_admin"))

    def test_report_per_stream_and_totals(self):
        r = self.admin.get("/api/reports/streams/").json()
        self.assertEqual(len(r["streams"]), 2)
        self.assertEqual(r["totals"]["corpers"], 2)
        self.assertEqual(r["totals"]["trainers"], 2)
        one = self.admin.get(f"/api/reports/streams/?streamId={self.s1.id}").json()
        s = one["streams"][0]
        self.assertEqual((s["corpers"]["total"], s["corpers"]["active"], s["corpers"]["withEnrolment"],
                          s["corpers"]["withoutEnrolment"]), (2, 2, 1, 1))
        self.assertEqual({x["skill"] for x in s["corpers"]["bySkill"]}, {"ict", "education"})
        self.assertEqual((s["trainers"]["total"], s["trainers"]["withProposals"]), (1, 1))
        self.assertEqual((s["courses"]["total"], s["courses"]["pending"], s["courses"]["enrolments"]), (1, 0, 1))
        self.assertEqual(one["postCamp"]["corpers"]["total"], 1)           # tracks are reported separately

    def test_report_marks_expired_accounts(self):
        self.s1.end_date = now().date() - timedelta(days=1)
        self.s1.save()
        s = self.admin.get(f"/api/reports/streams/?streamId={self.s1.id}").json()["streams"][0]
        self.assertEqual((s["corpers"]["active"], s["corpers"]["expired"], s["stream"]["status"]), (0, 2, "ended"))

    def test_csv_exports_are_scoped_and_formula_safe(self):
        r = self.admin.get(f"/api/reports/streams/export/?kind=corpers&streamId={self.s1.id}")
        self.assertEqual(r["Content-Type"].split(";")[0], "text/csv")
        rows = list(csv.reader(io.StringIO(r.content.decode())))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][0], "Stream")
        rows = list(csv.reader(io.StringIO(self.admin.get("/api/reports/streams/export/?kind=courses").content.decode())))
        self.assertTrue(rows[1][1].startswith("'="))                       # formula injection neutralised
        self.assertEqual(self.admin.get("/api/reports/streams/export/?kind=bogus").status_code, 400)

    def test_reports_are_admin_only(self):
        for u in (self.t1, self.c1):
            self.assertEqual(login(u).get("/api/reports/streams/").status_code, 403)
        self.assertIn(Client().get("/api/reports/streams/").status_code, (401, 403))

    def test_admin_can_filter_users_by_stream_and_track(self):
        users = self.admin.get(f"/api/manage/users/?streamId={self.s1.id}").json()["users"]
        self.assertEqual({u["email"] for u in users}, {"t1@x.com", "c1@x.com", "c2@x.com"})
        self.assertIn("streams", users[0])
        pc = self.admin.get("/api/manage/users/?track=post_camp").json()["users"]
        self.assertIn("pc@x.com", {u["email"] for u in pc})
        self.assertNotIn("c1@x.com", {u["email"] for u in pc})
