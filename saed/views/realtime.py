"""
Real-time synchronization view.
Provides low-latency, lightweight sync for user interactions,
connection requests/approvals, live notifications, and profile status changes.
"""
from django.utils.timezone import now
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Connection, Notification, Profile, CourseEnrollment, Complaint
from .base import (
    _log_error, IsAuthenticatedAPI, role_for, connection_payload,
)


class RealtimeSyncView(APIView):
    """
    High-efficiency synchronization endpoint (<5ms response time).
    Called periodically and on visibility changes by the frontend
    to deliver real-time inter-user interaction updates without requiring page reloads.
    """
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        user = request.user
        role = role_for(user)
        profile = getattr(user, "profile", None)

        try:
            # 1. Unread notifications count and recent notifications
            unread_count = Notification.objects.filter(
                user=user, is_read=False
            ).count()

            recent_notifications_qs = Notification.objects.filter(
                user=user
            ).order_by("-created_at")[:10]

            filtered_notifications = []
            for n in recent_notifications_qs:
                if n.reason == "admin_update":
                    continue
                if role == "saed_admin" and n.created_by_role == "dunis_admin":
                    continue
                filtered_notifications.append({
                    "id": n.id,
                    "title": n.title,
                    "message": n.message,
                    "reason": n.reason,
                    "isRead": n.is_read,
                    "createdAt": n.created_at.isoformat(),
                })

            response_data = {
                "timestamp": now().isoformat(),
                "role": role,
                "unreadNotificationsCount": unread_count,
                "latestNotifications": filtered_notifications[:6],
                "profile": {
                    "isAuthorized": profile.is_authorized if profile else False,
                    "hasPaid": profile.has_paid if profile else False,
                    "authorizationStatus": profile.authorization_status if profile else "",
                    "isEmailVerified": profile.is_email_verified if profile else False,
                    "isVerified": profile.is_verified if profile else False,
                },
            }

            # 2. Role-specific interactions (Corps Member <-> Trainer <-> Admin)
            if role == "corps_member":
                connections = Connection.objects.filter(
                    corps_member=user
                ).select_related("trainer", "trainer__profile")
                
                conn_list = [connection_payload(c) for c in connections]
                conn_map = {c.trainer_id: c.status for c in connections}
                response_data["connections"] = conn_list
                response_data["connectionsMap"] = conn_map

            elif role == "trainer":
                connections = Connection.objects.filter(
                    trainer=user
                ).select_related("corps_member", "corps_member__profile")
                
                conn_list = [connection_payload(c) for c in connections]
                response_data["connections"] = conn_list
                response_data["pendingConnectionsCount"] = sum(1 for c in connections if c.status == "pending")
                response_data["activeConnectionsCount"] = sum(1 for c in connections if c.status == "active")

            elif role in ("saed_admin", "dunis_admin"):
                trainer_profiles = Profile.objects.filter(role="trainer").exclude(is_hidden=True)
                admin_stats = {
                    "pendingTrainers": trainer_profiles.filter(authorization_status="pending").count(),
                    "pendingRefunds": CourseEnrollment.objects.filter(refund_requested=True, refund_processed=False).count(),
                    "openComplaints": Complaint.objects.filter(status="open").count(),
                }
                if role == "dunis_admin":
                    admin_stats["pendingPayments"] = trainer_profiles.filter(
                        is_authorized=True, has_paid=False
                    ).count()
                response_data["adminStats"] = admin_stats

            return Response(response_data)
        except Exception as exc:
            _log_error("Realtime sync error", exc=exc)
            return Response({"error": "Failed to sync realtime data."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
