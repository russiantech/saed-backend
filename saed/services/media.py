"""Lesson file handling: validation, private storage, signed in-app streaming URLs.

* Uploaded videos/documents live in PRIVATE_MEDIA_ROOT (never under MEDIA_URL).
* The API hands the frontend a short-lived signed URL bound to (user, lesson, kind).
  The stream endpoint re-checks the user's entitlement on every request, so revoking
  access or restricting a course takes effect immediately.
* Range requests are supported so the HTML5 player can seek.
"""
import mimetypes
import os
from urllib.parse import urlparse

from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils.text import get_valid_filename

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
DOC_EXT = {".pdf", ".txt", ".jpg", ".jpeg", ".png", ".webp"}   # only formats that render inside the app
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
INLINE_VIEWABLE = {".pdf", ".txt"} | {".jpg", ".jpeg", ".png", ".gif", ".webp"}
SALT = "saed.lesson-media"
CHUNK = 1024 * 1024


class MediaError(Exception):
    pass


def _max_bytes(kind):
    if kind == "video":
        return int(getattr(settings, "SAED_MAX_VIDEO_BYTES", 500 * 1024 * 1024))
    return int(getattr(settings, "SAED_MAX_DOCUMENT_BYTES", 100 * 1024 * 1024))


def _sniff_ok(ext: str, head: bytes) -> bool:
    """Light magic-number check so renamed executables/HTML are rejected."""
    if ext == ".pdf":
        return head.startswith(b"%PDF")
    if ext == ".mp4":
        return head[4:8] == b"ftyp"
    if ext == ".mov":
        return head[4:8] in (b"ftyp", b"moov", b"wide", b"free", b"mdat", b"skip")
    if ext in (".webm", ".mkv"):
        return head.startswith(b"\x1a\x45\xdf\xa3")
    if ext == ".avi":
        return head.startswith(b"RIFF")
    if ext in (".docx", ".pptx", ".xlsx"):
        return head.startswith(b"PK")
    if ext in (".doc", ".ppt", ".xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")
    if ext == ".txt":
        return b"\x00" not in head
    if ext in IMAGE_EXT:
        return image_magic_ok(ext, head)
    return False


IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
PROFILE_DOC_EXT = {".pdf"} | IMAGE_EXT      # in-app viewable formats only
MAX_PROFILE_BYTES = 10 * 1024 * 1024


def image_magic_ok(ext: str, head: bytes) -> bool:
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def validate_profile_file(uploaded, allow_documents=False):
    """Profile pictures / partnership letters. Strict extension + size + magic-number check."""
    ext = os.path.splitext(uploaded.name)[1].lower()
    allowed = PROFILE_DOC_EXT if allow_documents else IMAGE_EXT
    if ext not in allowed:
        raise MediaError(f"Unsupported file type ({ext or 'none'}). Allowed: {', '.join(sorted(allowed))}")
    if uploaded.size == 0 or uploaded.size > MAX_PROFILE_BYTES:
        raise MediaError("File must be between 1 byte and 10 MB.")
    head = uploaded.read(16)
    uploaded.seek(0)
    ok = image_magic_ok(ext, head) if ext in IMAGE_EXT else _sniff_ok(ext, head)
    if not ok:
        raise MediaError("The file contents do not match its extension.")


_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")


def clean_link(value: str, *, forbid_video=False) -> str:
    """Validate a user-supplied external link (http/https only). Raises MediaError."""
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or len(value) > 500:
        raise MediaError("Enter a valid http(s) link.")
    if forbid_video:
        host = parsed.netloc.lower().split(":")[0]
        if os.path.splitext(parsed.path)[1].lower() in VIDEO_EXT or any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS):
            raise MediaError("Video links go in the video field.")
    return value


def validate_upload(uploaded, kind: str):
    """kind: video | document. Raises MediaError with a user-facing message."""
    ext = os.path.splitext(uploaded.name)[1].lower()
    allowed = VIDEO_EXT if kind == "video" else DOC_EXT
    if ext not in allowed:
        raise MediaError(f"Unsupported {kind} type ({ext or 'none'}). Allowed: {', '.join(sorted(allowed))}")
    if uploaded.size > _max_bytes(kind):
        mb = _max_bytes(kind) // (1024 * 1024)
        raise MediaError(f"File too large. Maximum for {kind}s is {mb} MB.")
    if uploaded.size == 0:
        raise MediaError("The uploaded file is empty.")
    head = uploaded.read(16)
    uploaded.seek(0)
    if not _sniff_ok(ext, head):
        raise MediaError("The file contents do not match its extension.")
    return ext


def store_lesson_file(lesson, kind: str, uploaded):
    """Replace the lesson's video/document with the uploaded file (private storage)."""
    validate_upload(uploaded, kind)
    field = lesson.video_file if kind == "video" else lesson.document_file
    old = field.name if field else ""
    safe = get_valid_filename(uploaded.name)
    target = f"lesson_{lesson.id}_{safe}"
    if kind == "video":
        lesson.video_file.save(target, uploaded, save=False)
        lesson.video_size = uploaded.size
        lesson.video_url = ""            # an uploaded file supersedes any link
        lesson.content_type = "video"
    else:
        lesson.document_file.save(target, uploaded, save=False)
        lesson.document_size = uploaded.size
        lesson.document_url = ""
        if lesson.content_type == "text":
            lesson.content_type = "document"
    lesson.save()
    if old:
        try:
            (lesson.video_file if kind == "video" else lesson.document_file).storage.delete(old)
        except Exception:
            pass


# ── Resolution: file in private storage | legacy local upload | external link ─────────
def _legacy_local_path(url: str):
    """Old uploads saved URLs like https://api/media/uploads/videos/x.mp4 inside MEDIA_ROOT."""
    if not url:
        return None
    path = urlparse(url).path or ""
    prefix = (getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if not path.startswith(prefix):
        return None
    rel = path[len(prefix):].lstrip("/")
    if not rel.startswith(("uploads/videos/", "uploads/documents/", "uploads/lessons/")):
        return None
    full = os.path.normpath(os.path.join(str(settings.MEDIA_ROOT), rel))
    root = os.path.normpath(str(settings.MEDIA_ROOT))
    if not full.startswith(root + os.sep) or not os.path.isfile(full):
        return None
    return full


def resolve(lesson, kind: str):
    """→ ("file", abs_path) | ("external", url) | (None, None)"""
    f = lesson.video_file if kind == "video" else lesson.document_file
    url = lesson.video_url if kind == "video" else lesson.document_url
    if f:
        try:
            return "file", f.path
        except Exception:
            return None, None
    legacy = _legacy_local_path(url)
    if legacy:
        return "file", legacy
    if url:
        return "external", url
    return None, None


# ── Signed URLs ───────────────────────────────────────────────────────────────
def make_token(user_id, lesson_id, kind) -> str:
    return signing.dumps({"u": user_id, "l": lesson_id, "k": kind}, salt=SALT)


def read_token(token, lesson_id, kind):
    ttl = int(getattr(settings, "SAED_MEDIA_TOKEN_TTL", 3600))
    try:
        data = signing.loads(token, salt=SALT, max_age=ttl)
    except signing.BadSignature:
        return None
    if data.get("l") != lesson_id or data.get("k") != kind:
        return None
    return data.get("u")


def backend_origin(request=None) -> str:
    explicit = (getattr(settings, "BACKEND_URL", "") or getattr(settings, "MEDIA_PUBLIC_URL", "") or "").rstrip("/")
    if explicit:
        return explicit
    if request is not None:
        return f"{request.scheme}://{request.get_host()}"
    return ""


def stream_url(request, user, lesson, kind) -> str:
    return f"{backend_origin(request)}/api/lessons/{lesson.id}/media/{kind}/?t={make_token(user.id, lesson.id, kind)}"


def media_descriptor(request, user, lesson, kind):
    """What the frontend needs to render the in-app player/viewer (no raw storage path)."""
    mode, target = resolve(lesson, kind)
    if mode is None:
        return None
    if mode == "external":
        return {"mode": "external", "url": target}
    ext = os.path.splitext(target)[1].lower()
    mime = mimetypes.guess_type(target)[0] or "application/octet-stream"
    return {
        "mode": "file", "url": stream_url(request, user, lesson, kind), "mime": mime,
        "extension": ext, "name": os.path.basename(target),
        "size": os.path.getsize(target) if os.path.exists(target) else 0,
        "inlineViewable": kind == "video" or ext in INLINE_VIEWABLE,
    }


# ── Streaming with HTTP Range support ────────────────────────────────────────
def _iter_range(path, start, length):
    with open(path, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            chunk = fh.read(min(CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def serve_file(request, path: str, inline=True):
    if not os.path.isfile(path):
        raise Http404("File missing")
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    disp = "inline" if inline else "attachment"
    name = os.path.basename(path).replace('"', "")
    rng = request.headers.get("Range", "")
    start, end, status = 0, size - 1, 200
    if rng.startswith("bytes=") and size > 0:
        try:
            s, _, e = rng[6:].split(",")[0].partition("-")
            if s == "":
                n = int(e)
                start, end = max(size - n, 0), size - 1
            else:
                start = int(s)
                end = int(e) if e else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                raise ValueError
            status = 206
        except ValueError:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
    length = end - start + 1
    resp = StreamingHttpResponse(_iter_range(path, start, length), status=status, content_type=ctype)
    resp["Content-Length"] = str(length)
    resp["Accept-Ranges"] = "bytes"
    if status == 206:
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
    resp["Content-Disposition"] = f'{disp}; filename="{name}"'
    resp["Cache-Control"] = "private, no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


# ── Partnership letters (private, in-app only) ────────────────────────────────
LETTER_KINDS = {".pdf": "pdf", ".jpg": "image", ".jpeg": "image", ".png": "image", ".gif": "image", ".webp": "image"}


def letter_path(profile):
    """Absolute path of a profile's partnership letter, or None when there is no file on disk.

    New uploads live in PRIVATE storage. Letters uploaded by older versions sit under the public
    MEDIA_ROOT; they are still found (and should be moved with `manage.py move_partnership_letters`).
    """
    name = profile.partnership_letter.name if profile and profile.partnership_letter else ""
    if not name:
        return None
    for root in (settings.PRIVATE_MEDIA_ROOT, settings.MEDIA_ROOT):
        full = os.path.normpath(os.path.join(str(root), name))
        if full.startswith(os.path.normpath(str(root)) + os.sep) and os.path.isfile(full):
            return full
    return None


def letter_info(profile):
    name = profile.partnership_letter.name if profile and profile.partnership_letter else ""
    if not name:
        return {"available": False, "name": "", "kind": ""}
    ext = os.path.splitext(name)[1].lower()
    return {"available": letter_path(profile) is not None, "name": os.path.basename(name), "kind": LETTER_KINDS.get(ext, "other")}


def _delete_letter_files(name):
    for root in (settings.PRIVATE_MEDIA_ROOT, settings.MEDIA_ROOT):
        full = os.path.normpath(os.path.join(str(root), name))
        if full.startswith(os.path.normpath(str(root)) + os.sep) and os.path.isfile(full):
            try:
                os.remove(full)
            except OSError:
                pass


def set_partnership_letter(profile, uploaded):
    """Validate + store a (new or replacement) letter; the superseded file is removed. Caller saves the profile."""
    validate_profile_file(uploaded, allow_documents=True)
    old = profile.partnership_letter.name if profile.partnership_letter else ""
    profile.partnership_letter = uploaded
    return old


def discard_old_letter(old_name, profile):
    if old_name and old_name != (profile.partnership_letter.name if profile.partnership_letter else ""):
        _delete_letter_files(old_name)
