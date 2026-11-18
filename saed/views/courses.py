"""Course views: public catalogue, trainer CRUD, admin restrict/unrestrict, enrolment, progress.

Hierarchy is Course → Lessons. There is no course price: enrolment is free and
individual lessons decide whether extra payment is needed.
"""
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Connection, Course, CourseEnrollment, Lesson, LessonProgress, OrientationCamp
from ..models import Stream
from ..services import access, streams as stream_svc
from ..services.notify import course_link, notify
from .base import (
    HasRole, IsAuthenticatedAPI, _log_error, _parse_date, _resolve_course_dates, _safe_int,
    annotate_courses, attach_course_counts, course_payload, ensure_trainer_connection, lesson_payload, paginate, progress_for,
    program_categories_payload, role_for, skill_key, trainer_public_payload,
)

COURSE_FIELD_MAP = {
    "title": "title", "description": "description", "category": "category",
    "durationWeeks": "duration_weeks", "startDate": "start_date", "endDate": "end_date",
    "maxStudents": "max_students", "isActive": "is_active", "courseType": "course_type",
    "orientationCampId": "orientation_camp_id", "learningObjectives": "learning_objectives",
    "prerequisites": "prerequisites", "trainingLocation": "training_location",
    "trainingLga": "training_lga", "trainingState": "training_state",
    "isPublished": "is_published", "location": "location",
}


def get_course(ref, qs=None):
    """Course by public UUID or legacy integer id; raises Course.DoesNotExist."""
    return access.resolve_course(ref, qs if qs is not None else Course.objects.all())


def _not_found():
    return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)


def filter_catalogue(request, qs):
    """Shared search/filter logic for the Courses and In-Camp pages."""
    g = request.GET
    q = (g.get("q") or g.get("search") or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(trainer__first_name__icontains=q)
            | Q(trainer__last_name__icontains=q) | Q(training_location__icontains=q)
        )
    ctype = (g.get("courseType") or g.get("type") or "").strip()
    if ctype in ("in_camp", "post_camp"):
        qs = qs.filter(course_type=ctype)
    skill = (g.get("skill") or g.get("category") or "").strip()
    if skill and skill.lower() not in ("all", "mine"):
        qs = qs.filter(category=skill_key(skill) or skill)
    state = (g.get("state") or "").strip()
    if state:
        qs = qs.filter(Q(training_state__icontains=state) | Q(orientation_camp__state__icontains=state))
    lga = (g.get("lga") or "").strip()
    if lga:
        qs = qs.filter(Q(training_lga__icontains=lga) | Q(training_location__icontains=lga))
    loc = (g.get("location") or "").strip()
    if loc:
        qs = qs.filter(Q(training_location__icontains=loc) | Q(location__icontains=loc))
    camp = (g.get("campId") or g.get("camp") or "").strip()
    if camp.isdigit():
        qs = qs.filter(orientation_camp_id=int(camp))
    stream_id = (g.get("streamId") or g.get("stream") or "").strip()
    if stream_id.isdigit():
        qs = qs.filter(stream_id=int(stream_id))
    approval = (g.get("approval") or "").strip()
    if approval in ("pending", "approved", "declined"):
        qs = qs.filter(approval_status=approval)
    trainer = (g.get("trainerId") or "").strip()
    if trainer.isdigit():
        qs = qs.filter(trainer_id=int(trainer))
    year, month = _safe_int(g.get("year"), 0), _safe_int(g.get("month"), 0)
    if year:
        qs = qs.filter(Q(start_date__year=year) | Q(orientation_camp__start_date__year=year)
                       | Q(lessons__scheduled_date__year=year))
    if month:
        qs = qs.filter(Q(start_date__month=month) | Q(orientation_camp__start_date__month=month)
                       | Q(lessons__scheduled_date__month=month))
    if year or month:
        qs = qs.distinct()
    return qs


def visible_courses():
    """Published, active, unrestricted courses (the corps-member catalogue)."""
    return Course.objects.filter(is_active=True, is_published=True, is_restricted=False)


class CourseListView(APIView):
    """Catalogue of published courses, newest first, with search/filter/pagination."""
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            qs = filter_catalogue(request, visible_courses())
            user = request.user
            if not (user.is_authenticated and access.is_admin(user)):
                # People only ever see their own programme. Anonymous visitors and Post-Camp accounts: Post-Camp
                # courses; In-Camp accounts: In-Camp courses of their running stream (the In-Camp page is the home).
                if stream_svc.track_of(user) == stream_svc.IN_CAMP:
                    lc = stream_svc.lifecycle(user)
                    qs = qs.filter(course_type="in_camp", stream_id__in=lc["streamIds"]) if lc["isActive"] else qs.none()
                else:
                    qs = qs.filter(course_type="post_camp")
            qs = annotate_courses(qs).order_by("-created_at", "-id")
            items, pagination = paginate(request, qs)
            return Response({
                "courses": [course_payload(c, request) for c in items],
                "categories": program_categories_payload(),
                "pagination": pagination,
            })
        except Exception as exc:
            _log_error("Course list error", exc=exc)
            return Response({"error": "Failed to load courses."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def schedules_for(courses, limit=8):
    """{course_id: [lesson, ...]} for a page of courses in ONE query."""
    from ..models import Lesson
    out = {}
    ids = [c.id for c in courses]
    for l in Lesson.objects.filter(course_id__in=ids, is_published=True, scheduled_date__isnull=False) \
            .order_by("scheduled_date", "scheduled_time"):
        rows = out.setdefault(l.course_id, [])
        if len(rows) < limit:
            rows.append(l)
    return out


def lesson_schedule(course, limit=8, rows=None):
    """Upcoming/ordered scheduled lessons for timetable display (no content, no access info)."""
    if rows is None:
        rows = course.lessons.filter(is_published=True, scheduled_date__isnull=False).order_by("scheduled_date", "scheduled_time")[:limit]
    return [{"id": l.id, "title": l.title, "scheduledDate": l.scheduled_date.isoformat(),
             "scheduledTime": l.scheduled_time.isoformat() if l.scheduled_time else None,
             "contentType": l.content_type, "requiresPayment": l.requires_payment(), "price": str(l.price or 0)}
            for l in rows]


def _validate_course(data, partial=False):
    fields = {}
    title = (data.get("title") or "").strip()
    if not partial and not title:
        fields["title"] = "Title is required."
    if "title" in data and not title:
        fields["title"] = "Title is required."
    ctype = data.get("courseType")
    if ctype is not None and ctype not in ("in_camp", "post_camp"):
        fields["courseType"] = "Choose In-Camp or Post-Camp."
    ms = data.get("maxStudents")
    if ms not in (None, ""):
        try:
            if int(ms) < 1:
                raise ValueError
        except (TypeError, ValueError):
            fields["maxStudents"] = "Enter a valid number of students."
    return fields


class ManageCoursesView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        qs = annotate_courses(Course.objects.filter(trainer=request.user)).order_by("-created_at")
        ctype = request.GET.get("courseType")
        if ctype in ("in_camp", "post_camp"):
            qs = qs.filter(course_type=ctype)
        return Response({"courses": [course_payload(c, request) for c in qs]})

    def post(self, request):
        data = _resolve_course_dates(dict(request.data))
        fields = _validate_course(data)
        track = stream_svc.track_of(request.user) or "post_camp"
        course_type = data.get("courseType") or track
        if course_type != track:
            return Response({"error": f"{'In-Camp' if track == 'in_camp' else 'Post-Camp'} trainers can only create "
                                      f"{'In-Camp' if track == 'in_camp' else 'Post-Camp'} courses."},
                            status=status.HTTP_403_FORBIDDEN)
        stream = None
        if track == "in_camp":
            lc = stream_svc.lifecycle(request.user)
            ids = lc.get("streamIds") or []
            wanted = _safe_int(data.get("streamId"), 0) or (ids[0] if ids else 0)
            if wanted not in ids:
                return Response({"error": "Choose one of your active streams for this In-Camp course."},
                                status=status.HTTP_400_BAD_REQUEST)
            stream = Stream.objects.get(pk=wanted)
        camp = None
        camp_id = data.get("orientationCampId") or None
        if camp_id:
            camp = OrientationCamp.objects.filter(pk=camp_id).first()
            if not camp:
                fields["orientationCampId"] = "Orientation camp not found."
            elif stream is not None and camp.stream_id not in (None, stream.id):
                fields["orientationCampId"] = "This camp belongs to a different stream."
        start, end = _parse_date(data.get("startDate")), _parse_date(data.get("endDate"))
        if course_type == "in_camp":
            if camp:
                start, end = start or camp.start_date, end or camp.end_date
            elif stream is not None:
                start, end = start or stream.start_date, end or stream.end_date
        if not start:
            fields["startDate"] = "Start date is required."
        if not end:
            fields["endDate"] = "End date is required."
        if start and end and end < start:
            fields["endDate"] = "End date must be after start date."
        if fields:
            return Response({"error": f"Please correct: {', '.join(fields)}", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                course = Course.objects.create(
                    trainer=request.user, title=data["title"].strip(),
                    description=(data.get("description") or "").strip(),
                    category=(data.get("category") or "").strip(),
                    duration_weeks=_safe_int(data.get("durationWeeks"), 4) or 4,
                    start_date=start, end_date=end,
                    max_students=_safe_int(data.get("maxStudents"), 40) or 40,
                    course_type=course_type, orientation_camp=camp,
                    learning_objectives=data.get("learningObjectives") if isinstance(data.get("learningObjectives"), list) else [],
                    prerequisites=(data.get("prerequisites") or "").strip(),
                    training_location=(data.get("trainingLocation") or "").strip(),
                    training_lga=(data.get("trainingLga") or "").strip(),
                    training_state=(data.get("trainingState") or "").strip(),
                    # In-Camp courses are proposals: SAED admin "opens" (approves + publishes) them for the stream.
                    is_published=bool(data.get("isPublished", False)) and course_type != "in_camp",
                    stream=stream,
                    approval_status="pending" if course_type == "in_camp" else "approved",
                    location=(data.get("location") or data.get("trainingLocation") or "Lagos")[:120],
                )
            if course.is_published:
                announce_course_published(course)
            if course.course_type == "in_camp":
                from ..services.notify import notify_admins
                notify_admins("In-Camp course proposal",
                              f"{request.user.get_full_name() or request.user.email} proposed “{course.title}” "
                              f"for {stream.name if stream else 'a stream'}.", reason="course_proposal",
                              link="/app/proposals")
            return Response({"course": course_payload(course, request)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Course creation error", exc=exc)
            return Response({"error": "Failed to create course."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def announce_course_published(course):
    """Tell the trainer's connected corps members (in-app) that a course is available."""
    link = course_link(course)
    trainer_name = course.trainer.get_full_name() if course.trainer else "A trainer"
    members = Connection.objects.filter(trainer=course.trainer, status="active").select_related("corps_member")[:500]
    for conn in members:
        notify(conn.corps_member, "New course available",
               f"{trainer_name} published “{course.title}”.", reason="course_published", link=link, email=False)
    if course.trainer:
        notify(course.trainer, "Course published", f"“{course.title}” is now live.",
               reason="course_published", link=link, email=False)


class ManageCourseDetailView(APIView):
    permission_classes = [HasRole("trainer")]

    def _course(self, request, ref):
        return get_course(ref, Course.objects.filter(trainer=request.user))

    def get(self, request, course_id):
        try:
            course = self._course(request, course_id)
        except Course.DoesNotExist:
            return _not_found()
        lessons = course.lessons.all().order_by("order", "id")
        return Response({
            "course": course_payload(course, request),
            "lessons": [lesson_payload(l, request, request.user, manage=True) for l in lessons],
        })

    def patch(self, request, course_id):
        try:
            course = self._course(request, course_id)
        except Course.DoesNotExist:
            return _not_found()
        data = _resolve_course_dates(dict(request.data))
        fields = _validate_course(data, partial=True)
        if fields:
            return Response({"error": f"Please correct: {', '.join(fields)}", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)
        was_published = course.is_published
        for key, model_field in COURSE_FIELD_MAP.items():
            if key not in data:
                continue
            value = data[key]
            if model_field in ("duration_weeks",):
                value = _safe_int(value, 4) or 4
            elif model_field == "max_students":
                value = _safe_int(value, 40) or 40
            elif model_field in ("is_active", "is_published"):
                value = bool(value)
            elif model_field in ("start_date", "end_date"):
                value = _parse_date(value)
            elif model_field == "learning_objectives" and not isinstance(value, list):
                value = []
            elif model_field == "orientation_camp_id":
                value = value or None
            elif isinstance(value, str):
                value = value.strip()
            setattr(course, model_field, value)
        if course.start_date and course.end_date and course.end_date < course.start_date:
            return Response({"error": "End date must be after start date.", "fields": {"endDate": "End date must be after start date."}},
                            status=status.HTTP_400_BAD_REQUEST)
        if course.course_type == "in_camp":
            if course.approval_status != "approved":
                if course.is_published:
                    return Response({"error": "This In-Camp course must be opened by SAED admin before it can be published.",
                                     "fields": {"isPublished": "Awaiting SAED approval."}}, status=status.HTTP_400_BAD_REQUEST)
                if course.approval_status == "declined":  # editing a declined proposal resubmits it
                    course.approval_status, course.review_note = "pending", ""
        course.save()
        if course.is_published and not was_published:
            announce_course_published(course)
        return Response({"course": course_payload(course, request)})

    def delete(self, request, course_id):
        try:
            course = self._course(request, course_id)
        except Course.DoesNotExist:
            return _not_found()
        course.delete()
        return Response({"ok": True, "message": "Course deleted."})


class AdminCoursesView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        qs = annotate_courses(Course.objects.all())
        if role_for(request.user) == "saed_admin":
            qs = qs.exclude(is_restricted=True, restricted_by__profile__role="dunis_admin")
        qs = filter_catalogue(request, qs).order_by("-created_at")
        items, pagination = paginate(request, qs, default_size=50, max_size=200)
        return Response({"courses": [course_payload(c, request) for c in items], "pagination": pagination})


class ReviewCourseView(APIView):
    """SAED admin opens (approves + publishes) or declines a trainer's In-Camp course proposal."""
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, course_id):
        try:
            course = get_course(course_id)
        except Course.DoesNotExist:
            return _not_found()
        if course.course_type != "in_camp":
            return Response({"error": "Only In-Camp course proposals are reviewed."}, status=status.HTTP_400_BAD_REQUEST)
        decision = (request.data.get("decision") or "").strip()
        note = (request.data.get("note") or "").strip()[:500]
        if decision not in ("approve", "decline"):
            return Response({"error": "decision must be 'approve' or 'decline'."}, status=status.HTTP_400_BAD_REQUEST)
        if decision == "decline" and not note:
            return Response({"error": "Tell the trainer why the proposal was declined.", "fields": {"note": "Required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        was_published = course.is_published
        course.approval_status = "approved" if decision == "approve" else "declined"
        course.is_published = decision == "approve"
        course.review_note, course.reviewed_at, course.reviewed_by = note, now(), request.user
        course.save(update_fields=["approval_status", "is_published", "review_note", "reviewed_at", "reviewed_by"])
        if decision == "approve":
            if not was_published:
                announce_course_published(course)
            notify(course.trainer, "In-Camp course opened", f"“{course.title}” was approved and is now open to corps members.",
                   reason="course_review", link=course_link(course))
        else:
            notify(course.trainer, "In-Camp course declined", f"“{course.title}” was declined: {note}",
                   reason="course_review", link=course_link(course))
        return Response({"course": course_payload(course, request)})


class RestrictCourseView(APIView):
    """SAED validates; Dunis has the final say (a Dunis restriction cannot be lifted by SAED)."""
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, course_id):
        try:
            course = get_course(course_id)
        except Course.DoesNotExist:
            return _not_found()
        if course.is_restricted:
            return Response({"error": "Course is already restricted."}, status=status.HTTP_400_BAD_REQUEST)
        course.is_restricted = True
        course.restricted_by = request.user
        course.restricted_at = now()
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            notify(course.trainer, "Course restricted", f"Your course “{course.title}” has been restricted.",
                   reason="course_restricted", link=course_link(course), created_by_role=role_for(request.user))
        return Response({"ok": True, "message": "Course restricted."})


class UnrestrictCourseView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, course_id):
        try:
            course = get_course(course_id)
        except Course.DoesNotExist:
            return _not_found()
        if not course.is_restricted:
            return Response({"error": "Course is not restricted."}, status=status.HTTP_400_BAD_REQUEST)
        if (role_for(request.user) == "saed_admin" and course.restricted_by_id
                and role_for(course.restricted_by) == "dunis_admin"):
            return Response({"error": "Only Dunis Admin can lift this restriction."}, status=status.HTTP_403_FORBIDDEN)
        course.is_restricted = False
        course.restricted_by = None
        course.restricted_at = None
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            notify(course.trainer, "Course unrestricted", f"Your course “{course.title}” is available again.",
                   reason="course_unrestricted", link=course_link(course), created_by_role=role_for(request.user))
        return Response({"ok": True, "message": "Course unrestricted."})


def _progress(user, course):
    lessons = list(course.lessons.filter(is_published=True).values_list("id", flat=True))
    done = set(LessonProgress.objects.filter(student=user, lesson_id__in=lessons).values_list("lesson_id", flat=True))
    total = len(lessons)
    return {"totalLessons": total, "completedLessons": len(done),
            "percentage": round(len(done) / total * 100) if total else 0, "completedLessonIds": sorted(done)}


class CourseDetailView(APIView):
    """One course with its lessons. Lesson content is returned only if the viewer is entitled."""
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            course = get_course(course_id, annotate_courses(Course.objects.filter(is_active=True)))
        except Course.DoesNotExist:
            return _not_found()
        user = request.user
        owner = access.is_course_owner(user, course)
        admin = access.is_admin(user)
        if not (owner or admin) and (course.is_restricted or not course.is_published):
            return _not_found()

        reason = None if (owner or admin) else access.course_block_reason(user, course)
        if reason in ("wrong_track", "other_stream"):
            return Response({"error": access.BLOCK_MESSAGES[reason], "wrongTrack": True}, status=status.HTTP_403_FORBIDDEN)
        enrolled = access.is_enrolled(user, course)
        can_consume = access.can_consume_course(user, course, enrolled=enrolled)
        blocked = access.in_camp_blocked(user, course)
        lessons_qs = course.lessons.all().order_by("order", "id")
        if not (owner or admin):
            lessons_qs = lessons_qs.filter(is_published=True)
        lessons = list(lessons_qs)
        amap = access.access_map(user, lessons)
        out = []
        for les in lessons:
            st = access.lesson_state(user, les, can_consume=can_consume, owner_or_admin=owner or admin,
                                     access_by_lesson=amap)
            out.append(lesson_payload(les, request, user, st, manage=owner))
        trainer = course.trainer
        trainer_data = trainer_public_payload(trainer, request) if trainer else None
        bank = None
        if trainer and not owner and can_consume:
            p = trainer.profile
            if p.account_number and p.bank_name and p.account_name:
                bank = {"bankName": p.bank_name, "accountNumber": p.account_number,
                        "accountName": p.account_name, "verified": p.bank_verified}
        return Response({
            "course": course_payload(course, request),
            "isOwner": owner,
            "isEnrolled": enrolled,
            "canConsume": can_consume,
            "inCampBlocked": blocked,
            "enrolledCount": course.enrollments.filter(status="confirmed").count(),
            "trainer": trainer_data,
            "bankTransfer": bank,
            "lessons": out,
            "progress": _progress(user, course) if role_for(user) == "corps_member" else None,
        })


class CourseProgressView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            course = get_course(course_id)
        except Course.DoesNotExist:
            return _not_found()
        return Response(_progress(request.user, course))


class LessonCompleteView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request, course_id, lesson_id):
        try:
            course = get_course(course_id)
            lesson = Lesson.objects.select_related("course").get(id=lesson_id, course=course, is_published=True)
        except (Course.DoesNotExist, Lesson.DoesNotExist):
            return Response({"error": "Lesson not found."}, status=status.HTTP_404_NOT_FOUND)
        if not access.user_can_open_lesson(request.user, lesson):
            return Response({"error": "You do not have access to this lesson."}, status=status.HTTP_403_FORBIDDEN)
        _, created = LessonProgress.objects.get_or_create(student=request.user, lesson=lesson)
        return Response({"ok": True, "completed": True, "alreadyCompleted": not created,
                         "progress": _progress(request.user, course)})


class MyEnrollmentsView(APIView):
    """Corps member: enrolled courses with progress, newest enrolment first."""
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        qs = CourseEnrollment.objects.filter(student=request.user).exclude(status__in=("rejected",)) \
            .select_related("course", "course__trainer", "course__trainer__profile", "course__orientation_camp")
        qs = qs.filter(course__course_type=stream_svc.track_of(request.user) or "post_camp")
        q = (request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(course__title__icontains=q)
        qs = qs.order_by("-enrolled_at")
        items, pagination = paginate(request, qs, default_size=24, max_size=100)
        courses = []
        attach_course_counts([e.course for e in items])
        prog = progress_for(request.user, [e.course_id for e in items])
        lc = stream_svc.lifecycle(request.user)  # once, not per row
        for e in items:
            payload = course_payload(e.course, request)
            payload["enrollmentStatus"] = e.status
            payload["enrolledAt"] = e.enrolled_at.isoformat() if e.enrolled_at else None
            payload["progress"] = prog[e.course_id]
            payload["inCampBlocked"] = access.in_camp_blocked(request.user, e.course, lc)
            courses.append(payload)
        return Response({"courses": courses, "pagination": pagination})


class CourseEnrollView(APIView):
    """Enrol in a course. Free and immediate; connects the corps member to the trainer in the same step."""
    permission_classes = [HasRole("corps_member")]

    def post(self, request, course_id=None):
        ref = course_id or request.data.get("courseId") or request.data.get("programId")
        if not ref:
            return Response({"error": "courseId is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            course = get_course(ref, Course.objects.select_related("trainer").filter(
                is_active=True, is_published=True, is_restricted=False))
        except Course.DoesNotExist:
            return _not_found()
        reason = access.course_block_reason(request.user, course)
        if reason:
            return Response({"error": access.BLOCK_MESSAGES[reason], "inCampBlocked": reason == "expired",
                             "wrongTrack": reason in ("wrong_track", "other_stream")}, status=status.HTTP_403_FORBIDDEN)

        with transaction.atomic():
            enrollment, created = CourseEnrollment.objects.select_for_update().get_or_create(
                student=request.user, course=course)
            if enrollment.status == "confirmed":
                conn = ensure_trainer_connection(request.user, course.trainer, "active")
                return Response({"ok": True, "alreadyEnrolled": True, "courseId": str(course.public_id),
                                 "connected": bool(conn), "message": "You are already enrolled."})
            if enrollment.status == "rejected":
                return Response({"error": "The trainer has declined your enrolment in this course."},
                                status=status.HTTP_403_FORBIDDEN)
            confirmed = CourseEnrollment.objects.filter(course=course, status="confirmed").count()
            if confirmed >= course.max_students:
                return Response({"error": "This course is full.", "slotsFull": True}, status=status.HTTP_400_BAD_REQUEST)
            enrollment.status = "confirmed"
            enrollment.confirmed_at = now()
            enrollment.refund_requested = False
            enrollment.save(update_fields=["status", "confirmed_at", "refund_requested"])
            conn = ensure_trainer_connection(request.user, course.trainer, "active")

        link = course_link(course)
        notify(request.user, "Enrolment confirmed", f"You are enrolled in “{course.title}”. Start learning now.",
               reason="enrolment", link=link, cta_label="Open course")
        if course.trainer:
            who = request.user.get_full_name() or request.user.email
            notify(course.trainer, "New enrolment", f"{who} enrolled in “{course.title}”.",
                   reason="enrolment", link="/app/my-corpers", email=False)
            if conn is not None and getattr(conn, "_created", False):
                notify(request.user, "Connected to trainer",
                       f"You are now connected with {course.trainer.get_full_name() or course.trainer.email}.",
                       reason="trainer_connected", link=f"/app/trainers/{course.trainer_id}", email=False)
        return Response({"ok": True, "enrolled": True, "courseId": str(course.public_id),
                         "connected": bool(conn), "message": "Enrolled. You can open the course and learn."},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CourseEnrollmentStatusView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            course = get_course(course_id)
        except Course.DoesNotExist:
            return _not_found()
        e = CourseEnrollment.objects.filter(student=request.user, course=course).first()
        return Response({"enrolled": e is not None and e.status == "confirmed",
                         "status": e.status if e else None,
                         "canConsume": access.can_consume_course(request.user, course)})
