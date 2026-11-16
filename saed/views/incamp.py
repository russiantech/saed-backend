"""
In-Camp SAED views:
- Orientation camp management
- In-Camp registration helpers
- Automatic deactivation task
- Corps member In-Camp dashboard data
"""

from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils.dateparse import parse_date, parse_time
from django.utils.timezone import now
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Course, OrientationCamp, Profile
from ..services import access
from .base import (
    HasRole,
    IsAuthenticatedAPI,
    _log_error,
    _log_info,
    annotate_courses,
    course_payload,
    paginate,
    profile_skill_keys,
    program_categories_payload,
    skill_key,
)
from .courses import filter_catalogue, get_course, lesson_schedule, schedules_for


def _as_date(value):
    """Accept date, datetime, or ISO date string; return date or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        parsed = parse_date(value.strip()[:10])
        if parsed:
            return parsed
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            return None
    return None


def _as_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        return parse_time(value.strip()) or None
    return None


def _iso_date(value):
    if not value:
        return None
    if isinstance(value, str):
        return value[:10]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _iso_time(value):
    if not value:
        return None
    if isinstance(value, str):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


# ─── Payload helpers ─────────────────────────────────────────────────────────

def orientation_camp_payload(camp):
    start = _as_date(getattr(camp, "start_date", None)) or getattr(camp, "start_date", None)
    end = _as_date(getattr(camp, "end_date", None)) or getattr(camp, "end_date", None)
    deactivation = None
    try:
        deactivation = camp.deactivation_date
    except Exception:
        if end:
            try:
                grace = int(getattr(camp, "deactivation_grace_days", 7) or 7)
                deactivation = _as_date(end) + timedelta(days=grace)
            except Exception:
                deactivation = None
    created = getattr(camp, "created_at", None)
    return {
        "id": camp.id,
        "name": camp.name,
        "state": camp.state,
        "location": camp.location,
        "startDate": _iso_date(start),
        "endDate": _iso_date(end),
        "deactivationGraceDays": camp.deactivation_grace_days,
        "deactivationDate": _iso_date(deactivation),
        "isActive": camp.is_active,
        "createdAt": created.isoformat() if created and hasattr(created, "isoformat") else (str(created) if created else None),
    }


# ─── Orientation Camp CRUD (Admin) ───────────────────────────────────────────

class PublicOrientationCampsView(APIView):
    """Active orientation camps for In-Camp signup (public)."""
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        camps = OrientationCamp.objects.filter(is_active=True).order_by("-start_date")
        return Response({"camps": [orientation_camp_payload(c) for c in camps]})


class ManageOrientationCampsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        from django.db.models import Count
        camps = OrientationCamp.objects.annotate(
            _courses=Count("courses", distinct=True), _corpers=Count("corps_members", distinct=True)).order_by("-start_date", "-id")
        out = []
        for c in camps:
            d = orientation_camp_payload(c)
            d["courseCount"], d["corperCount"] = c._courses, c._corpers
            out.append(d)
        return Response({"camps": out})

    def post(self, request):
        data = request.data
        if not hasattr(data, "get"):
            return Response({"error": "Send a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        name = (data.get("name") or "").strip()
        state = (data.get("state") or "").strip()
        start = _as_date(data.get("startDate"))
        end = _as_date(data.get("endDate"))
        if not name or not state or not start or not end:
            return Response(
                {"error": "name, state, startDate and endDate are required (use YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if end < start:
            return Response(
                {"error": "endDate must be on or after startDate."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        grace = data.get("deactivationGraceDays", 7)
        try:
            grace = int(grace)
        except (TypeError, ValueError):
            grace = 7
        if not 0 <= grace <= 365:
            return Response({"error": "Grace days must be between 0 and 365."}, status=status.HTTP_400_BAD_REQUEST)
        if OrientationCamp.objects.filter(name__iexact=name, state__iexact=state, start_date=start).exists():
            return Response({"error": "This camp (same name, state and start date) already exists."},
                            status=status.HTTP_409_CONFLICT)
        camp = OrientationCamp.objects.create(
            name=name,
            state=state,
            location=(data.get("location") or "").strip(),
            start_date=start,
            end_date=end,
            deactivation_grace_days=grace,
            is_active=bool(data.get("isActive", True)),
        )
        camp.refresh_from_db()
        return Response(
            {"camp": orientation_camp_payload(camp)}, status=status.HTTP_201_CREATED
        )


class ManageOrientationCampDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def patch(self, request, camp_id):
        try:
            camp = OrientationCamp.objects.get(id=camp_id)
        except OrientationCamp.DoesNotExist:
            return Response({"error": "Camp not found."}, status=status.HTTP_404_NOT_FOUND)
        data = request.data
        if not hasattr(data, "get"):
            return Response({"error": "Send a JSON object."}, status=status.HTTP_400_BAD_REQUEST)
        if "name" in data:
            camp.name = (data.get("name") or "").strip()
        if "state" in data:
            camp.state = (data.get("state") or "").strip()
        if "location" in data:
            camp.location = (data.get("location") or "").strip()
        if "startDate" in data:
            parsed = _as_date(data.get("startDate"))
            if not parsed:
                return Response({"error": "Invalid startDate (use YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST)
            camp.start_date = parsed
        if "endDate" in data:
            parsed = _as_date(data.get("endDate"))
            if not parsed:
                return Response({"error": "Invalid endDate (use YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST)
            camp.end_date = parsed
        if "deactivationGraceDays" in data:
            try:
                camp.deactivation_grace_days = int(data.get("deactivationGraceDays"))
            except (TypeError, ValueError):
                pass
        if "isActive" in data:
            camp.is_active = bool(data.get("isActive"))
        if camp.end_date and camp.start_date and camp.end_date < camp.start_date:
            return Response({"error": "endDate must be on or after startDate."}, status=status.HTTP_400_BAD_REQUEST)
        camp.save()
        camp.refresh_from_db()
        return Response({"camp": orientation_camp_payload(camp)})

    def delete(self, request, camp_id):
        try:
            camp = OrientationCamp.objects.get(id=camp_id)
        except OrientationCamp.DoesNotExist:
            return Response({"error": "Camp not found."}, status=status.HTTP_404_NOT_FOUND)
        used_courses = camp.courses.count()
        used_corpers = camp.corps_members.count()
        if used_courses or used_corpers:
            return Response({"error": f"This camp is in use ({used_courses} course(s), {used_corpers} corps member(s)). "
                                      "Deactivate it instead of deleting it.", "courseCount": used_courses,
                             "corperCount": used_corpers}, status=status.HTTP_409_CONFLICT)
        camp.delete()
        return Response({"ok": True})


# ─── Corps Member In-Camp Dashboard ──────────────────────────────────────────

class InCampCoursesView(APIView):
    """The In-Camp SAED catalogue: every course with course_type = in_camp. One endpoint, one shape, all roles.

    * corps_member  -> every published In-Camp course (not limited to their own camp or to enrolled courses)
    * trainer       -> the trainer's OWN In-Camp courses (drafts included) so they see what corps members see
    * admins        -> every In-Camp course
    * newest first, paginated, filterable by year / month / camp / skill / search
    * each course carries its scheduled lessons so the timetable needs no separate page
    """
    permission_classes = [HasRole("corps_member", "trainer", "saed_admin", "dunis_admin")]

    def get(self, request):
        role = access.role_of(request.user)
        camps = OrientationCamp.objects.filter(is_active=True).order_by("-start_date")
        camps_payload = [{"id": k.id, "name": k.name, "state": k.state} for k in camps]
        base = {"role": role, "accessActive": True, "orientationCamp": None}
        qs = Course.objects.filter(course_type="in_camp", is_active=True)
        enrolled = set()
        skills = program_categories_payload()
        labels = {s["value"]: s["label"] for s in skills}
        my_skills = []
        if role == "corps_member":
            profile = getattr(request.user, "profile", None)
            if profile is None:
                return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)
            base = {"role": role, "accessActive": profile.in_camp_access_active,
                    "orientationCamp": orientation_camp_payload(profile.orientation_camp) if profile.orientation_camp else None}
            if not profile.in_camp_access_active:
                return Response({**base, "message": "Your In-Camp access has ended. Post-Camp courses remain available.",
                                 "courses": [], "camps": camps_payload, "skills": skills,
                                 "pagination": {"page": 1, "pageSize": 12, "total": 0, "totalPages": 1}})
            qs = qs.filter(is_published=True, is_restricted=False)
            enrolled = set(request.user.course_enrollments.filter(status="confirmed").values_list("course_id", flat=True))
            my_skills = profile_skill_keys(profile)
        elif role == "trainer":
            qs = qs.filter(trainer=request.user)
        qs = filter_catalogue(request, qs)

        # Skill set handling. `skill` may be: "" / "mine" (default: the corps member's own skill set), "all",
        # or a specific skill. Corps members see their own skill set first; if nothing is listed under it the
        # catalogue is held back (noSkillMatch) so the page can say so and let them explore the rest on request.
        asked = (request.GET.get("skill") or request.GET.get("category") or "").strip()
        specific = skill_key(asked) or ("" if asked.lower() in ("", "all", "mine") else asked)
        mode = "specific" if specific else ("all" if asked.lower() == "all" or not my_skills else "mine")
        no_match = False
        order = ["-start_date", "-created_at", "-id"]
        if my_skills and mode != "specific":
            from django.db.models import Case, IntegerField, Value, When
            if mode == "mine" and not qs.filter(category__in=my_skills).exists():
                no_match = True
                qs = qs.none()
            else:
                qs = qs.annotate(_skill_rank=Case(When(category__in=my_skills, then=Value(0)),
                                                  default=Value(1), output_field=IntegerField()))
                order = ["_skill_rank"] + order
        qs = annotate_courses(qs).order_by(*order)
        items, pagination = paginate(request, qs)
        courses = []
        schedules = schedules_for(items)
        for c in items:
            payload = course_payload(c, request)
            payload["matchesMySkills"] = c.category in my_skills
            payload["isEnrolled"] = c.id in enrolled
            payload["isPublished"] = c.is_published
            payload["isRestricted"] = c.is_restricted
            payload["scheduledLessons"] = lesson_schedule(c, rows=schedules.get(c.id, []))
            courses.append(payload)
        return Response({
            **base, "courses": courses, "pagination": pagination, "camps": camps_payload,
            "skills": skills,
            "mySkills": [{"value": k, "label": labels.get(k, k)} for k in my_skills],
            "skillMode": mode,
            "selectedSkill": {"value": specific, "label": labels.get(specific, specific)} if specific else None,
            "noSkillMatch": no_match,
        })


# ─── Automatic In-Camp Deactivation ──────────────────────────────────────────

def deactivate_expired_in_camp_accounts():
    """
    Background-safe function: deactivate In-Camp access for corps members
    whose orientation camp ended + grace period has passed.
    Does NOT delete accounts or touch Post-Camp access.
    Call from management command / celery / cron.
    """
    today = now().date()
    deactivated = 0
    camps = OrientationCamp.objects.filter(is_active=True)
    for camp in camps:
        if not camp.is_past_deactivation():
            continue
        qs = Profile.objects.filter(
            role="corps_member",
            orientation_camp=camp,
            in_camp_access_active=True,
        )
        count = qs.update(
            in_camp_access_active=False,
            in_camp_deactivated_at=now(),
        )
        deactivated += count
        _log_info(
            f"Deactivated {count} In-Camp accounts for camp {camp.name}",
            extra={"camp_id": camp.id, "deactivation_date": str(camp.deactivation_date)},
        )
    return deactivated


class RunInCampDeactivationView(APIView):
    """
    Admin-triggered or cron-triggered endpoint to run deactivation.
    Prefer a management command + cron in production.
    """
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request):
        try:
            count = deactivate_expired_in_camp_accounts()
            return Response({"ok": True, "deactivatedCount": count})
        except Exception as exc:
            _log_error("In-Camp deactivation failed", exc=exc)
            return Response(
                {"error": "Deactivation task failed."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
