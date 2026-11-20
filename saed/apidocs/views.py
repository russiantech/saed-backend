"""Serve the OpenAPI document and the Swagger UI / ReDoc pages (offline: assets are vendored)."""
from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .builder import build_spec


def _allowed(request):
    mode = getattr(settings, "API_DOCS", "staff")
    if mode == "off":
        return False
    if mode == "public":
        return True
    u = request.user
    return bool(u.is_authenticated and (u.is_staff or u.is_superuser or _is_admin(u)))


def _is_admin(user):
    try:
        return user.profile.role in ("saed_admin", "dunis_admin")
    except Exception:
        return False


def _guard(request):
    if not _allowed(request):
        # 404 (not 403) so that a disabled/private docs site is indistinguishable from "no docs".
        raise Http404()


@require_GET
@never_cache
def openapi_json(request):
    _guard(request)
    return JsonResponse(build_spec(), json_dumps_params={"indent": 2})


_CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; worker-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")


def _api_base(request):
    """'/api/' derived from the docs URL itself, so the pages keep working when the API is mounted elsewhere."""
    return request.path.rsplit("/", 2)[0] + "/"


def _page(html):
    r = HttpResponse(html)
    r["Content-Security-Policy"] = _CSP
    return r


@require_GET
@never_cache
def swagger_ui(request):
    _guard(request)
    base = _api_base(request)
    css, js = static("saed/apidocs/swagger/swagger-ui.css"), static("saed/apidocs/swagger/swagger-ui-bundle.js")
    return _page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SAED API — Swagger UI</title>
<link rel="stylesheet" href="{css}"><style>body{{margin:0}}.topbar{{display:none}}</style></head>
<body><div id="swagger-ui"></div><script src="{js}"></script><script>
function csrf(){{var m=document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);return m?decodeURIComponent(m[1]):null}}
window.ui=SwaggerUIBundle({{url:"{base}openapi.json",
 dom_id:"#swagger-ui",deepLinking:true,persistAuthorization:true,tryItOutEnabled:false,
 requestInterceptor:function(req){{req.credentials="include";var t=csrf();if(t&&!/^(GET|HEAD|OPTIONS)$/i.test(req.method)){{req.headers["X-CSRFToken"]=t}}return req}}}});
fetch("{base}csrf/",{{credentials:"include"}}).catch(function(){{}});
</script></body></html>""")


@require_GET
@never_cache
def redoc(request):
    _guard(request)
    base = _api_base(request)
    js = static("saed/apidocs/redoc/redoc.standalone.js")
    return _page(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SAED API — ReDoc</title>
<style>body{{margin:0}}</style></head><body><div id="r"></div><script src="{js}"></script>
<script>Redoc.init("{base}openapi.json",{{hideDownloadButton:false}},document.getElementById("r"))</script></body></html>""")


def docs_redirect(request):
    return redirect("/api/docs/", permanent=False)
