"""
Fast track video views.
"""
import json
import re
import urllib.request
from django.conf import settings as django_settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Course, CourseEnrollment, FastTrackVideo
from .base import (
    _log_error, _log_info, _log_warning,
    read_json, _safe_int, course_payload, fast_track_video_payload,
    validation_error, HasRole, IsAuthenticatedAPI,
)


class TraineeFastTrackCoursesView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            enrollments = CourseEnrollment.objects.filter(
                student=request.user, status="confirmed"
            ).select_related("course")
            courses = []
            for e in enrollments:
                course = e.course
                if course.has_fast_track:
                    videos = FastTrackVideo.objects.filter(course=course).order_by("order")
                    course_data = course_payload(course)
                    course_data["videos"] = [fast_track_video_payload(v) for v in videos]
                    courses.append(course_data)
            return Response({"courses": courses})
        except Exception as exc:
            _log_error("Trainee fast track error", exc=exc)
            return Response({"error": "Failed to load fast track courses."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageFastTrackVideosView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        try:
            courses = Course.objects.filter(
                trainer=request.user, has_fast_track=True
            )
            result = []
            for course in courses:
                videos = FastTrackVideo.objects.filter(course=course).order_by("order")
                course_data = course_payload(course)
                course_data["videos"] = [fast_track_video_payload(v) for v in videos]
                result.append(course_data)
            return Response({"courses": result})
        except Exception as exc:
            _log_error("Fast track videos list error", exc=exc)
            return Response({"error": "Failed to load fast track videos."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        data = request.data
        course_id = data.get("courseId")
        title = data.get("title", "").strip()
        video_url = data.get("videoUrl", "").strip()

        if not course_id:
            return Response({"error": "Course ID is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "Title is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not video_url:
            return Response({"error": "Video URL is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            course = Course.objects.get(id=course_id, trainer=request.user)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            order = FastTrackVideo.objects.filter(course=course).count() + 1
            video = FastTrackVideo.objects.create(
                course=course, title=title,
                description=data.get("description", "").strip(),
                video_url=video_url,
                duration_seconds=_safe_int(data.get("durationSeconds", 0), 0),
                order=order,
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
        try:
            video = FastTrackVideo.objects.select_related("course").get(
                id=video_id, course__trainer=request.user
            )
        except FastTrackVideo.DoesNotExist:
            return Response({"error": "Video not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if "title" in data:
            video.title = str(data["title"]).strip() or video.title
        if "description" in data:
            video.description = str(data["description"]).strip()
        if "videoUrl" in data:
            video.video_url = str(data["videoUrl"]).strip()
        if "durationSeconds" in data:
            video.duration_seconds = _safe_int(data["durationSeconds"], 0)
        if "order" in data:
            video.order = _safe_int(data["order"], 0)
        if "price" in data:
            video.price = float(data["price"])
        if "isFreePreview" in data:
            video.is_free_preview = bool(data["isFreePreview"])
        video.save()
        return Response({"video": fast_track_video_payload(video)})

    def delete(self, request, video_id):
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
            videos = FastTrackVideo.objects.filter(course_id=course_id).order_by("order")
            return Response({"videos": [fast_track_video_payload(v) for v in videos]})
        except Exception as exc:
            _log_error("Fast track videos for course error", exc=exc)
            return Response({"error": "Failed to load videos."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _parse_iso8601_duration(text):
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", text)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _fetch_youtube_duration(url):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    if not match:
        return 0
    video_id = match.group(1)
    api_key = getattr(django_settings, "YOUTUBE_API_KEY", "")
    if not api_key:
        return 0
    api_url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&part=contentDetails&key={api_key}"
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    items = data.get("items", [])
    if items:
        duration = items[0].get("contentDetails", {}).get("duration", "PT0S")
        return _parse_iso8601_duration(duration)
    return 0


def _fetch_vimeo_duration(url):
    match = re.search(r"vimeo\.com/(\d+)", url)
    if not match:
        return 0
    video_id = match.group(1)
    api_url = f"https://vimeo.com/api/v2/video/{video_id}.json"
    req = urllib.request.Request(api_url)
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    if data:
        return int(data[0].get("duration", 0))
    return 0


class FetchVideoDurationView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request):
        data = request.data
        url = data.get("url", "").strip()
        if not url:
            return Response({"error": "URL is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            duration = 0
            if "youtube.com" in url or "youtu.be" in url:
                duration = _fetch_youtube_duration(url)
            elif "vimeo.com" in url:
                duration = _fetch_vimeo_duration(url)
            return Response({"durationSeconds": duration})
        except Exception as exc:
            _log_error("Fetch video duration error", exc=exc)
            return Response({"error": "Failed to fetch video duration."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
