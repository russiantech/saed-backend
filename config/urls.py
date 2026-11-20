from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from saed.apidocs.views import docs_redirect

from .views import api_root

urlpatterns = [
    path("", api_root),
    path("admin/", admin.site.urls),
    path("api/", include("saed.urls")),
    path("docs/", docs_redirect),
    path("redoc/", docs_redirect),
]
# Public media (profile pictures, images ONLY). Lesson videos/documents live in
# PRIVATE_MEDIA_ROOT and are never served from here.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
