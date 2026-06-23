"""
Program and application views.
"""

from django.db import IntegrityError
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from rest_framework.permissions import AllowAny
from ..models import Application, Program
from .base import (
    _log_error, _log_info, _log_warning, _notify_user,
    read_json, user_payload, program_payload, application_payload,
    program_categories_payload, trainers_payload, managed_programs_for,
    managed_applications_for, trainer_program_payload, role_for,
    validation_error, PROGRAM_FIELDS, IsAuthenticatedAPI, HasRole,
)


class ProgramListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            programs = Program.objects.filter(is_active=True, is_restricted=False)
            return Response({
                "programs": [program_payload(p) for p in programs],
                "categories": program_categories_payload(),
            })
        except Exception as exc:
            _log_error("Program list error", exc=exc)
            return Response({"error": "Failed to load programs."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ApplicationListView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            applications = Application.objects.filter(
                applicant=request.user
            ).select_related("program")
            return Response({
                "applications": [application_payload(a) for a in applications]
            })
        except Exception as exc:
            _log_error("Application list error", exc=exc)
            return Response({"error": "Failed to load applications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ApplicationCreateView(APIView):
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        program_id = data.get("programId")
        motivation = data.get("motivation", "")

        if not program_id:
            return Response({"error": "Choose a program before applying.",
                             "fields": {"programId": "Program is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            program = Program.objects.get(id=program_id, is_active=True)
        except Program.DoesNotExist:
            return Response({"error": "Program not found."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            application, created = Application.objects.get_or_create(
                applicant=request.user, program=program,
                defaults={"motivation": motivation},
            )
            if not created:
                return Response({"error": "You already applied for this program."},
                                status=status.HTTP_400_BAD_REQUEST)
            return Response({"application": application_payload(application)},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Application creation error", exc=exc)
            return Response({"error": "Failed to create application."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _apply_program_data(program, data):
    fields = {}
    values = {}
    for frontend_key, model_key in PROGRAM_FIELDS.items():
        if frontend_key in data:
            values[model_key] = data[frontend_key]
    if "trainerId" in data:
        from django.contrib.auth.models import User
        try:
            trainer = User.objects.select_related("profile").get(
                id=int(data.get("trainerId")), is_active=True, profile__role="trainer"
            )
        except (TypeError, ValueError, User.DoesNotExist):
            fields["trainerId"] = "Choose a valid trainer."
        else:
            values["trainer"] = trainer
            values["trainer_name"] = trainer.get_full_name() or trainer.email
    for field in ["title", "description", "trainer_name", "location"]:
        if field in values:
            values[field] = str(values[field]).strip()
            if not values[field]:
                fields[field] = "This field is required."
    if "category" in values and values["category"] not in dict(Program.CATEGORY_CHOICES):
        fields["category"] = "Choose a valid program category."
    for field in ["duration_weeks", "capacity"]:
        if field in values:
            try:
                values[field] = int(values[field])
            except (TypeError, ValueError):
                fields[field] = "Enter a number."
            else:
                if values[field] < 1:
                    fields[field] = "Enter a value greater than zero."
    required = ["title", "category", "description", "duration_weeks", "capacity", "location"]
    if program is None:
        for field in required:
            if field not in values:
                fields[field] = "This field is required."
        if "trainer" not in values:
            fields["trainerId"] = "Choose a trainer."
    if fields:
        return None, fields
    if program is None:
        program = Program()
    for key, value in values.items():
        setattr(program, key, value)
    program.save()
    return program, {}


class ManageProgramsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def get(self, request):
        try:
            programs = managed_programs_for(request.user)
            return Response({
                "programs": [program_payload(p) for p in programs],
                "categories": program_categories_payload(),
                "trainers": trainers_payload(),
            })
        except Exception as exc:
            _log_error("Program list error", exc=exc)
            return Response({"error": "Failed to load programs."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        if role_for(request.user) != "saed_admin":
            return Response({"error": "Only admins can create programs."},
                            status=status.HTTP_403_FORBIDDEN)
        program, fields = _apply_program_data(None, request.data)
        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"program": program_payload(program)}, status=status.HTTP_201_CREATED)


class ManageProgramDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def patch(self, request, program_id):
        try:
            program = managed_programs_for(request.user).get(id=program_id)
        except Program.DoesNotExist:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        program, fields = _apply_program_data(program, request.data)
        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response({"program": program_payload(program)})


class RestrictProgramView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, program_id):
        try:
            program = managed_programs_for(request.user).get(id=program_id)
        except Program.DoesNotExist:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        if program.is_restricted:
            return Response({"error": "Program is already restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        program.is_restricted = True
        program.restricted_by = request.user
        program.restricted_at = now()
        program.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if program.trainer:
            _notify_user(program.trainer, "Program Restricted",
                         f"Your program '{program.title}' has been restricted.",
                         reason="program_restricted", program=program)
        return Response({"ok": True, "message": "Program restricted."})


class UnrestrictProgramView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def post(self, request, program_id):
        try:
            program = managed_programs_for(request.user).get(id=program_id)
        except Program.DoesNotExist:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        if not program.is_restricted:
            return Response({"error": "Program is not restricted."},
                            status=status.HTTP_400_BAD_REQUEST)
        program.is_restricted = False
        program.restricted_by = None
        program.restricted_at = None
        program.save(update_fields=["is_restricted", "restricted_by", "restricted_at"])
        if program.trainer:
            _notify_user(program.trainer, "Program Unrestricted",
                         f"Your program '{program.title}' has been unrestricted.",
                         reason="program_unrestricted", program=program)
        return Response({"ok": True, "message": "Program unrestricted."})


class ManageApplicationsView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def get(self, request):
        try:
            applications = managed_applications_for(request.user)
            return Response({"applications": [application_payload(a) for a in applications]})
        except Exception as exc:
            _log_error("Manage applications error", exc=exc)
            return Response({"error": "Failed to load applications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageApplicationDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin", "trainer")]

    def patch(self, request, application_id):
        try:
            application = managed_applications_for(request.user).get(id=application_id)
        except Application.DoesNotExist:
            return Response({"error": "Application not found."},
                            status=status.HTTP_404_NOT_FOUND)
        data = request.data
        new_status = data.get("status")
        valid = {"approved", "declined", "completed"}
        if new_status and new_status in valid:
            application.status = new_status
            application.save(update_fields=["status"])
        return Response({"application": application_payload(application)})
