"""
Fast track video views.
"""
import json
import logging
import re
import urllib.request
import urllib.parse
from django.conf import settings as django_settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Connection, Course, CourseEnrollment, FastTrackVideo, Profile, Module, Lesson, LessonProgress
from .base import (
    _log_error, _log_info, _log_warning,
    read_json, _safe_int, course_payload, fast_track_video_payload,
    validation_error, HasRole, IsAuthenticatedAPI,
)

logger = logging.getLogger(__name__)


class TraineeFastTrackCoursesView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            connections = Connection.objects.filter(
                corps_member=request.user, status="active"
            ).select_related("trainer")
            trainer_ids = connections.values_list("trainer_id", flat=True)
            courses = Course.objects.filter(
                trainer_id__in=trainer_ids, is_active=True, has_fast_track=True
            )
            enrolled_ids = set(
                CourseEnrollment.objects.filter(
                    student=request.user, course__in=courses, status="confirmed"
                ).values_list("course_id", flat=True)
            )
            pending_ids = set(
                CourseEnrollment.objects.filter(
                    student=request.user, course__in=courses, status="pending"
                ).values_list("course_id", flat=True)
            )
            rejected_ids = set(
                CourseEnrollment.objects.filter(
                    student=request.user, course__in=courses, status="rejected"
                ).values_list("course_id", flat=True)
            )
            refunded_ids = set(
                CourseEnrollment.objects.filter(
                    student=request.user, course__in=courses, status="refunded"
                ).values_list("course_id", flat=True)
            )
            result = []
            for c in courses:
                videos = FastTrackVideo.objects.filter(course=c)
                profile = getattr(request.user, "profile", None)
                is_busy = profile.is_busy_corper if profile else False
                if not is_busy:
                    videos = videos.filter(is_free_preview=True)
                lesson_count = Lesson.objects.filter(module__course=c).count()
                module_count = Module.objects.filter(course=c).count()
                content_count = videos.count() + lesson_count
                enrollment_status = None
                if c.id in enrolled_ids:
                    enrollment_status = "confirmed"
                elif c.id in pending_ids:
                    enrollment_status = "pending"
                elif c.id in rejected_ids:
                    enrollment_status = "rejected"
                elif c.id in refunded_ids:
                    enrollment_status = "refunded"
                result.append({
                    **course_payload(c),
                    "videoCount": content_count,
                    "moduleCount": module_count,
                    "isEnrolled": c.id in enrolled_ids,
                    "isPending": c.id in pending_ids,
                    "isRejected": c.id in rejected_ids,
                    "isRefunded": c.id in refunded_ids,
                    "enrollmentStatus": enrollment_status,
                })
            return Response({"courses": result})
        except Exception as exc:
            _log_error("Trainee fast track error", exc=exc)
            return Response({"error": "Failed to load fast track courses."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class FastTrackVideosForCourseView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request, course_id):
        try:
            user = request.user
            try:
                course = Course.objects.get(id=course_id, is_active=True)
            except Course.DoesNotExist:
                return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

            if not course.has_fast_track:
                return Response({"videos": [], "modules": [], "error": "Fast track is not enabled for this course."})

            if not Connection.objects.filter(
                corps_member=user, trainer=course.trainer, status="active"
            ).exists():
                return Response({"error": "Connect with this course's trainer to access its content."},
                                status=status.HTTP_403_FORBIDDEN)

            is_enrolled = False
            if course.price > 0:
                is_enrolled = CourseEnrollment.objects.filter(
                    student=user, course=course, status="confirmed"
                ).exists()

            from ..models import Module, Lesson

            modules = Module.objects.filter(course=course, is_active=True).prefetch_related("lessons")
            module_list = []
            for m in modules:
                lessons_qs = m.lessons.all()
                if course.price > 0 and not is_enrolled:
                    lessons_qs = lessons_qs.filter(is_free_preview=True)
                module_list.append({
                    "id": m.id,
                    "title": m.title,
                    "description": m.description,
                    "order": m.order,
                    "lessons": [{
                        "id": l.id,
                        "title": l.title,
                        "description": l.description,
                        "contentType": l.content_type,
                        "videoUrl": l.video_url,
                        "textContent": l.text_content,
                        "documentUrl": l.document_url,
                        "durationSeconds": l.duration_seconds,
                        "order": l.order,
                        "isFreePreview": l.is_free_preview,
                    } for l in lessons_qs],
                })

            videos = FastTrackVideo.objects.select_related("course").filter(course=course)
            if course.price > 0 and not is_enrolled:
                videos = videos.filter(is_free_preview=True)
            video_list = [{
                "id": v.id,
                "title": v.title,
                "description": v.description,
                "videoUrl": v.video_url,
                "durationSeconds": v.duration_seconds,
                "price": str(v.price),
                "isFreePreview": v.is_free_preview,
            } for v in videos]

            completed_lesson_ids = []
            if user.is_authenticated:
                lesson_ids = [l["id"] for m in module_list for l in m.get("lessons", [])]
                completed_lesson_ids = list(
                    LessonProgress.objects.filter(
                        student=user, lesson_id__in=lesson_ids
                    ).values_list("lesson_id", flat=True)
                )

            return Response({
                "videos": video_list,
                "modules": module_list,
                "isEnrolled": is_enrolled,
                "completedLessonIds": completed_lesson_ids,
            })
        except Exception as exc:
            _log_error("Fast track videos for course error", exc=exc)
            return Response({"error": "Failed to load content."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _parse_iso8601_duration(text):
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
    return None


def _fetch_youtube_duration(url):
    video_id = None
    m = re.search(r"(?:v=|youtu\.be/|embed/)([\w-]{11})", url)
    if m:
        video_id = m.group(1)
    if not video_id:
        return None

    page_url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        req = urllib.request.Request(page_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        m = re.search(r'"lengthSeconds"\s*:\s*"(\d+)"', html)
        if m:
            return int(m.group(1))

        m = re.search(r'"approxDurationMs"\s*:\s*"(\d+)"', html)
        if m:
            return int(m.group(1)) // 1000

        m = re.search(r'"duration"\s*:\s*"(PT[\dHMS]+)"', html)
        if m:
            return _parse_iso8601_duration(m.group(1))
    except Exception as exc:
        logger.warning("YouTube duration fetch for %s failed: %s", url, exc)
    return None


class FetchVideoDurationView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request):
        data = request.data
        url = data.get("url", "").strip()
        if not url:
            return Response({"error": "URL is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        duration = None
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            return Response({"error": "Use a HTTPS YouTube URL."},
                            status=status.HTTP_400_BAD_REQUEST)
        if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            duration = _fetch_youtube_duration(url)
        else:
            return Response({"error": "Only YouTube URLs are supported."},
                            status=status.HTTP_400_BAD_REQUEST)

        if duration is None:
            return Response({"error": "Could not fetch duration."},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response({"durationSeconds": duration})
