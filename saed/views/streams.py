"""Streams (up to six per year), the In-Camp trainer roster, the In-Camp dashboard and stream reports.

SAED / Dunis admins create streams, create and manage In-Camp trainers per stream (full CRUD, e-mail invitation,
re-activation for a later stream) and read reports filtered by stream. Everything is per stream.
"""
import csv

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (SKILL_AREAS, Course, CourseEnrollment, Lesson, LessonProgress, OrientationCamp, Profile, Stream,
                      StreamMembership)
from ..services import access, streams as svc
from ..services.notify import notify
from .base import (HasRole, _log_error, _safe_int, _send_email_async, annotate_courses, attach_course_counts,
                   clean_email, course_payload, paginate, profile_skill_keys, progress_for, skill_key)
from .courses import lesson_schedule, schedules_for

ADMINS = ("saed_admin", "dunis_admin")
SKILL_LABELS = dict(SKILL_AREAS)


def _date(value):
    from django.utils.dateparse import parse_date
    try:
        return parse_date(str(value)) if value else None
    except ValueError:
        return None


def _bad(message, fields=None, code=status.HTTP_400_BAD_REQUEST):
    body = {"error": message}
    if fields:
        body["fields"] = fields
    return Response(body, status=code)


# ─── Streams ────────────────────────────────────────────────────────────────

def stream_with_counts(stream, counts=None):
    d = svc.stream_payload(stream)
    c = counts or {}
    d["counts"] = {
        "camps": c.get("camps", 0), "courses": c.get("courses", 0), "corpers": c.get("corpers", 0),
        "trainers": c.get("trainers", 0), "pendingProposals": c.get("pending", 0),
    }
    return d


def _stream_counts(stream_ids=None):
    """{stream_id: counts} for many streams in a handful of queries."""
    out = {}

    def bump(sid, key, n):
        out.setdefault(sid, {})[key] = n
    mem = StreamMembership.objects.all()
    crs = Course.objects.filter(stream__isnull=False)
    if stream_ids is not None:
        mem, crs = mem.filter(stream_id__in=stream_ids), crs.filter(stream_id__in=stream_ids)
    for r in mem.values("stream_id", "role").annotate(n=Count("id")):
        bump(r["stream_id"], "corpers" if r["role"] == "corps_member" else "trainers", r["n"])
    for r in crs.values("stream_id").annotate(n=Count("id"), p=Count("id", filter=Q(approval_status="pending"))):
        bump(r["stream_id"], "courses", r["n"])
        bump(r["stream_id"], "pending", r["p"])
    for r in OrientationCamp.objects.filter(stream__isnull=False).values("stream_id").annotate(n=Count("id")):
        if stream_ids is None or r["stream_id"] in stream_ids:
            bump(r["stream_id"], "camps", r["n"])
    return out


class PublicStreamsView(APIView):
    """Streams a corps member can still sign up to (sign-up form)."""
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"streams": [svc.stream_payload(s, camps=True) for s in svc.open_streams()]})


def _stream_values(data, instance=None):
    """Validate stream input; returns (values, field_errors)."""
    errors, vals = {}, {}
    year = _safe_int(data.get("year", getattr(instance, "year", None)), 0)
    number = _safe_int(data.get("number", getattr(instance, "number", None)), 0)
    start = _date(data.get("startDate")) if "startDate" in data else getattr(instance, "start_date", None)
    end = _date(data.get("endDate")) if "endDate" in data else getattr(instance, "end_date", None)
    if not 2000 <= year <= 2200:
        errors["year"] = "Enter a valid year."
    if not 1 <= number <= 6:
        errors["number"] = "A year has streams 1 to 6."
    if not start:
        errors["startDate"] = "Start date is required (YYYY-MM-DD)."
    if not end:
        errors["endDate"] = "End date is required (YYYY-MM-DD)."
    if start and end and end < start:
        errors["endDate"] = "End date must be on or after the start date."
    grace = data.get("deactivationGraceDays", getattr(instance, "deactivation_grace_days", 0))
    grace = _safe_int(grace, -1)
    if not 0 <= grace <= 365:
        errors["deactivationGraceDays"] = "Grace days must be between 0 and 365."
    label = str(data.get("label", getattr(instance, "label", "")) or "").strip()[:80]
    if not errors and Stream.objects.filter(year=year, number=number).exclude(pk=getattr(instance, "pk", None)).exists():
        errors["number"] = f"Stream {number} of {year} already exists."
    vals.update(year=year, number=number, start_date=start, end_date=end, deactivation_grace_days=grace, label=label,
                notes=str(data.get("notes", getattr(instance, "notes", "")) or "").strip()[:1000])
    if "isActive" in data:
        vals["is_active"] = bool(data.get("isActive"))
    return vals, errors


class ManageStreamsView(APIView):
    permission_classes = [HasRole(*ADMINS)]

    def get(self, request):
        qs = Stream.objects.all()
        year = _safe_int(request.GET.get("year"), 0)
        if year:
            qs = qs.filter(year=year)
        rows = list(qs)
        counts = _stream_counts([s.id for s in rows])
        years = sorted(set(Stream.objects.values_list("year", flat=True)), reverse=True)
        return Response({"streams": [stream_with_counts(s, counts.get(s.id)) for s in rows], "years": years})

    def post(self, request):
        if not hasattr(request.data, "get"):
            return _bad("Send a JSON object.")
        vals, errors = _stream_values(request.data)
        if errors:
            return _bad("Please correct the highlighted fields.", errors)
        stream = Stream.objects.create(created_by=request.user, **vals)
        return Response({"stream": stream_with_counts(stream)}, status=status.HTTP_201_CREATED)


class ManageStreamDetailView(APIView):
    permission_classes = [HasRole(*ADMINS)]

    def _get(self, stream_id):
        return Stream.objects.filter(pk=stream_id).first()

    def get(self, request, stream_id):
        stream = self._get(stream_id)
        if not stream:
            return _bad("Stream not found.", code=status.HTTP_404_NOT_FOUND)
        return Response({"stream": stream_with_counts(stream, _stream_counts([stream.id]).get(stream.id))})

    def patch(self, request, stream_id):
        stream = self._get(stream_id)
        if not stream:
            return _bad("Stream not found.", code=status.HTTP_404_NOT_FOUND)
        if not hasattr(request.data, "get"):
            return _bad("Send a JSON object.")
        vals, errors = _stream_values(request.data, stream)
        if errors:
            return _bad("Please correct the highlighted fields.", errors)
        for k, v in vals.items():
            setattr(stream, k, v)
        stream.save()
        return Response({"stream": stream_with_counts(stream, _stream_counts([stream.id]).get(stream.id))})

    def delete(self, request, stream_id):
        stream = self._get(stream_id)
        if not stream:
            return _bad("Stream not found.", code=status.HTTP_404_NOT_FOUND)
        c = _stream_counts([stream.id]).get(stream.id, {})
        if any(c.get(k) for k in ("corpers", "trainers", "courses")):
            return _bad("This stream already has accounts or courses. Close it (set it inactive) instead of deleting it.",
                        code=status.HTTP_409_CONFLICT)
        stream.delete()
        return Response({"ok": True})


# ─── In-Camp trainers (SAED admin CRUD) ─────────────────────────────────────

def _membership_rows(user, memberships):
    on = svc.today()
    rows = []
    for m in sorted(memberships, key=lambda m: (-m.stream.year, -m.stream.number)):
        st = m.stream
        live = m.status == "active" and st.is_active and not st.is_past_deactivation(on)
        rows.append({"streamId": st.id, "streamName": st.name, "status": "active" if live else (
            "deactivated" if m.status == "deactivated" else "expired"),
            "startDate": st.start_date.isoformat(), "endDate": st.end_date.isoformat(),
            "deactivationDate": st.deactivation_date.isoformat(),
            "daysRemaining": svc._window(st, on) if live else None})
    return rows


def trainer_row(user, memberships, course_count=0):
    p = user.profile
    rows = _membership_rows(user, memberships)
    live = [r for r in rows if r["status"] == "active"]
    return {
        "id": user.id, "fullName": user.get_full_name() or user.email, "email": user.email, "phone": p.phone,
        "specialization": p.specialization, "specializationLabel": SKILL_LABELS.get(p.specialization, p.specialization),
        "bio": p.bio, "isActive": user.is_active, "hasPassword": user.has_usable_password(),
        "memberships": rows, "currentStreamId": live[0]["streamId"] if live else None,
        "state": "active" if live else ("expired" if rows else "none"), "courseCount": course_count,
        "lastLogin": user.last_login.isoformat() if user.last_login else None,
    }


def _send_invite(user, stream, *, reactivated=False, temp_password=False):
    base = getattr(django_settings, "FRONTEND_URL", "http://localhost:3002")
    link = f"{base}/forgot?email={user.email}"
    name = user.get_full_name() or user.email
    verb = "re-activated" if reactivated else "created"
    extra = ("\nSAED admin set a temporary password for you. For your security, please set your own password now."
             if temp_password else "")
    msg = (f"Hello {name},\n\nYour NYSC SAED In-Camp trainer account has been {verb} for {stream.name}.\n"
           f"Your account is active from {stream.start_date:%d %b %Y} until {svc.deactivation_label(stream)}; after that it "
           f"is deactivated automatically (SAED admin can re-activate it for another stream).\n{extra}\n"
           f"Set your password and sign in here: {link}\n\nNYSC SAED IMS")
    _send_email_async(subject=f"Your SAED In-Camp trainer account — {stream.name}", message=msg,
                      recipient_list=[user.email], html_message=(
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
        '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
        '<h1 style="color:#fff;margin:0;font-size:22px;">NYSC SAED IMS</h1></div>'
        '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
        f'<h2 style="color:#1a5f2a;margin-top:0;">In-Camp trainer account {verb}</h2>'
        f'<p>Hello <strong>{name}</strong>,</p>'
        f'<p>You have been added as an In-Camp trainer for <strong>{stream.name}</strong>.</p>'
        f'<p>Your account is active from <strong>{stream.start_date:%d %b %Y}</strong> until '
        f'<strong>{svc.deactivation_label(stream)}</strong>. After that it is deactivated automatically; SAED admin '
        'can re-activate it for another stream.</p>'
        f'{"<p>SAED admin set a temporary password for you. Please set your own now.</p>" if temp_password else ""}'
        f'<p style="text-align:center;margin:30px 0;"><a href="{link}" style="background:#1a5f2a;color:#fff;'
        'padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">'
        'Set your password</a></p></div></div>'))


def _trainer_queryset():
    return (User.objects.filter(profile__role="trainer", profile__account_mode="in_camp")
            .select_related("profile").prefetch_related("stream_memberships__stream"))


def _course_counts(user_ids):
    return dict(Course.objects.filter(trainer_id__in=user_ids, course_type="in_camp").values("trainer_id")
                .annotate(n=Count("id")).values_list("trainer_id", "n"))


class StreamTrainersView(APIView):
    permission_classes = [HasRole(*ADMINS)]

    def get(self, request):
        qs = _trainer_queryset()
        sid = _safe_int(request.GET.get("streamId"), 0)
        if sid:
            qs = qs.filter(stream_memberships__stream_id=sid)
        q = (request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q)
                           | Q(profile__phone__icontains=q))
        users = list(qs.distinct().order_by("first_name", "email"))
        counts = _course_counts([u.id for u in users])
        rows = [trainer_row(u, list(u.stream_memberships.all()), counts.get(u.id, 0)) for u in users]
        state = (request.GET.get("state") or "").strip()
        if state in ("active", "expired"):
            rows = [r for r in rows if r["state"] == state]
        return Response({"trainers": rows})

    def post(self, request):
        data = request.data
        if not hasattr(data, "get"):
            return _bad("Send a JSON object.")
        errors = {}
        full_name = (data.get("fullName") or "").strip()
        email = clean_email(data.get("email", ""))
        phone = (data.get("phone") or "").strip()
        password = data.get("password") or ""
        spec = skill_key(data.get("specialization")) if data.get("specialization") else ""
        stream = Stream.objects.filter(pk=_safe_int(data.get("streamId"), 0)).first()
        if len(full_name.split()) < 2:
            errors["fullName"] = "Enter first and last name."
        if not email:
            errors["email"] = "Enter a valid email address."
        elif User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
            errors["email"] = "An account with this email already exists."
        if not phone:
            errors["phone"] = "Phone number is required."
        elif Profile.objects.filter(phone=phone).exists():
            errors["phone"] = "An account with this phone number already exists."
        if stream is None:
            errors["streamId"] = "Choose a stream."
        elif not stream.is_active or stream.is_past_deactivation():
            errors["streamId"] = "This stream has ended or is closed."
        if data.get("specialization") and not spec:
            errors["specialization"] = "Choose a valid skill area."
        if password:
            try:
                validate_password(password)
            except ValidationError as exc:
                errors["password"] = " ".join(exc.messages)
        if errors:
            return _bad("Please correct the highlighted fields.", errors)
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email, email=email, password=password or None,
                    first_name=full_name.split(" ", 1)[0], last_name=full_name.split(" ", 1)[1])
                Profile.objects.create(
                    user=user, role="trainer", phone=phone, specialization=spec, bio=(data.get("bio") or "").strip(),
                    account_mode="in_camp", is_authorized=True, authorization_status="approved", has_paid=True,
                    payment_verified=True, is_email_verified=True, authorized_at=now())
                svc.join_stream(user, stream, "trainer", invited_by=request.user)
        except IntegrityError:
            return _bad("An account with this email or phone already exists.")
        _send_invite(user, stream, temp_password=bool(password))
        user = _trainer_queryset().get(pk=user.pk)
        return Response({"trainer": trainer_row(user, list(user.stream_memberships.all()))},
                        status=status.HTTP_201_CREATED)


class StreamTrainerDetailView(APIView):
    permission_classes = [HasRole(*ADMINS)]

    def _user(self, user_id):
        return _trainer_queryset().filter(pk=user_id).first()

    def _row(self, user):
        user = self._user(user.pk)
        return trainer_row(user, list(user.stream_memberships.all()), _course_counts([user.pk]).get(user.pk, 0))

    def get(self, request, user_id):
        user = self._user(user_id)
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        return Response({"trainer": self._row(user)})

    def patch(self, request, user_id):
        user = self._user(user_id)
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        data = request.data
        if not hasattr(data, "get"):
            return _bad("Send a JSON object.")
        p, errors = user.profile, {}
        if "fullName" in data:
            name = (data.get("fullName") or "").strip()
            if len(name.split()) < 2:
                errors["fullName"] = "Enter first and last name."
            else:
                user.first_name, user.last_name = name.split(" ", 1)
        if "email" in data:
            email = clean_email(data.get("email", ""))
            if not email:
                errors["email"] = "Enter a valid email address."
            elif User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exclude(pk=user.pk).exists():
                errors["email"] = "An account with this email already exists."
            else:
                if user.username.lower() == user.email.lower():
                    user.username = email
                user.email = email
        if "phone" in data:
            phone = (data.get("phone") or "").strip()
            if not phone:
                errors["phone"] = "Phone number is required."
            elif Profile.objects.filter(phone=phone).exclude(user=user).exists():
                errors["phone"] = "An account with this phone number already exists."
            else:
                p.phone = phone
        if "specialization" in data:
            spec = skill_key(data.get("specialization")) if data.get("specialization") else ""
            if data.get("specialization") and not spec:
                errors["specialization"] = "Choose a valid skill area."
            else:
                p.specialization = spec
        if "bio" in data:
            p.bio = (data.get("bio") or "").strip()
        new_stream = None
        if data.get("streamId"):
            new_stream = Stream.objects.filter(pk=_safe_int(data.get("streamId"), 0)).first()
            if new_stream is None:
                errors["streamId"] = "Stream not found."
        if errors:
            return _bad("Please correct the highlighted fields.", errors)
        with transaction.atomic():
            user.save()
            p.save()
            if new_stream is not None:
                # "Correct a mistake": move the current membership to the right stream (or add it if none is live).
                live = [m for m in user.stream_memberships.all() if m.status == "active"]
                if live and live[0].stream_id != new_stream.id:
                    target = StreamMembership.objects.filter(user=user, stream=new_stream).first()
                    if target is None:
                        live[0].stream = new_stream
                        live[0].save(update_fields=["stream"])
                    else:
                        live[0].status, live[0].deactivated_at = "deactivated", now()
                        live[0].save(update_fields=["status", "deactivated_at"])
                        svc.join_stream(user, new_stream, "trainer", invited_by=request.user)
                elif not live:
                    svc.join_stream(user, new_stream, "trainer", invited_by=request.user)
        return Response({"trainer": self._row(user)})

    def delete(self, request, user_id):
        user = self._user(user_id)
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        if Course.objects.filter(trainer=user).exists():
            return _bad("This trainer has courses. Deactivate the account instead of deleting it.",
                        code=status.HTTP_409_CONFLICT)
        user.delete()
        return Response({"ok": True})


class StreamTrainerReactivateView(APIView):
    """Re-activate a trainer for a (new) stream."""
    permission_classes = [HasRole(*ADMINS)]

    def post(self, request, user_id):
        user = _trainer_queryset().filter(pk=user_id).first()
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        stream = Stream.objects.filter(pk=_safe_int(request.data.get("streamId"), 0)).first()
        if stream is None:
            return _bad("Choose a stream.", {"streamId": "Choose a stream."})
        if not stream.is_active or stream.is_past_deactivation():
            return _bad("This stream has ended or is closed.", {"streamId": "Choose a running or upcoming stream."})
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=["is_active"])
        svc.join_stream(user, stream, "trainer", invited_by=request.user)
        notify(user, "Your In-Camp account is active", f"You have been re-activated for {stream.name}.",
               reason="stream_activated", link="/app/dashboard", email=False)
        _send_invite(user, stream, reactivated=True)
        user = _trainer_queryset().get(pk=user.pk)
        return Response({"trainer": trainer_row(user, list(user.stream_memberships.all()),
                                                _course_counts([user.pk]).get(user.pk, 0))})


class StreamTrainerDeactivateView(APIView):
    permission_classes = [HasRole(*ADMINS)]

    def post(self, request, user_id):
        user = _trainer_queryset().filter(pk=user_id).first()
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        qs = StreamMembership.objects.filter(user=user, status="active")
        sid = _safe_int(request.data.get("streamId"), 0)
        if sid:
            qs = qs.filter(stream_id=sid)
        qs.update(status="deactivated", deactivated_at=now())
        if not StreamMembership.objects.filter(user=user, status="active").exists():
            Profile.objects.filter(user=user).update(in_camp_access_active=False, in_camp_deactivated_at=now())
        user = _trainer_queryset().get(pk=user.pk)
        return Response({"trainer": trainer_row(user, list(user.stream_memberships.all()),
                                                _course_counts([user.pk]).get(user.pk, 0))})


class StreamTrainerInviteView(APIView):
    """Send the invitation e-mail again (set-password link)."""
    permission_classes = [HasRole(*ADMINS)]

    def post(self, request, user_id):
        user = _trainer_queryset().filter(pk=user_id).first()
        if not user:
            return _bad("Trainer not found.", code=status.HTTP_404_NOT_FOUND)
        lc = svc.lifecycle(user)
        stream = Stream.objects.filter(pk=lc.get("streamId")).first()
        if not lc["isActive"] or stream is None:
            return _bad("Re-activate this trainer for a stream before sending an invitation.")
        _send_invite(user, stream)
        return Response({"ok": True, "message": f"Invitation sent to {user.email}."})


class RunStreamExpiryView(APIView):
    """Persist expiry for every finished stream (cron/management command does the same)."""
    permission_classes = [HasRole(*ADMINS)]

    def post(self, request):
        try:
            counts = svc.expire_memberships()
        except Exception as exc:  # pragma: no cover - defensive
            _log_error("Stream expiry failed", exc=exc)
            return _bad("Stream expiry failed.", code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"ok": True, "deactivatedCount": sum(counts.values()), "byRole": counts})


# ─── In-Camp dashboard (corps member + trainer) ─────────────────────────────

class InCampDashboardView(APIView):
    """The In-Camp portal home. Also the only data an expired In-Camp account can still reach."""
    permission_classes = [HasRole("corps_member", "trainer")]

    def get(self, request):
        user = request.user
        if svc.track_of(user) != svc.IN_CAMP:
            return _bad("The In-Camp dashboard is only for In-Camp accounts.", code=status.HTTP_403_FORBIDDEN)
        role = access.role_of(user)
        lc = svc.lifecycle(user)
        out = {"role": role, "track": "in_camp", "lifecycle": lc, "stats": {}, "courses": [], "schedule": []}
        if not lc["isActive"]:
            return Response(out)
        ids = lc["streamIds"]
        if role == "trainer":
            mine = Course.objects.filter(trainer=user, course_type="in_camp", stream_id__in=ids)
            agg = mine.aggregate(total=Count("id"), pending=Count("id", filter=Q(approval_status="pending")),
                                 approved=Count("id", filter=Q(approval_status="approved")),
                                 declined=Count("id", filter=Q(approval_status="declined")))
            enrolled = CourseEnrollment.objects.filter(course__in=mine, status="confirmed")
            out["stats"] = {"courses": agg["total"], "pending": agg["pending"], "open": agg["approved"],
                            "declined": agg["declined"], "learners": enrolled.values("student").distinct().count(),
                            "lessons": Lesson.objects.filter(course__in=mine).count()}
            items = list(annotate_courses(mine).order_by("-created_at")[:6])
            sched = schedules_for(items)
            out["courses"] = [{**course_payload(c, request), "scheduledLessons": lesson_schedule(c, rows=sched.get(c.id, []))}
                              for c in items]
            return Response(out)
        profile = user.profile
        mine_skills = profile_skill_keys(profile)
        avail = Course.objects.filter(course_type="in_camp", is_active=True, is_published=True, is_restricted=False,
                                      approval_status="approved").filter(Q(stream_id__in=ids) | Q(stream__isnull=True))
        enrol = CourseEnrollment.objects.filter(student=user, status="confirmed", course__in=avail)
        out["stats"] = {"available": avail.count(), "inMySkillSet": avail.filter(category__in=mine_skills).count(),
                        "enrolled": enrol.count(),
                        "completedLessons": LessonProgress.objects.filter(student=user, lesson__course__in=avail).count()}
        out["mySkills"] = [{"value": k, "label": SKILL_LABELS.get(k, k)} for k in mine_skills]
        recent = list(annotate_courses(avail.filter(enrollments__student=user, enrollments__status="confirmed"))
                      .order_by("-created_at")[:6])
        attach_course_counts(recent)
        prog = progress_for(user, [c.id for c in recent])
        out["courses"] = [{**course_payload(c, request), "progress": prog.get(c.id)} for c in recent]
        today = svc.today()
        rows = Lesson.objects.filter(course__in=avail, is_published=True, scheduled_date__gte=today) \
            .select_related("course").order_by("scheduled_date", "scheduled_time")[:6]
        out["schedule"] = [{"id": l.id, "title": l.title, "course": l.course.title, "courseId": str(l.course.public_id),
                            "scheduledDate": l.scheduled_date.isoformat(),
                            "scheduledTime": l.scheduled_time.isoformat() if l.scheduled_time else None} for l in rows]
        return Response(out)


# ─── Reports ────────────────────────────────────────────────────────────────

def _skill_breakdown(profiles):
    counts = {}
    for p in profiles:
        for k in (profile_skill_keys(p) or ["unspecified"]):
            counts[k] = counts.get(k, 0) + 1
    return sorted(({"skill": k, "label": SKILL_LABELS.get(k, "Not specified"), "count": n} for k, n in counts.items()),
                  key=lambda r: -r["count"])


def stream_report(stream):
    on = svc.today()
    mem = StreamMembership.objects.filter(stream=stream).select_related("user__profile")
    live = lambda m: m.status == "active" and stream.is_active and not stream.is_past_deactivation(on)  # noqa: E731
    corp = [m for m in mem if m.role == "corps_member"]
    train = [m for m in mem if m.role == "trainer"]
    corp_profiles = [m.user.profile for m in corp]
    by_camp = {}
    for p in corp_profiles:
        name = p.orientation_camp.name if p.orientation_camp_id else "No camp selected"
        by_camp[name] = by_camp.get(name, 0) + 1
    courses = Course.objects.filter(stream=stream)
    cagg = courses.aggregate(total=Count("id"), pending=Count("id", filter=Q(approval_status="pending")),
                             approved=Count("id", filter=Q(approval_status="approved")),
                             declined=Count("id", filter=Q(approval_status="declined")),
                             published=Count("id", filter=Q(is_published=True)))
    enrol = CourseEnrollment.objects.filter(course__stream=stream, status="confirmed")
    learners = enrol.values("student").distinct().count()
    lesson_total = Lesson.objects.filter(course__stream=stream).count()
    completions = LessonProgress.objects.filter(lesson__course__stream=stream).count()
    top = (annotate_courses(courses).filter(approval_status="approved").order_by("-_enrolled_count")[:5])
    trainer_ids = {m.user_id for m in train}
    proposing = courses.values("trainer").distinct().count()
    return {
        "stream": svc.stream_payload(stream),
        "corpers": {"total": len(corp), "active": sum(1 for m in corp if live(m)),
                    "expired": sum(1 for m in corp if not live(m)),
                    "withEnrolment": learners, "withoutEnrolment": max(len(corp) - learners, 0),
                    "bySkill": _skill_breakdown(corp_profiles),
                    "byCamp": sorted(({"camp": k, "count": v} for k, v in by_camp.items()), key=lambda r: -r["count"])},
        "trainers": {"total": len(train), "active": sum(1 for m in train if live(m)),
                     "expired": sum(1 for m in train if not live(m)),
                     "withProposals": proposing, "withoutProposals": max(len(trainer_ids) - proposing, 0),
                     "bySkill": _skill_breakdown([m.user.profile for m in train])},
        "courses": {**cagg, "lessons": lesson_total, "enrolments": enrol.count(), "lessonCompletions": completions,
                    "avgLearnersPerCourse": round(enrol.count() / cagg["approved"], 1) if cagg["approved"] else 0},
        "topCourses": [{"id": str(c.public_id), "title": c.title, "trainer": c.trainer.get_full_name() if c.trainer else "",
                        "enrolled": c._enrolled_count} for c in top],
    }


def post_camp_report():
    p = Profile.objects.filter(account_mode="post_camp")
    corp = p.filter(role="corps_member")
    train = p.filter(role="trainer")
    courses = Course.objects.filter(course_type="post_camp")
    return {
        "corpers": {"total": corp.count(), "bySkill": _skill_breakdown(list(corp))},
        "trainers": {"total": train.count(), "approved": train.filter(is_authorized=True).count(),
                     "pending": train.filter(authorization_status="pending").count(),
                     "bySkill": _skill_breakdown(list(train))},
        "courses": {"total": courses.count(), "published": courses.filter(is_published=True).count(),
                    "enrolments": CourseEnrollment.objects.filter(course__course_type="post_camp",
                                                                  status="confirmed").count()},
    }


class StreamReportView(APIView):
    """Per-stream report (corps members, trainers, courses, engagement) plus the separate Post-Camp summary."""
    permission_classes = [HasRole(*ADMINS)]

    def get(self, request):
        qs = Stream.objects.all()
        sid, year = _safe_int(request.GET.get("streamId"), 0), _safe_int(request.GET.get("year"), 0)
        if sid:
            qs = qs.filter(pk=sid)
        elif year:
            qs = qs.filter(year=year)
        reports = [stream_report(s) for s in qs]
        total = {"corpers": sum(r["corpers"]["total"] for r in reports),
                 "activeCorpers": sum(r["corpers"]["active"] for r in reports),
                 "trainers": sum(r["trainers"]["total"] for r in reports),
                 "activeTrainers": sum(r["trainers"]["active"] for r in reports),
                 "courses": sum(r["courses"]["total"] for r in reports),
                 "pendingProposals": sum(r["courses"]["pending"] for r in reports),
                 "enrolments": sum(r["courses"]["enrolments"] for r in reports)}
        return Response({"streams": reports, "totals": total, "postCamp": post_camp_report(),
                         "years": sorted(set(Stream.objects.values_list("year", flat=True)), reverse=True),
                         "generatedAt": now().isoformat()})


def _safe_cell(value):
    """Neutralise spreadsheet formula injection in CSV exports."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


class StreamReportExportView(APIView):
    """CSV download: kind = corpers | trainers | courses, optionally for one stream."""
    permission_classes = [HasRole(*ADMINS)]

    def get(self, request):
        kind = (request.GET.get("kind") or "").strip()
        if kind not in ("corpers", "trainers", "courses"):
            return _bad("kind must be corpers, trainers or courses.")
        sid = _safe_int(request.GET.get("streamId"), 0)
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="saed-{kind}{f"-stream-{sid}" if sid else ""}.csv"'
        w = csv.writer(resp)
        on = svc.today()
        if kind in ("corpers", "trainers"):
            role = "corps_member" if kind == "corpers" else "trainer"
            mem = StreamMembership.objects.filter(role=role).select_related("user__profile", "stream",
                                                                          "user__profile__orientation_camp")
            if sid:
                mem = mem.filter(stream_id=sid)
            w.writerow(["Stream", "Full name", "Email", "Phone", "NYSC state code", "Skill set", "Camp", "Status",
                        "Account ends"])
            for m in mem.order_by("-stream__year", "-stream__number", "user__first_name"):
                p, st = m.user.profile, m.stream
                live = m.status == "active" and st.is_active and not st.is_past_deactivation(on)
                skills = ", ".join(SKILL_LABELS.get(k, k) for k in profile_skill_keys(p)) or SKILL_LABELS.get(p.specialization, "")
                w.writerow([_safe_cell(x) for x in [
                    st.name, m.user.get_full_name(), m.user.email, p.phone, p.nysc_state_code, skills,
                    p.orientation_camp.name if p.orientation_camp_id else "",
                    "Active" if live else ("Deactivated" if m.status == "deactivated" else "Expired"),
                    st.deactivation_date.isoformat()]])
        else:
            qs = Course.objects.filter(course_type="in_camp").select_related("trainer", "stream")
            if sid:
                qs = qs.filter(stream_id=sid)
            qs = annotate_courses(qs).order_by("-created_at")
            w.writerow(["Stream", "Course", "Skill", "Trainer", "Status", "Published", "Lessons", "Enrolled"])
            for c in qs:
                w.writerow([_safe_cell(x) for x in [
                    c.stream.name if c.stream_id else "", c.title, SKILL_LABELS.get(c.category, c.category),
                    c.trainer.get_full_name() if c.trainer else "", c.get_approval_status_display(),
                    "Yes" if c.is_published else "No", c._lesson_count, c._enrolled_count]])
        return resp
