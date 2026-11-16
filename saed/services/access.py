"""Who may open which course / lesson. Single source of truth for entitlements."""
from ..models import CourseEnrollment, Lesson, LessonAccess, Profile

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


def in_camp_open_access(user, course) -> bool:
    """In-Camp courses are open to any corps member whose In-Camp access is active."""
    if course.course_type != "in_camp" or role_of(user) != "corps_member":
        return False
    profile = getattr(user, "profile", None)
    return bool(profile and profile.in_camp_access_active)


def in_camp_blocked(user, course) -> bool:
    if course.course_type != "in_camp" or role_of(user) != "corps_member":
        return False
    profile = getattr(user, "profile", None)
    return bool(profile and not profile.in_camp_access_active)


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
