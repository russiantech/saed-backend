from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
import base64
from django.http import HttpResponse


def favicon(request):
    # serve a tiny 1x1 transparent PNG so browsers won't 404 for /favicon.ico
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAn0B9Sl6Jd0AAAAASUVORK5CYII="
    )
    return HttpResponse(data, content_type="image/png")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("saed.urls")),
    path("favicon.ico", favicon),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
