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
from ..models import Connection, Course, CourseEnrollment, FastTrackVideo, Profile
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
                    "videoCount": videos.count(),
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


class ManageFastTrackVideosView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        try:
            profile = request.user.profile
            if not profile.can_upload_fast_track:
                return Response({"error": "You are not approved to upload fast track videos."},
                                status=status.HTTP_403_FORBIDDEN)
            course_id = request.GET.get("courseId")
            videos = FastTrackVideo.objects.select_related("course").filter(course__trainer=request.user)
            if course_id:
                videos = videos.filter(course_id=course_id)
            return Response({"videos": [fast_track_video_payload(v) for v in videos]})
        except Exception as exc:
            _log_error("Fast track videos list error", exc=exc)
            return Response({"error": "Failed to load fast track videos."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        profile = request.user.profile
        if not profile.can_upload_fast_track:
            return Response({"error": "You are not approved to upload fast track videos."},
                            status=status.HTTP_403_FORBIDDEN)
        data = request.data
        course_id = data.get("courseId")
        title = data.get("title", "").strip()
        if not course_id:
            return Response({"error": "Course ID is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "Title is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            course = Course.objects.get(id=course_id, trainer=request.user)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            video = FastTrackVideo.objects.create(
                course=course, title=title,
                description=data.get("description", "").strip(),
                video_url=data.get("videoUrl", "").strip(),
                duration_seconds=_safe_int(data.get("durationSeconds", 0), 0),
                order=_safe_int(data.get("order", 0), 0),
                price=float(data.get("price", 0)),
                is_free_preview=bool(data.get("isFreePreview", False)),
            )
            return Response({"video": fast_track_video_payload(video)},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Fast track video creation error", exc=exc)
            return Response({"error": "Failed to create video."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageFastTrackVideoDetailView(APIView):
    permission_classes = [HasRole("trainer")]

    def patch(self, request, video_id):
        profile = request.user.profile
        if not profile.can_upload_fast_track:
            return Response({"error": "You are not approved to upload fast track videos."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            video = FastTrackVideo.objects.select_related("course").get(
                id=video_id, course__trainer=request.user
            )
        except FastTrackVideo.DoesNotExist:
            return Response({"error": "Video not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        for field in ["title", "description", "videoUrl", "durationSeconds", "order", "price", "isFreePreview"]:
            if field in data:
                model_field = {
                    "title": "title", "description": "description", "videoUrl": "video_url",
                    "durationSeconds": "duration_seconds", "order": "order", "price": "price",
                    "isFreePreview": "is_free_preview",
                }[field]
                setattr(video, model_field, data[field])
        video.save()
        return Response({"video": fast_track_video_payload(video)})

    def delete(self, request, video_id):
        profile = request.user.profile
        if not profile.can_upload_fast_track:
            return Response({"error": "You are not approved to upload fast track videos."},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            video = FastTrackVideo.objects.select_related("course").get(
                id=video_id, course__trainer=request.user
            )
        except FastTrackVideo.DoesNotExist:
            return Response({"error": "Video not found."}, status=status.HTTP_404_NOT_FOUND)
        video.delete()
        return Response({"ok": True, "message": "Video deleted."})


class FastTrackVideosForCourseView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request, course_id):
        try:
            user = request.user
            profile = getattr(user, "profile", None)
            is_busy = profile.is_busy_corper if profile else False

            try:
                course = Course.objects.get(id=course_id, is_active=True)
            except Course.DoesNotExist:
                return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

            if not course.has_fast_track:
                return Response({"videos": [], "error": "Fast track is not enabled for this course."})

            is_enrolled = False
            if course.price > 0:
                is_enrolled = CourseEnrollment.objects.filter(
                    student=user, course=course, status="confirmed"
                ).exists()

            videos = FastTrackVideo.objects.select_related("course").filter(course=course)

            if not is_busy and not is_enrolled:
                videos = videos.filter(is_free_preview=True)

            result = []
            for v in videos:
                result.append({
                    "id": v.id,
                    "title": v.title,
                    "description": v.description,
                    "videoUrl": v.video_url,
                    "durationSeconds": v.duration_seconds,
                    "price": str(v.price),
                    "isFreePreview": v.is_free_preview,
                })
            return Response({"videos": result, "isEnrolled": is_enrolled})
        except Exception as exc:
            _log_error("Fast track videos for course error", exc=exc)
            return Response({"error": "Failed to load videos."},
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


def _fetch_vimeo_duration(url):
    try:
        oembed_url = f"https://vimeo.com/api/oembed.json?url={urllib.parse.quote(url)}"
        req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("duration")
    except Exception as exc:
        logger.warning("Vimeo duration fetch for %s failed: %s", url, exc)
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
        if "youtube.com" in url or "youtu.be" in url:
            duration = _fetch_youtube_duration(url)
        elif "vimeo.com" in url:
            duration = _fetch_vimeo_duration(url)

        if duration is None:
            return Response({"error": "Could not fetch duration. Enter it manually."},
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        return Response({"durationSeconds": duration})
