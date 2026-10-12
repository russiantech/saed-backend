from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include, re_path
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
import base64

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


@csrf_exempt
def clear_session(request):
    """Flush session and force browser to drop the sessionid cookie."""
    request.session.flush()
    response = JsonResponse({"ok": True})
    response.delete_cookie("sessionid")
    return response


def favicon(request):
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAn0B9Sl6Jd0AAAAASUVORK5CYII="
    )
    return HttpResponse(data, content_type="image/png")

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


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("saed.urls")),
    path("favicon.ico", favicon),
    path("api/auth/clear-session/", clear_session, name="clear_session"),
    re_path(r"^api/docs/$", schema_view.with_ui("swagger", cache_timeout=0), name="swagger-ui"),
    re_path(r"^api/redoc/$", schema_view.with_ui("redoc", cache_timeout=0), name="redoc"),
    re_path(r"^api/schema/$", schema_view.without_ui(cache_timeout=0), name="schema-json"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
