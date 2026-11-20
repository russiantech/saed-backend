from django.conf import settings
from django.http import JsonResponse


def api_root(_request):
    """What you see at the API host's "/": proves the app is running and where things live (no data, no secrets)."""
    docs = getattr(settings, "API_DOCS", "staff")
    return JsonResponse({
        "service": "SAED IMS API",
        "status": "ok",
        "api": "/api/",
        "health": "/api/health/",
        "docs": "/api/docs/" if docs != "off" else None,
        "docsAccess": docs,
    })
