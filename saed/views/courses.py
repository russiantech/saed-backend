"""
Course views (trainer CRUD, admin).
"""

from django.db import transaction
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Course, CourseEnrollment, FastTrackVideo, Lesson, LessonProgress, Module
from .base import (
    _log_error, _notify_user,
    _safe_float, _resolve_course_dates, _parse_date,
    course_payload, role_for,
    HasRole, IsAuthenticatedAPI,
)

class CourseListView(APIView):
    """Public course catalog — lists active, non-restricted courses."""
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            courses = Course.objects.select_related("trainer", "trainer__profile").filter(
                is_active=True, is_restricted=False
            ).order_by("-created_at")
            return Response({"courses": [course_payload(c) for c in courses]})
        except Exception as exc:
            _log_error("Course list error", exc=exc)
            return Response({"error": "Failed to load courses."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageCoursesView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        try:
            courses = Course.objects.filter(trainer=request.user).order_by("-created_at")
            return Response({"courses": [course_payload(c) for c in courses]})
        except Exception as exc:
            _log_error("Course list error", exc=exc)
            return Response({"error": "Failed to load courses."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        data = _resolve_course_dates(dict(request.data))
        fields = {}
        title = data.get("title", "").strip()
        if not title:
            fields["title"] = "Title is required."
        category = data.get("category", "").strip()
        price = data.get("price", 0)
        try:
            price = float(price)
        except (TypeError, ValueError):
            fields["price"] = "Enter a valid price."
        max_students = data.get("maxStudents", 40)
        try:
            max_students = int(max_students)
        except (TypeError, ValueError):
            fields["maxStudents"] = "Enter a valid number."

        start_date = _parse_date(data.get("startDate"))
        end_date = _parse_date(data.get("endDate"))
        if not start_date:
            fields["startDate"] = "Start date is required."
        if not end_date:
            fields["endDate"] = "End date is required."
        if start_date and end_date and end_date < start_date:
            fields["endDate"] = "End date must be after start date."

        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                course = Course.objects.create(
                    trainer=request.user,
                    title=title,
                    description=data.get("description", "").strip(),
                    category=category,
                    price=price,
                    duration_weeks=_safe_float(data.get("durationWeeks", 4), 4),
                    start_date=start_date,
                    end_date=end_date,
                    max_students=max_students,
                    has_fast_track=bool(data.get("hasFastTrack", False)),
                )
            return Response({"course": course_payload(course)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Course creation error", exc=exc)
            return Response({"error": "Failed to create course."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageCourseDetailView(APIView):
    permission_classes = [HasRole("trainer")]

    def patch(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id, trainer=request.user)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        data = _resolve_course_dates(dict(request.data))
        for field in ["title", "description", "category", "price", "durationWeeks", "startDate", "endDate", "maxStudents", "hasFastTrack", "isActive"]:
            if field in data:
                model_field = {
                    "title": "title", "description": "description", "category": "category",
                    "price": "price", "durationWeeks": "duration_weeks", "startDate": "start_date",
                    "endDate": "end_date", "maxStudents": "max_students", "hasFastTrack": "has_fast_track",
                    "isActive": "is_active",
                }[field]
                value = data[field]
                if model_field in ("price",):
                    value = _safe_float(value, 0)
                elif model_field in ("duration_weeks",):
                    value = _safe_float(value, 4)
                elif model_field in ("max_students",):
                    value = int(value) if value else 40
                elif model_field in ("has_fast_track", "is_active"):
                    value = bool(value)
                elif model_field in ("start_date", "end_date"):
                    value = _parse_date(value) or value or None
                setattr(course, model_field, value)
        course.save()
        return Response({"course": course_payload(course)})

    def delete(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id, trainer=request.user)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        course.delete()
        return Response({"ok": True, "message": "Course deleted."})


class AdminCoursesView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        try:
            courses = Course.objects.select_related("trainer", "trainer__profile").all()
            user_role = role_for(request.user)
            if user_role == "saed_admin":
                courses = courses.exclude(is_restricted=True, restricted_by__profile__role="dunis_admin")
            return Response({"courses": [course_payload(c) for c in courses]})
        except Exception as exc:
            _log_error("Admin courses error", exc=exc)
            return Response({"error": "Failed to load courses."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class RestrictCourseView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        if course.is_restricted:
            return Response({"error": "Course is already restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        course.is_restricted = True
        course.restricted_by = request.user
        course.restricted_at = now()
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            _notify_user(course.trainer, "Course Restricted",
                         f"Your course '{course.title}' has been restricted.",
                         reason="course_restricted")
        return Response({"ok": True, "message": "Course restricted."})


class UnrestrictCourseView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        if not course.is_restricted:
            return Response({"error": "Course is not restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        course.is_restricted = False
        course.restricted_by = None
        course.restricted_at = None
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            _notify_user(course.trainer, "Course Unrestricted",
                         f"Your course '{course.title}' has been unrestricted.",
                         reason="course_unrestricted")
        return Response({"ok": True, "message": "Course unrestricted."})


class CourseDetailView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            course = Course.objects.select_related("trainer", "trainer__profile").get(id=course_id, is_active=True)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        videos = FastTrackVideo.objects.filter(course=course).order_by("order")
        is_owner = course.trainer_id == request.user.id
        is_connected = Connection.objects.filter(
            corps_member=request.user, trainer=course.trainer, status="active"
        ).exists()
        is_enrolled = CourseEnrollment.objects.filter(
            student=request.user, course=course, status="confirmed"
        ).exists()
        if not is_owner:
            if not is_connected:
                videos = videos.none()
            elif course.price > 0 and not is_enrolled:
                videos = videos.filter(is_free_preview=True)
        trainer_data = None
        if course.trainer:
            trainer_data = {
                "id": course.trainer.id,
                "fullName": course.trainer.get_full_name() or course.trainer.email,
                "specialization": course.trainer.profile.specialization if hasattr(course.trainer, "profile") else "",
                "companyName": course.trainer.profile.company_name if hasattr(course.trainer, "profile") else "",
            }
        return Response({
            "course": course_payload(course),
            "enrolledCount": CourseEnrollment.objects.filter(course=course, status="confirmed").count(),
            "trainer": trainer_data,
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "description": v.description,
                    "videoUrl": v.video_url,
                    "durationSeconds": v.duration_seconds,
                    "order": v.order,
                    "price": str(v.price),
                    "isFreePreview": v.is_free_preview,
                }
                for v in videos
            ],
        })


class CourseProgressView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        total = Lesson.objects.filter(module__course=course, module__is_active=True).count()
        completed = LessonProgress.objects.filter(
            student=request.user, lesson__module__course=course
        ).count()
        percentage = round(completed / total * 100) if total else 0
        return Response({
            "totalLessons": total,
            "completedLessons": completed,
            "percentage": percentage,
        })


class LessonCompleteView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request, course_id, lesson_id):
        try:
            lesson = Lesson.objects.get(id=lesson_id, module__course_id=course_id)
        except Lesson.DoesNotExist:
            return Response({"error": "Lesson not found."}, status=status.HTTP_404_NOT_FOUND)

        if not CourseEnrollment.objects.filter(
            student=request.user, course_id=course_id, status="confirmed"
        ).exists():
            return Response({"error": "You are not enrolled in this course."},
                            status=status.HTTP_403_FORBIDDEN)

        progress, created = LessonProgress.objects.get_or_create(
            student=request.user, lesson=lesson
        )
        return Response({
            "ok": True,
            "completed": True,
            "alreadyCompleted": not created,
        })
