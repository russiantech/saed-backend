"""
Trainer and connection views.
"""

from django.conf import settings as django_settings
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Course, CourseEnrollment, Notification, Profile
from ..services.notify import notify
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async, _notify_user,
    _notify_admins_email,
    read_json, user_payload, trainer_payload, trainers_payload,
    course_payload, connection_payload, role_for, trainer_public_payload, annotate_courses,
    ensure_trainer_connection, paginate,
    validation_error, HasRole, IsAuthenticatedAPI, IsAuthorizedTrainer,
)


def _trainer_card(p, request, courses=None):
    user = p.user
    data = trainer_public_payload(user, request, p)
    data["partnerLgas"] = p.partner_lgas or []
    if courses is not None:
        data["courses"] = courses
        data["courseCount"] = len(courses)
        data["trainingLocations"] = sorted({c["trainingLocation"] for c in courses if c.get("trainingLocation")})
    return data


class AvailableTrainersView(APIView):
    """Approved trainers. NO restrictive default filters: everything is optional."""
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            g = request.GET
            q = (g.get("q") or g.get("name") or "").strip()
            skill = (g.get("skill") or g.get("specialization") or g.get("category") or "").strip()
            state = (g.get("state") or "").strip()
            lga = (g.get("lga") or "").strip()
            ppa = (g.get("ppa") or "").strip()
            location = (g.get("location") or "").strip()

            qs = Profile.objects.filter(role="trainer", is_authorized=True, user__is_active=True) \
                .exclude(is_hidden=True).exclude(authorization_status__in=("restricted", "removed", "declined")) \
                .select_related("user")
            if q:
                qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
                               | Q(company_name__icontains=q) | Q(user__email__icontains=q))
            if skill:
                from ..models import SKILL_AREAS
                labels = [k for k, lbl in SKILL_AREAS if skill.lower() in (k.lower(), lbl.lower())]
                by_course = Course.objects.filter(category__in=labels or [skill]).values("trainer_id")
                qs = qs.filter(Q(specialization__icontains=skill) | Q(user_id__in=by_course))
            if state:
                by_course = Course.objects.filter(training_state__icontains=state).values("trainer_id")
                qs = qs.filter(Q(state_of_deployment__icontains=state) | Q(user_id__in=by_course))
            if lga:
                by_course = Course.objects.filter(training_lga__icontains=lga).values("trainer_id")
                qs = qs.filter(Q(lga_of_deployment__icontains=lga) | Q(user_id__in=by_course)
                               | Q(partner_lgas__icontains=lga))
            if ppa:
                qs = qs.filter(ppa__icontains=ppa)
            if location:
                by_course = Course.objects.filter(Q(training_location__icontains=location)
                                                  | Q(location__icontains=location)).values("trainer_id")
                qs = qs.filter(user_id__in=by_course)
            qs = qs.distinct().order_by("-is_verified", "user__first_name", "user__last_name", "id")
            items, pagination = paginate(request, qs, default_size=12, max_size=60)

            live = {c.trainer_id: [] for c in []}
            ids = [p.user_id for p in items]
            for c in annotate_courses(Course.objects.filter(trainer_id__in=ids, is_active=True, is_published=True, is_restricted=False)):
                live.setdefault(c.trainer_id, []).append(course_payload(c, request))
            return Response({"trainers": [_trainer_card(p, request, live.get(p.user_id, [])) for p in items],
                             "pagination": pagination})
        except Exception as exc:
            _log_error("Available trainers error", exc=exc)
            return Response({"error": "Failed to load trainers."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TrainerDetailView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, trainer_id):
        try:
            user = User.objects.select_related("profile").get(id=trainer_id, profile__role="trainer", is_active=True)
        except (User.DoesNotExist, ValueError):
            return Response({"error": "Trainer not found."}, status=status.HTTP_404_NOT_FOUND)
        existing = Connection.objects.filter(corps_member=request.user, trainer=user).first()
        courses = annotate_courses(Course.objects.filter(
            trainer=user, is_active=True, is_published=True, is_restricted=False)).order_by("-created_at")
        enrolled = dict(CourseEnrollment.objects.filter(student=request.user, course__in=courses)
                        .values_list("course_id", "status"))
        course_list = []
        for c in courses:
            st = enrolled.get(c.id)
            course_list.append({**course_payload(c, request), "isEnrolled": st == "confirmed", "enrollmentStatus": st})
        data = trainer_public_payload(user, request)
        data.update({"connectionStatus": existing.status if existing else "none",
                     "connectionId": existing.id if existing else None, "courses": course_list})
        return Response(data)


class MyTrainersView(APIView):
    permission_classes = [HasRole("corps_member")]

    def get(self, request):
        try:
            connections = Connection.objects.filter(corps_member=request.user).exclude(status="cancelled") \
                .select_related("trainer", "trainer__profile")
            result = []
            connections = list(connections)
            by_trainer = {}
            for c in annotate_courses(Course.objects.filter(trainer__in=[x.trainer_id for x in connections], is_active=True,
                                                            is_published=True, is_restricted=False)):
                by_trainer.setdefault(c.trainer_id, []).append(c)
            for conn in connections:
                trainer = conn.trainer
                card = trainer_public_payload(trainer, request)
                card.update({"connectionStatus": conn.status, "connectedAt": conn.connected_at.isoformat(),
                             "courses": [course_payload(c, request) for c in by_trainer.get(trainer.id, [])]})
                result.append(card)
            return Response({"trainers": result})
        except Exception as exc:
            _log_error("My trainers error", exc=exc)
            return Response({"error": "Failed to load trainers."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConnectTrainerView(APIView):
    """Follow a trainer without enrolling. Enrolling in any of their courses ALSO connects automatically."""
    permission_classes = [HasRole("corps_member")]

    def post(self, request):
        trainer_id = request.data.get("trainerId")
        if not trainer_id:
            return Response({"error": "Trainer ID is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            trainer = User.objects.select_related("profile").get(
                id=trainer_id, is_active=True, profile__role="trainer", profile__is_authorized=True)
        except (User.DoesNotExist, ValueError):
            return Response({"error": "Trainer not found."}, status=status.HTTP_404_NOT_FOUND)
        conn = ensure_trainer_connection(request.user, trainer, "active")
        created = getattr(conn, "_created", False)
        if created:
            who = request.user.get_full_name() or request.user.email
            notify(trainer, "New connection", f"{who} connected with you.", reason="connection_approved",
                   link="/app/my-corpers", email=False)
            notify(request.user, "Connected to trainer",
                   f"You are now connected with {trainer.get_full_name() or trainer.email}.",
                   reason="trainer_connected", link=f"/app/trainers/{trainer.id}", email=False)
        request.user.profile.has_selected_trainers = True
        request.user.profile.save(update_fields=["has_selected_trainers"])
        return Response({"connection": connection_payload(conn), "alreadyConnected": not created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


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
            for course in annotate_courses(trainer_courses):
                enrollment = enrollment_map.get(course.id)
                payload = course_payload(course, request)
                courses_with_status.append({
                    **payload,
                    "isFull": payload["availableSlots"] <= 0,
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
