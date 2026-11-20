"""Deployment checks: catch the "works locally, fails in production" misconfigurations at start-up."""
from urllib.parse import urlparse

from django.conf import settings
from django.core.checks import Warning, register

_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac", "sch"}


def _site(url):
    """Approximate registrable domain (good enough for a warning; no public-suffix list needed)."""
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    if len(parts) <= 2 or host.replace(".", "").isdigit():
        return host
    keep = 3 if parts[-2] in _SECOND_LEVEL and len(parts[-1]) == 2 else 2
    return ".".join(parts[-keep:])


@register(deploy=True)
def frontend_and_api_sites(app_configs, **kwargs):
    front, back = getattr(settings, "FRONTEND_URL", ""), getattr(settings, "BACKEND_URL", "")
    out = []
    if not back:
        out.append(Warning(
            "BACKEND_URL is not set.",
            hint="Set BACKEND_URL to this API's public origin (e.g. https://api.example.com); it is used in e-mails and media links.",
            id="saed.W001"))
    elif front and _site(front) != _site(back):
        lax = str(getattr(settings, "SESSION_COOKIE_SAMESITE", "Lax")).lower() != "none"
        if lax:
            out.append(Warning(
                f"FRONTEND_URL ({front}) and BACKEND_URL ({back}) are on different sites, but session cookies are "
                "SameSite=Lax, so browsers will drop them and sign-in will fail ('session could not be established').",
                hint="Host the API on a sub-domain of the app's domain (best), proxy /api through the app's host, or set "
                     "CROSS_SITE_COOKIES=1 (HTTPS only).",
                id="saed.W002"))
    if front and not front.startswith("https://") and not settings.DEBUG:
        out.append(Warning("FRONTEND_URL is not https:// in production.", id="saed.W003"))
    return out
