import hashlib
import hmac
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from datetime import timedelta

from django.utils.timezone import now

from ..models import Course, Lesson, Profile, Stream
from ..services import streams as stream_svc

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2048
PDF = b"%PDF-1.4\n" + b"0" * 512


def mk_user(email, role, **profile):
    u = User.objects.create_user(email, email, "Password123!", first_name=email.split("@")[0].title(), last_name="Test")
    defaults = {"role": role, "phone": f"080{User.objects.count():08d}"}
    if role == "trainer":
        defaults.update(is_authorized=True, has_paid=True, payment_verified=True, authorization_status="approved")
    if role in ("saed_admin", "dunis_admin"):
        defaults.update(is_email_verified=True)
    defaults.update(profile)
    Profile.objects.create(user=u, **defaults)
    return u


def mk_stream(number=1, *, year=None, start=-10, end=20, grace=0, **kw):
    """A stream whose window is [today+start, today+end] days (negative start = already running)."""
    today = now().date()
    d = dict(year=year or today.year, number=number, start_date=today + timedelta(days=start),
             end_date=today + timedelta(days=end), deactivation_grace_days=grace)
    d.update(kw)
    return Stream.objects.create(**d)


def mk_incamp(email, role, stream, **profile):
    """An In-Camp corps member / trainer with a live membership in `stream`."""
    u = mk_user(email, role, account_mode="in_camp", **profile)
    stream_svc.join_stream(u, stream, role)
    return u


def login(user):
    c = Client()
    c.force_login(user)
    return c


def post(client, path, payload=None, **extra):
    return client.post(path, data=json.dumps(payload or {}), content_type="application/json", **extra)


def patch(client, path, payload):
    return client.patch(path, data=json.dumps(payload), content_type="application/json")


def put(client, path, payload):
    return client.put(path, data=json.dumps(payload), content_type="application/json")


def mk_course(trainer, **kw):
    d = dict(title="ICT Skills", category="ict", trainer=trainer, is_published=True, max_students=20)
    d.update(kw)
    return Course.objects.create(**d)


def mk_lesson(course, **kw):
    d = dict(title="Lesson", course=course, order=1)
    d.update(kw)
    return Lesson.objects.create(**d)


def mp4(name="v.mp4", data=MP4):
    return SimpleUploadedFile(name, data, content_type="video/mp4")


def pdf(name="notes.pdf", data=PDF):
    return SimpleUploadedFile(name, data, content_type="application/pdf")


def sign(secret, body: bytes):
    return hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()


def gateway_success(reference, kobo, email, *, fees=0, bearer_fees=False, currency="NGN", requested=True, tx_id=1001, **extra):
    """A Paystack-shaped verify/webhook `data` object."""
    d = {"id": tx_id, "status": "success", "reference": reference,
         "amount": kobo + (fees if bearer_fees else 0), "fees": fees, "currency": currency,
         "channel": "card", "gateway_response": "Successful", "customer": {"email": email}}
    if requested:
        d["requested_amount"] = kobo
    d.update(extra)
    return d
