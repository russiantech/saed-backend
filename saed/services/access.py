"""Who may open which course / lesson. Single source of truth for entitlements."""
from ..models import CourseEnrollment, Lesson, LessonAccess, Profile
from . import streams

ADMIN_ROLES = ("saed_admin", "dunis_admin")


def role_of(user) -> str:
    profile = getattr(user, "profile", None)
    return profile.role if profile else "corps_member"


def is_admin(user) -> bool:
    return role_of(user) in ADMIN_ROLES


def is_course_owner(user, course) -> bool:
    return bool(course.trainer_id and course.trainer_id == user.id)


def is_enrolled(user, course) -> bool:
    return CourseEnrollment.objects.filter(student=user, course=course, status="confirmed").exists()


def course_block_reason(user, course, lc=None):
    """Why a corps member may not use this course: "wrong_track", "expired", "other_stream" or None (allowed).

    In-Camp and Post-Camp never mix: a corps member only ever sees the programme their account belongs to, and an
    In-Camp corps member only the courses of the stream they joined, while that stream is still running.
    """
    if role_of(user) != "corps_member":
        return None
    track = streams.track_of(user)
    if course.course_type != track:
        return "wrong_track"
    if track != streams.IN_CAMP:
        return None
    lc = lc or streams.lifecycle(user)
    if not lc["isActive"]:
        return "expired"
    if course.stream_id and course.stream_id not in lc["streamIds"]:
        return "other_stream"
    return None


BLOCK_MESSAGES = {
    "wrong_track": "This course belongs to a different programme (In-Camp and Post-Camp are separate).",
    "expired": "Your In-Camp stream has ended, so your In-Camp account is deactivated.",
    "other_stream": "This course belongs to another stream.",
}


def in_camp_open_access(user, course) -> bool:
    """In-Camp courses of the corps member's own (running) stream open without a separate enrolment step."""
    return (course.course_type == "in_camp" and role_of(user) == "corps_member"
            and course_block_reason(user, course) is None)


def in_camp_blocked(user, course, lc=None) -> bool:
    return course_block_reason(user, course, lc) is not None


def can_consume_course(user, course, enrolled=None) -> bool:
    """May this user open the course's learning content (subject to per-lesson locks)?"""
    if is_course_owner(user, course) or is_admin(user):
        return True
    if in_camp_blocked(user, course):
        return False
    if enrolled is None:
        enrolled = is_enrolled(user, course)
    return bool(enrolled or in_camp_open_access(user, course))


def lesson_state(user, lesson: Lesson, *, can_consume: bool, owner_or_admin: bool, access_by_lesson: dict) -> dict:
    """Return {state, hasAccess}.

    state ∈ owner | enrol_required | free | unlocked | requested | locked
    """
    if owner_or_admin:
        return {"state": "owner", "hasAccess": True}
    if not lesson.is_published:
        return {"state": "unpublished", "hasAccess": False}
    if not can_consume:
        return {"state": "enrol_required", "hasAccess": False}
    if not lesson.requires_payment():
        return {"state": "free", "hasAccess": True}
    acc = access_by_lesson.get(lesson.id)
    if acc and acc.status == "active":
        return {"state": "unlocked", "hasAccess": True}
    if acc and acc.status == "requested":
        return {"state": "requested", "hasAccess": False}
    return {"state": "locked", "hasAccess": False}


def access_map(user, lessons) -> dict:
    ids = [l.id for l in lessons]
    return {a.lesson_id: a for a in LessonAccess.objects.filter(student=user, lesson_id__in=ids)}


def user_can_open_lesson(user, lesson: Lesson) -> bool:
    course = lesson.course
    owner_or_admin = is_course_owner(user, course) or is_admin(user)
    can = can_consume_course(user, course)
    st = lesson_state(user, lesson, can_consume=can, owner_or_admin=owner_or_admin,
                      access_by_lesson=access_map(user, [lesson]))
    return st["hasAccess"]


def resolve_course(ref, queryset=None):
    """Accept a public UUID (preferred) or a legacy integer id."""
    from ..models import Course
    qs = queryset if queryset is not None else Course.objects.all()
    ref = str(ref)
    try:
        import uuid
        return qs.get(public_id=uuid.UUID(ref))
    except (ValueError, Course.DoesNotExist):
        pass
    if ref.isdigit():
        return qs.get(pk=int(ref))
    raise Course.DoesNotExist
