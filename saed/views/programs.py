"""
Program views — now proxy to Course model (unified entity).
Programs = Courses. Applications = CourseEnrollments.
"""

from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from ..models import Course, CourseEnrollment
from .base import (
    _log_error, _log_warning, _notify_user,
    user_payload, course_payload,
    program_categories_payload, trainers_payload,
    role_for, PROGRAM_FIELDS, HasRole,
    _parse_date,
)


class ProgramListView(APIView):
    """Public listing — returns courses as programs."""
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            courses = Course.objects.filter(is_active=True, is_restricted=False).select_related(
                "trainer", "trainer__profile"
            )
            return Response({
                "programs": [course_payload(c) for c in courses],
                "categories": program_categories_payload(),
            })
        except Exception as exc:
            _log_error("Program list error", exc=exc)
            return Response({"error": "Failed to load programs."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ApplicationListView(APIView):
    """Returns corps member's enrollments (replaces application list)."""
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            enrollments = CourseEnrollment.objects.filter(
                student=request.user
            ).select_related("course", "course__trainer", "course__trainer__profile")
            result = []
            for e in enrollments:
                result.append({
                    "id": e.id,
                    "status": e.status,
                    "motivation": f"Payment reference: {e.payment_reference}" if e.payment_reference else "",
                    "createdAt": e.enrolled_at.isoformat() if e.enrolled_at else "",
                    "applicant": user_payload(e.student),
                    "program": {
                        "id": e.course.id,
                        "title": e.course.title,
                        "category": e.course.category,
                        "location": e.course.location,
                        "description": e.course.description,
                        "durationWeeks": e.course.duration_weeks,
                        "trainerName": (e.course.trainer.get_full_name() or e.course.trainer.email) if e.course.trainer else None,
                        "availableSlots": e.course.max_students,
                    },
                    "type": "course_enrollment",
                    "amountPaid": str(e.amount_paid),
                    "paymentVerified": e.payment_verified,
                })
            return Response({"applications": result})
        except Exception as exc:
            _log_error("Application list error", exc=exc)
            return Response({"error": "Failed to load applications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ApplicationCreateView(APIView):
    """Enrolls corps member in a course (replaces application creation)."""
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        program_id = data.get("programId")

        if not program_id:
            return Response({"error": "Choose a program before enrolling.",
                             "fields": {"programId": "Program is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            course = Course.objects.get(id=program_id, is_active=True)
        except Course.DoesNotExist:
            return Response({"error": "Program not found."},
                            status=status.HTTP_404_NOT_FOUND)

        existing = CourseEnrollment.objects.filter(
            student=request.user, course=course
        ).first()
        if existing:
            return Response({"error": "You are already enrolled in this program."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            enrollment = CourseEnrollment.objects.create(
                student=request.user,
                course=course,
                status="confirmed",
            )
            return Response({
                "application": {
                    "id": enrollment.id,
                    "status": enrollment.status,
                    "createdAt": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else "",
                    "applicant": user_payload(request.user),
                    "program": {
                        "id": course.id,
                        "title": course.title,
                    },
                    "type": "course_enrollment",
                }
            }, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Enrollment creation error", exc=exc)
            return Response({"error": "Failed to enroll."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageProgramsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def get(self, request):
        try:
            if role_for(request.user) == "trainer":
                courses = Course.objects.filter(trainer=request.user).select_related(
                    "trainer", "trainer__profile"
                )
            else:
                courses = Course.objects.filter(is_active=True).select_related(
                    "trainer", "trainer__profile"
                )
            return Response({
                "programs": [course_payload(c) for c in courses],
                "categories": program_categories_payload(),
                "trainers": trainers_payload(),
            })
        except Exception as exc:
            _log_error("Program list error", exc=exc)
            return Response({"error": "Failed to load programs."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        user_role = role_for(request.user)
        if user_role not in ("saed_admin", "dunis_admin", "trainer"):
            return Response({"error": "Not authorized."},
                            status=status.HTTP_403_FORBIDDEN)

        data = dict(request.data)
        fields = {}
        title = data.get("title", "").strip()
        if not title:
            fields["title"] = "Title is required."
        elif Course.objects.filter(title__iexact=title).exists():
            fields["title"] = "A course with this title already exists."
        category = data.get("category", "").strip()
        price = data.get("price", 0)
        try:
            price = float(price)
        except (TypeError, ValueError):
            fields["price"] = "Enter a valid price."
        max_students = data.get("capacity") or data.get("maxStudents", 40)
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

        trainer = request.user
        if user_role in ("saed_admin", "dunis_admin"):
            trainer_id = data.get("trainerId")
            if trainer_id:
                try:
                    from .auth import User
                    trainer = User.objects.get(id=trainer_id, profile__role="trainer")
                except (User.DoesNotExist, ValueError):
                    return Response({"error": "Invalid trainer selected.",
                                     "fields": {"trainerId": "Trainer not found."}},
                                    status=status.HTTP_400_BAD_REQUEST)

        try:
            from django.db import transaction
            with transaction.atomic():
                course = Course.objects.create(
                    trainer=trainer,
                    title=title,
                    description=data.get("description", "").strip(),
                    category=category,
                    price=price,
                    duration_weeks=int(data.get("durationWeeks", 4)),
                    location=data.get("location", "Lagos").strip(),
                    start_date=start_date,
                    end_date=end_date,
                    max_students=max_students,
                    has_fast_track=bool(data.get("hasFastTrack", False)),
                )
            return Response({"program": course_payload(course)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Program creation error", exc=exc)
            return Response({"error": "Failed to create program."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageProgramDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def patch(self, request, program_id):
        try:
            course = Course.objects.get(id=program_id)
        except Course.DoesNotExist:
            return Response({"error": "Program not found."},
                            status=status.HTTP_404_NOT_FOUND)

        user_role = role_for(request.user)
        if user_role == "trainer" and course.trainer != request.user:
            return Response({"error": "Program not found."},
                            status=status.HTTP_404_NOT_FOUND)

        data = dict(request.data)
        fields = {}

        if "title" in data:
            new_title = data["title"].strip()
            if not new_title:
                fields["title"] = "Title is required."
            elif Course.objects.filter(trainer=course.trainer, title__iexact=new_title).exclude(id=course.id).exists():
                fields["title"] = "You already have a program with this title."

        if "price" in data:
            try:
                data["price"] = float(data["price"])
            except (TypeError, ValueError):
                fields["price"] = "Enter a valid price."

        if "maxStudents" in data:
            try:
                data["maxStudents"] = int(data["maxStudents"])
                if data["maxStudents"] < 1:
                    fields["maxStudents"] = "Capacity must be at least 1."
            except (TypeError, ValueError):
                fields["maxStudents"] = "Enter a valid number."

        if "capacity" in data and "maxStudents" not in data:
            try:
                data["maxStudents"] = int(data["capacity"])
                if data["maxStudents"] < 1:
                    fields["capacity"] = "Capacity must be at least 1."
            except (TypeError, ValueError):
                fields["capacity"] = "Enter a valid number."

        if "durationWeeks" in data:
            try:
                data["durationWeeks"] = int(data["durationWeeks"])
                if data["durationWeeks"] < 1:
                    fields["durationWeeks"] = "Duration must be at least 1 week."
            except (TypeError, ValueError):
                fields["durationWeeks"] = "Enter a valid number."

        if "startDate" in data:
            data["startDate"] = _parse_date(data["startDate"])
            if not data["startDate"]:
                fields["startDate"] = "Start date is required."
        if "endDate" in data:
            data["endDate"] = _parse_date(data["endDate"])
            if not data["endDate"]:
                fields["endDate"] = "End date is required."

        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)

        field_map = {
            "title": "title",
            "description": "description",
            "category": "category",
            "location": "location",
            "isActive": "is_active",
            "hasFastTrack": "has_fast_track",
            "isRestricted": "is_restricted",
        }
        for fe_key, model_key in field_map.items():
            if fe_key in data:
                setattr(course, model_key, data[fe_key])

        if "price" in data:
            course.price = data["price"]
        if "maxStudents" in data and "maxStudents" not in fields:
            course.max_students = data["maxStudents"]
        if "durationWeeks" in data:
            course.duration_weeks = data["durationWeeks"]
        if "startDate" in data:
            course.start_date = data["startDate"]
        if "endDate" in data:
            course.end_date = data["endDate"]
        if "trainerId" in data and user_role in ("saed_admin", "dunis_admin"):
            try:
                from .auth import User
                new_trainer = User.objects.get(id=data["trainerId"], profile__role="trainer")
                course.trainer = new_trainer
            except (User.DoesNotExist, ValueError):
                return Response({"error": "Invalid trainer selected.",
                                 "fields": {"trainerId": "Trainer not found."}},
                                status=status.HTTP_400_BAD_REQUEST)

        course.save()
        return Response({"program": course_payload(course)})


class RestrictProgramView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, program_id):
        try:
            course = Course.objects.get(id=program_id)
        except Course.DoesNotExist:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        if course.is_restricted:
            return Response({"error": "Program is already restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        course.is_restricted = True
        course.restricted_by = request.user
        course.restricted_at = now()
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            _notify_user(course.trainer, "Program Restricted",
                         f"Your program '{course.title}' has been restricted.",
                         reason="program_restricted")
        return Response({"ok": True, "message": "Program restricted."})


class UnrestrictProgramView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, program_id):
        try:
            course = Course.objects.get(id=program_id)
        except Course.DoesNotExist:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        if not course.is_restricted:
            return Response({"error": "Program is not restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        course.is_restricted = False
        course.restricted_by = None
        course.restricted_at = None
        course.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if course.trainer:
            _notify_user(course.trainer, "Program Unrestricted",
                         f"Your program '{course.title}' has been unrestricted.",
                         reason="program_unrestricted")
        return Response({"ok": True, "message": "Program unrestricted."})


class ManageApplicationsView(APIView):
    """Lists enrollments for the trainer's courses."""
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def get(self, request):
        try:
            user_role = role_for(request.user)
            if user_role == "trainer":
                trainer_courses = Course.objects.filter(trainer=request.user)
                enrollments = CourseEnrollment.objects.filter(
                    course__in=trainer_courses
                ).select_related("student", "student__profile", "course", "course__trainer", "course__trainer__profile")
            else:
                enrollments = CourseEnrollment.objects.all().select_related(
                    "student", "student__profile", "course", "course__trainer", "course__trainer__profile"
                )
            result = []
            for e in enrollments:
                result.append({
                    "id": e.id,
                    "status": e.status,
                    "motivation": f"Payment reference: {e.payment_reference}" if e.payment_reference else "",
                    "createdAt": e.enrolled_at.isoformat() if e.enrolled_at else "",
                    "applicant": user_payload(e.student),
                    "program": {
                        "id": e.course.id,
                        "title": e.course.title,
                        "category": e.course.category,
                        "location": e.course.location,
                        "description": e.course.description,
                        "durationWeeks": e.course.duration_weeks,
                        "trainerName": (e.course.trainer.get_full_name() or e.course.trainer.email) if e.course.trainer else None,
                        "availableSlots": e.course.max_students,
                    },
                    "type": "course_enrollment",
                    "amountPaid": str(e.amount_paid),
                    "paymentVerified": e.payment_verified,
                })
            return Response({"applications": result})
        except Exception as exc:
            _log_error("Manage applications error", exc=exc)
            return Response({"error": "Failed to load applications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageApplicationDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def patch(self, request, application_id):
        user_role = role_for(request.user)
        enrollment = None
        try:
            candidate = CourseEnrollment.objects.select_related(
                "student", "student__profile", "course", "course__trainer"
            ).get(id=application_id)
            if user_role in ("saed_admin", "dunis_admin") or candidate.course.trainer == request.user:
                enrollment = candidate
        except CourseEnrollment.DoesNotExist:
            pass
        if enrollment is None:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)

        data = request.data
        new_status = data.get("status")
        STATUS_MAP = {"approved": "confirmed", "declined": "rejected", "completed": "completed"}
        valid = set(STATUS_MAP.keys())
        if new_status and new_status not in valid:
            return Response({"error": "Choose approve, decline, or complete.",
                             "fields": {"status": "Invalid application status."}},
                            status=status.HTTP_400_BAD_REQUEST)

        if enrollment.status == "completed" and user_role not in ("saed_admin", "dunis_admin"):
            return Response({"error": "Only admins can change the status of a completed application.",
                             "fields": {"status": "Completed applications can only be modified by an admin."}},
                            status=status.HTTP_400_BAD_REQUEST)

        if new_status and new_status in valid:
            enrollment.status = STATUS_MAP[new_status]
            enrollment.save(update_fields=["status"])

        return Response({
            "application": {
                "id": enrollment.id,
                "status": enrollment.status,
                "motivation": f"Payment reference: {enrollment.payment_reference}" if enrollment.payment_reference else "",
                "createdAt": enrollment.enrolled_at.isoformat() if enrollment.enrolled_at else "",
                "applicant": user_payload(enrollment.student),
                "program": {
                    "id": enrollment.course.id,
                    "title": enrollment.course.title,
                    "category": enrollment.course.category,
                    "location": enrollment.course.location,
                    "description": enrollment.course.description,
                    "durationWeeks": enrollment.course.duration_weeks,
                    "trainerName": (enrollment.course.trainer.get_full_name() or enrollment.course.trainer.email) if enrollment.course.trainer else None,
                    "availableSlots": enrollment.course.max_students,
                },
                "type": "course_enrollment",
                "amountPaid": str(enrollment.amount_paid),
                "paymentVerified": enrollment.payment_verified,
            }
        })
