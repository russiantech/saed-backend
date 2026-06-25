from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, re_path
from django.http import HttpResponse

import base64

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


# -----------------------------
# FAVICON (safe fallback)
# -----------------------------
def favicon(request):
    """
    Returns a tiny transparent PNG to prevent browser favicon 404s
    """
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAn0B9Sl6Jd0AAAAASUVORK5CYII="
    )
    return HttpResponse(data, content_type="image/png")


# -----------------------------
# SWAGGER / OPENAPI SCHEMA
# -----------------------------
schema_view = get_schema_view(
    openapi.Info(
        title="SAED API",
        default_version="v1",
        description="SAED API documentation",
        contact=openapi.Contact(email="chrisjsmez@gmail.com"),
        license=openapi.License(name="Proprietary"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)


# -----------------------------
# URL ROUTING
# -----------------------------
urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Core API
    path("api/", include("saed.urls")),

    # Favicon
    path("favicon.ico", favicon),

    # Swagger UI
    re_path(r"^api/docs/$", schema_view.with_ui("swagger", cache_timeout=0), name="swagger-ui"),

    # ReDoc UI
    re_path(r"^api/redoc/$", schema_view.with_ui("redoc", cache_timeout=0), name="redoc"),

    # OpenAPI schema JSON
    re_path(r"^api/schema/$", schema_view.without_ui(cache_timeout=0), name="schema-json"),
]

# -----------------------------
# MEDIA FILES (DEV + SIMPLE PROD)
# -----------------------------
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

