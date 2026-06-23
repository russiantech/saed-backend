"""
Trainer and connection views.
"""

from django.conf import settings as django_settings
from django.db import transaction
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Course, Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async, _notify_user,
    read_json, user_payload, trainer_payload, trainers_payload,
    course_payload, connection_payload, role_for,
    validation_error, HasRole, IsAuthenticatedAPI, IsAuthorizedTrainer,
)


class AvailableTrainersView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            specialization = request.GET.get("specialization", "").strip()
            lga = request.GET.get("lga", "").strip()
            trainers = Profile.objects.filter(
                role="trainer", is_authorized=True, user__is_active=True
            ).select_related("user")
            if specialization:
                trainers = trainers.filter(specialization__icontains=specialization)
            if lga:
                trainers = trainers.filter(partner_lgas__contains=[lga])
            result = []
            for p in trainers:
                user = p.user
                result.append({
                    "id": user.id,
                    "fullName": user.get_full_name() or user.email,
                    "email": user.email,
                    "specialization": p.specialization,
                    "partnerLgas": p.partner_lgas,
                    "yearsExperience": p.years_experience,
                    "bio": p.bio,
                    "companyName": p.company_name,
                    "numberTrained": p.number_trained,
                    "profilePicture": f"{django_settings.MEDIA_URL}{p.profile_picture.name}" if p.profile_picture else None,
                })
            return Response({"trainers": result})
        except Exception as exc:
            _log_error("Available trainers error", exc=exc)
            return Response({"error": "Failed to load trainers."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrainerDetailView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, trainer_id):
        try:
            from django.contrib.auth.models import User
            user = User.objects.select_related("profile").get(
                id=trainer_id, profile__role="trainer", is_active=True
            )
            profile = user.profile
            courses = Course.objects.filter(trainer=user, is_active=True)
            data = {
                "id": user.id,
                "fullName": user.get_full_name() or user.email,
                "email": user.email,
                "specialization": profile.specialization,
                "partnerLgas": profile.partner_lgas,
                "yearsExperience": profile.years_experience,
                "bio": profile.bio,
                "companyName": profile.company_name,
                "numberTrained": profile.number_trained,
                "profilePicture": f"{django_settings.MEDIA_URL}{profile.profile_picture.name}" if profile.profile_picture else None,
                "courses": [course_payload(c) for c in courses],
            }
            return Response(data)
        except Exception as exc:
            _log_error("Trainer detail error", exc=exc)
            return Response({"error": "Trainer not found."},
                            status=status.HTTP_404_NOT_FOUND)


class SelectTrainersView(APIView):
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        trainer_ids = data.get("trainerIds", [])
        if not trainer_ids:
            return Response({"error": "Select at least one trainer."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                for trainer_id in trainer_ids:
                    from django.contrib.auth.models import User
                    try:
                        trainer = User.objects.get(id=trainer_id, profile__role="trainer")
                    except User.DoesNotExist:
                        continue
                    connection, created = Connection.objects.get_or_create(
                        corps_member=request.user, trainer=trainer,
                    )
                    if created:
                        _notify_user(trainer, "New Connection Request",
                                     f"{request.user.get_full_name()} wants to connect with you.",
                                     reason="connection_request",
                                     created_by_role="corps_member")
                request.user.profile.has_selected_trainers = True
                request.user.profile.save(update_fields=["has_selected_trainers"])
            return Response({"ok": True, "message": "Trainer selections submitted."})
        except Exception as exc:
            _log_error("Select trainers error", exc=exc)
            return Response({"error": "Failed to select trainers."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MyTrainersView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            connections = Connection.objects.filter(
                corps_member=request.user
            ).select_related("trainer", "trainer__profile")
            result = []
            for c in connections:
                t = c.trainer
                p = getattr(t, "profile", None)
                result.append({
                    "id": t.id,
                    "fullName": t.get_full_name() or t.email,
                    "email": t.email,
                    "specialization": p.specialization if p else "",
                    "connectionStatus": c.status,
                    "connectionId": c.id,
                })
            return Response({"trainers": result})
        except Exception as exc:
            _log_error("My trainers error", exc=exc)
            return Response({"error": "Failed to load trainers."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConnectTrainerView(APIView):
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        data = request.data
        trainer_id = data.get("trainerId")
        if not trainer_id:
            return Response({"error": "Trainer ID is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            from django.contrib.auth.models import User
            trainer = User.objects.select_related("profile").get(
                id=trainer_id, profile__role="trainer", is_active=True
            )
        except User.DoesNotExist:
            return Response({"error": "Trainer not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            connection, created = Connection.objects.get_or_create(
                corps_member=request.user, trainer=trainer,
            )
            if not created:
                return Response({"error": "Connection already exists."},
                                status=status.HTTP_400_BAD_REQUEST)

            cm_name = request.user.get_full_name() or request.user.email
            _notify_user(trainer, "New Connection Request",
                         f"{cm_name} wants to connect with you.",
                         reason="connection_request", created_by_role="corps_member")

            _send_email_async(
                subject="SAED IMS - New Connection Request",
                message=f"Hello {trainer.get_full_name()},\n\n{cm_name} wants to connect with you.\n\nBest regards,\nNYSC SAED IMS",
                recipient_list=[trainer.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">New Connection Request</h2>'
                    f'<p><strong>{cm_name}</strong> wants to connect with you.</p></div></div>'
                ),
            )
            return Response({"connection": connection_payload(connection)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Connection creation error", exc=exc)
            return Response({"error": "Failed to create connection."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MyConnectionsView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            connections = Connection.objects.filter(
                corps_member=request.user
            ).select_related("trainer", "trainer__profile")
            return Response({"connections": [connection_payload(c) for c in connections]})
        except Exception as exc:
            _log_error("My connections error", exc=exc)
            return Response({"error": "Failed to load connections."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MyCorpersView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        try:
            connections = Connection.objects.filter(
                trainer=request.user
            ).select_related("corps_member", "corps_member__profile")
            return Response({"corpers": [connection_payload(c) for c in connections]})
        except Exception as exc:
            _log_error("My corpers error", exc=exc)
            return Response({"error": "Failed to load corps members."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConnectionApproveView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, connection_id):
        try:
            connection = Connection.objects.select_related(
                "corps_member", "trainer"
            ).get(id=connection_id, trainer=request.user, status="pending")
        except Connection.DoesNotExist:
            return Response({"error": "Connection request not found."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            connection.status = "active"
            connection.save(update_fields=["status"])
            _notify_user(connection.corps_member, "Connection Approved",
                         f"Your connection with {request.user.get_full_name()} has been approved!",
                         reason="connection_approved", created_by_role="trainer")
            frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3002")
            _send_email_async(
                subject="SAED IMS - Connection Approved!",
                message=f"Hello {connection.corps_member.get_full_name()},\n\nYour connection has been approved!",
                recipient_list=[connection.corps_member.email],
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Connection Approved!</h2>'
                    f'<p>Your connection with <strong>{request.user.get_full_name()}</strong> has been approved!</p></div></div>'
                ),
            )
            return Response({"connection": connection_payload(connection)})
        except Exception as exc:
            _log_error(f"Connection approval error for {connection_id}", exc=exc)
            return Response({"error": "Failed to approve connection."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConnectionRejectView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, connection_id):
        try:
            connection = Connection.objects.get(
                id=connection_id, trainer=request.user, status="pending"
            )
        except Connection.DoesNotExist:
            return Response({"error": "Connection request not found."},
                            status=status.HTTP_404_NOT_FOUND)
        try:
            connection.status = "cancelled"
            connection.save(update_fields=["status"])
            _notify_user(connection.corps_member, "Connection Declined",
                         f"Your connection request with {request.user.get_full_name()} was declined.",
                         reason="connection_declined", created_by_role="trainer")
            return Response({"connection": connection_payload(connection)})
        except Exception as exc:
            _log_error(f"Connection reject error for {connection_id}", exc=exc)
            return Response({"error": "Failed to reject connection."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CorperProfileForTrainerView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request, corper_id):
        try:
            from django.contrib.auth.models import User
            corper = User.objects.select_related("profile").get(id=corper_id)
            return Response({"corper": user_payload(corper, request)})
        except Exception as exc:
            _log_error("Corper profile error", exc=exc)
            return Response({"error": "Corps member not found."},
                            status=status.HTTP_404_NOT_FOUND)
