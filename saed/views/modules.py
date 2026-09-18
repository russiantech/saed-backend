"""
Module and Lesson CRUD views for trainers.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Course, Module, Lesson
from .base import (
    _log_error, module_payload, lesson_payload,
    HasRole, IsAuthenticatedAPI,
)


class ManageModulesView(APIView):
    """List and create modules for a trainer's courses."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def get(self, request):
        course_id = request.GET.get("courseId")
        modules = Module.objects.filter(course__trainer=request.user)
        if course_id:
            modules = modules.filter(course_id=course_id)
        return Response({"modules": [module_payload(m) for m in modules]})

    def post(self, request):
        data = request.data
        course_id = data.get("courseId")
        title = data.get("title", "").strip()
        if not course_id:
            return Response({"error": "courseId is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "title is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            course = Course.objects.get(id=course_id, trainer=request.user)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."},
                            status=status.HTTP_404_NOT_FOUND)
        order = data.get("order") or (course.modules.count() + 1)
        module = Module.objects.create(
            course=course,
            title=title,
            description=data.get("description", "").strip(),
            order=order,
            is_active=data.get("isActive", True),
        )
        return Response({"module": module_payload(module)}, status=status.HTTP_201_CREATED)


class ManageModuleDetailView(APIView):
    """Update or delete a module."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def patch(self, request, module_id):
        try:
            module = Module.objects.get(id=module_id, course__trainer=request.user)
        except Module.DoesNotExist:
            return Response({"error": "Module not found."},
                            status=status.HTTP_404_NOT_FOUND)
        data = request.data
        for field in ("title", "description", "order"):
            if field in data:
                setattr(module, field, data[field])
        if "isActive" in data:
            module.is_active = data["isActive"]
        module.save()
        return Response({"module": module_payload(module)})

    def delete(self, request, module_id):
        try:
            module = Module.objects.get(id=module_id, course__trainer=request.user)
        except Module.DoesNotExist:
            return Response({"error": "Module not found."},
                            status=status.HTTP_404_NOT_FOUND)
        module.delete()
        return Response({"ok": True})


class ManageLessonsView(APIView):
    """List and create lessons within a module."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def get(self, request):
        module_id = request.GET.get("moduleId")
        course_id = request.GET.get("courseId")
        lessons = Lesson.objects.filter(module__course__trainer=request.user)
        if module_id:
            lessons = lessons.filter(module_id=module_id)
        elif course_id:
            lessons = lessons.filter(module__course_id=course_id)
        return Response({"lessons": [lesson_payload(l) for l in lessons]})

    def post(self, request):
        data = request.data
        module_id = data.get("moduleId")
        title = data.get("title", "").strip()
        if not module_id:
            return Response({"error": "moduleId is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if not title:
            return Response({"error": "title is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            module = Module.objects.get(id=module_id, course__trainer=request.user)
        except Module.DoesNotExist:
            return Response({"error": "Module not found."},
                            status=status.HTTP_404_NOT_FOUND)
        order = data.get("order") or (module.lessons.count() + 1)
        lesson = Lesson.objects.create(
            module=module,
            title=title,
            description=data.get("description", "").strip(),
            content_type=data.get("contentType", "video"),
            video_url=data.get("videoUrl", ""),
            text_content=data.get("textContent", ""),
            document_url=data.get("documentUrl", ""),
            duration_seconds=data.get("durationSeconds", 0),
            order=order,
            is_free_preview=data.get("isFreePreview", False),
        )
        return Response({"lesson": lesson_payload(lesson)}, status=status.HTTP_201_CREATED)


class ManageLessonDetailView(APIView):
    """Update or delete a lesson."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def patch(self, request, lesson_id):
        try:
            lesson = Lesson.objects.get(id=lesson_id, module__course__trainer=request.user)
        except Lesson.DoesNotExist:
            return Response({"error": "Lesson not found."},
                            status=status.HTTP_404_NOT_FOUND)
        data = request.data
        for field in ("title", "description", "video_url", "text_content",
                       "document_url", "duration_seconds", "order"):
            camel = {
                "video_url": "videoUrl", "text_content": "textContent",
                "document_url": "documentUrl", "duration_seconds": "durationSeconds",
            }
            json_key = camel.get(field, field)
            if json_key in data:
                setattr(lesson, field, data[json_key])
        if "contentType" in data:
            lesson.content_type = data["contentType"]
        if "isFreePreview" in data:
            lesson.is_free_preview = data["isFreePreview"]
        lesson.save()
        return Response({"lesson": lesson_payload(lesson)})

    def delete(self, request, lesson_id):
        try:
            lesson = Lesson.objects.get(id=lesson_id, module__course__trainer=request.user)
        except Lesson.DoesNotExist:
            return Response({"error": "Lesson not found."},
                            status=status.HTTP_404_NOT_FOUND)
        lesson.delete()
        return Response({"ok": True})
