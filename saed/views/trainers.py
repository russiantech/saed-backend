"""
Trainer and connection views.
"""

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.db import transaction
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Course, CourseEnrollment, Notification, Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async, _notify_user,
    _notify_admins_email,
    read_json, user_payload, trainer_payload, trainers_payload,
    course_payload, connection_payload, role_for,
    validation_error, HasRole, IsAuthenticatedAPI, IsAuthorizedTrainer,
)


class AvailableTrainersView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            lga = request.GET.get("lga", "").strip()
            skill = request.GET.get("skill", "").strip()
            specialization = request.GET.get("specialization", "").strip()
            query = skill or specialization
            trainers = Profile.objects.filter(
                role="trainer", is_authorized=True, user__is_active=True
            ).exclude(is_hidden=True).select_related("user")
            if query:
                trainers = trainers.filter(specialization__icontains=query)
            result = []
            for p in trainers:
                user = p.user
                if lga and lga not in (p.partner_lgas or []):
                    continue
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
            user = User.objects.select_related("profile").get(
                id=trainer_id, profile__role="trainer", is_active=True
            )
            profile = user.profile
            courses = Course.objects.filter(trainer=user, is_active=True)
            existing_connection = Connection.objects.filter(
                corps_member=request.user, trainer=user
            ).first() if request.user.is_authenticated else None

            course_list = []
            for c in courses:
                enrollment = CourseEnrollment.objects.filter(
                    student=request.user, course=c
                ).first() if request.user.is_authenticated else None
                course_list.append({
                    **course_payload(c),
                    "isEnrolled": enrollment is not None,
                    "isPaid": enrollment.status == "confirmed" if enrollment else False,
                    "enrollmentStatus": enrollment.status if enrollment else None,
                })

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
                "connectionStatus": existing_connection.status if existing_connection else "none",
                "connectionId": existing_connection.id if existing_connection else None,
                "courses": course_list,
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
                created_count = 0
                for trainer_id in trainer_ids:
                    try:
                        trainer = User.objects.select_related("profile").get(
                            id=trainer_id, is_active=True, profile__role="trainer", profile__is_authorized=True
                        )
                    except User.DoesNotExist:
                        continue
                    _, created = Connection.objects.get_or_create(
                        corps_member=request.user,
                        trainer=trainer,
                        defaults={"status": "active"},
                    )
                    if created:
                        created_count += 1
                        _notify_user(trainer, "New Connection Request",
                                     f"{request.user.get_full_name()} wants to connect with you.",
                                     reason="connection_request",
                                     created_by_role="corps_member")
                request.user.profile.has_selected_trainers = True
                request.user.profile.save(update_fields=["has_selected_trainers"])
            return Response({"ok": True, "connected": created_count})
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
            ).select_related("trainer", "trainer__profile").exclude(status="cancelled")
            result = []
            for conn in connections:
                trainer = conn.trainer
                profile = trainer.profile
                courses = Course.objects.filter(trainer=trainer, is_active=True)
                result.append({
                    "id": trainer.id,
                    "fullName": trainer.get_full_name() or trainer.email,
                    "email": trainer.email,
                    "specialization": profile.specialization,
                    "bio": profile.bio,
                    "companyName": profile.company_name,
                    "yearsExperience": profile.years_experience,
                    "numberTrained": profile.number_trained,
                    "connectionStatus": conn.status,
                    "connectedAt": conn.connected_at.isoformat(),
                    "courses": [
                        {
                            "id": c.id,
                            "title": c.title,
                            "description": c.description,
                            "category": c.category,
                            "price": str(c.price),
                            "durationWeeks": c.duration_weeks,
                            "startDate": c.start_date.isoformat() if c.start_date else None,
                            "endDate": c.end_date.isoformat() if c.end_date else None,
                            "maxStudents": c.max_students,
                            "hasFastTrack": c.has_fast_track,
                        }
                        for c in courses
                    ],
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
            trainer = User.objects.select_related("profile").get(
                id=trainer_id, is_active=True, profile__role="trainer", profile__is_authorized=True
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

            trainer_courses = Course.objects.filter(trainer=trainer, is_active=True)
            all_full = all(
                Connection.objects.filter(trainer=trainer, status="active").count() >= c.max_students
                for c in trainer_courses
            ) if trainer_courses.exists() else False

            if all_full:
                connection.status = "cancelled"
                connection.save(update_fields=["status"])
                Notification.objects.create(
                    user=request.user,
                    title="Connection Auto-Declined",
                    message=f"Your connection request with {trainer.get_full_name()} was automatically declined because all course slots are full.",
                    reason="connection_request",
                    created_by_role="trainer",
                )
                return Response({"error": "All course slots for this trainer are full."},
                                status=status.HTTP_400_BAD_REQUEST)

            cm_name = request.user.get_full_name() or request.user.email
            _notify_user(trainer, "New Connection Request",
                         f"{cm_name} wants to connect with you. Please review and approve.",
                         reason="connection_request", created_by_role="corps_member")

            _send_email_async(
                subject="SAED IMS - New Connection Request",
                message=f"Hello {trainer.get_full_name()},\n\n{cm_name} ({request.user.email}) wants to connect with you.\nPlease log in to review and approve this request.\n\nBest regards,\nNYSC SAED IMS",
                recipient_list=[trainer.email],
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">New Connection Request</h2>'
                    f'<p><strong>{cm_name}</strong> ({request.user.email}) wants to connect with you.</p>'
                    f'<p>Please log in to review and approve this request.</p></div></div>'
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
            _send_email_async(
                subject="SAED IMS - Connection Approved!",
                message=f"Hello {connection.corps_member.get_full_name()},\n\nYour connection has been approved!",
                recipient_list=[connection.corps_member.email],
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Connection Approved!</h2>'
                    f'<p>Your connection with <strong>{request.user.get_full_name()}</strong> has been approved!</p></div></div>'
                ),
            )
            _notify_admins_email(
                subject=f"Connection Approved - {connection.corps_member.get_full_name()} -> {request.user.get_full_name()}",
                message=(
                    f"A connection has been approved.\n"
                    f"Corps Member: {connection.corps_member.get_full_name()}\n"
                    f"Trainer: {request.user.get_full_name()}"
                ),
                email_type="trainer",
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#1a5f2a;margin-top:0;">Connection Approved</h2>'
                    f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                    f'<tr><td style="padding:8px;font-weight:bold;">Corps Member</td><td style="padding:8px;">{connection.corps_member.get_full_name()}</td></tr>'
                    f'<tr><td style="padding:8px;font-weight:bold;">Trainer</td><td style="padding:8px;">{request.user.get_full_name()}</td></tr>'
                    f'</table></div></div>'
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
            _send_email_async(
                subject="SAED IMS - Connection Declined",
                message=f"Hello {connection.corps_member.get_full_name()},\n\nYour connection request with {request.user.get_full_name()} has been declined.",
                recipient_list=[connection.corps_member.email],
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#e67e22;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#e67e22;margin-top:0;">Connection Declined</h2>'
                    f'<p>Your connection request with <strong>{request.user.get_full_name()}</strong> has been declined.</p>'
                    f'<p style="color:#666;font-size:13px;">You can browse other trainers from your dashboard.</p></div></div>'
                ),
            )
            _notify_admins_email(
                subject=f"Connection Declined - {connection.corps_member.get_full_name()} by {request.user.get_full_name()}",
                message=(
                    f"A connection request has been declined.\n"
                    f"Corps Member: {connection.corps_member.get_full_name()}\n"
                    f"Trainer: {request.user.get_full_name()}"
                ),
                email_type="trainer",
                from_email=request.user.email,
                html_message=(
                    f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                    f'<div style="background:#e67e22;padding:20px;border-radius:8px 8px 0 0;"><h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                    f'<h2 style="color:#e67e22;margin-top:0;">Connection Declined</h2>'
                    f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                    f'<tr><td style="padding:8px;font-weight:bold;">Corps Member</td><td style="padding:8px;">{connection.corps_member.get_full_name()}</td></tr>'
                    f'<tr><td style="padding:8px;font-weight:bold;">Trainer</td><td style="padding:8px;">{request.user.get_full_name()}</td></tr>'
                    f'</table></div></div>'
                ),
            )
            return Response({"connection": connection_payload(connection)})
        except Exception as exc:
            _log_error(f"Connection reject error for {connection_id}", exc=exc)
            return Response({"error": "Failed to reject connection."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CorperProfileForTrainerView(APIView):
    permission_classes = [HasRole("trainer")]

    def get(self, request, corper_id):
        try:
            corper = User.objects.select_related("profile").get(id=corper_id, profile__role="corps_member")
        except User.DoesNotExist:
            return Response({"error": "Corps member not found."},
                            status=status.HTTP_404_NOT_FOUND)

        try:
            connection = Connection.objects.filter(
                trainer=request.user, corps_member=corper
            ).first()

            trainer_courses = Course.objects.filter(trainer=request.user, is_active=True)
            corper_data = user_payload(corper, request)
            corper_data["connectionStatus"] = connection.status if connection else "none"
            corper_data["connectionId"] = connection.id if connection else None

            corper_enrollments = CourseEnrollment.objects.filter(
                student=corper, course__in=trainer_courses
            )
            enrollment_map = {e.course_id: e for e in corper_enrollments}

            courses_with_status = []
            for course in trainer_courses:
                enrolled_count = Connection.objects.filter(
                    trainer=request.user, status="active"
                ).count()
                enrollment = enrollment_map.get(course.id)
                courses_with_status.append({
                    **course_payload(course),
                    "isFull": enrolled_count >= course.max_students,
                    "enrolledCount": enrolled_count,
                    "isEnrolled": enrollment is not None,
                    "isPaid": enrollment.status == "confirmed" if enrollment else False,
                    "enrollmentStatus": enrollment.status if enrollment else None,
                    "enrollmentId": enrollment.id if enrollment else None,
                })

            return Response({
                "corper": corper_data,
                "courses": courses_with_status,
            })
        except Exception as exc:
            _log_error("Corper profile for trainer error", exc=exc)
            return Response({"error": "Failed to load corper profile."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
