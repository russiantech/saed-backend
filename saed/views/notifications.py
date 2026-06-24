"""
Notification views.
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Notification
from .base import _log_error, _log_info, IsAuthenticatedAPI, role_for


class NotificationListView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        try:
            notifications = Notification.objects.filter(
                user=request.user
            ).order_by("-created_at")[:50]
            unread_count = Notification.objects.filter(
                user=request.user, is_read=False
            ).count()
            user_role = role_for(request.user)
            filtered = []
            for n in notifications:
                if n.reason == "admin_update":
                    continue
                if user_role == "saed_admin" and n.created_by_role == "dunis_admin":
                    continue
                filtered.append(n)
            result = []
            for n in filtered[:50]:
                result.append({
                    "id": n.id,
                    "title": n.title,
                    "message": n.message,
                    "reason": n.reason,
                    "isRead": n.is_read,
                    "createdAt": n.created_at.isoformat(),
                })
            return Response({"notifications": result, "unreadCount": unread_count})
        except Exception as exc:
            _log_error("Notification list error", exc=exc)
            return Response({"error": "Failed to load notifications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NotificationMarkReadView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request, notification_id):
        try:
            notification = Notification.objects.get(
                id=notification_id, user=request.user
            )
            notification.is_read = True
            notification.save(update_fields=["is_read"])
            return Response({"ok": True})
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found."},
                            status=status.HTTP_404_NOT_FOUND)
        except Exception as exc:
            _log_error("Notification mark read error", exc=exc)
            return Response({"error": "Failed to mark notification."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def post(self, request):
        try:
            count = Notification.objects.filter(
                user=request.user, is_read=False
            ).update(is_read=True)
            return Response({"ok": True, "marked": count})
        except Exception as exc:
            _log_error("Notification mark all read error", exc=exc)
            return Response({"error": "Failed to mark notifications."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
