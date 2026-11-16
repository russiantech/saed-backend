"""Lesson management (trainer), lesson viewing (learner), secure media streaming,
premium access (Paystack / direct bank transfer / manual grants)."""
import os
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse
from django.utils.dateparse import parse_date, parse_time
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Course, CourseEnrollment, Lesson, LessonAccess
from ..services import access, config, media
from ..services.notify import course_link, notify
from .base import HasRole, IsAuthenticatedAPI, _log_error, lesson_payload, role_for
from .courses import get_course

User = get_user_model()


def _nf(msg="Lesson not found."):
    return Response({"error": msg}, status=status.HTTP_404_NOT_FOUND)


def _own_lesson(request, lesson_id, for_write=True):
    """Lesson the user may MANAGE: its trainer (or an admin for read-only views)."""
    qs = Lesson.objects.select_related("course", "course__trainer")
    lesson = qs.get(pk=lesson_id)
    if lesson.course.trainer_id == request.user.id:
        return lesson
    if not for_write and access.is_admin(request.user):
        return lesson
    raise Lesson.DoesNotExist


def _parse_price(value):
    try:
        price = Decimal(str(value if value not in (None, "") else 0))
    except InvalidOperation:
        raise ValueError("Enter a valid price.")
    if price < 0 or price > Decimal("10000000"):
        raise ValueError("Enter a valid price.")
    return price.quantize(Decimal("0.01"))


def video_fee_payload(lesson=None):
    fee = config.video_upload_fee()
    return {"feeAmount": float(fee["amount"]), "feeAmountKobo": fee["amountKobo"], "currency": "NGN",
            "feeEnabled": fee["enabled"], "feeApplies": fee["applies"],
            "paid": bool(lesson and lesson.video_upload_paid) or not fee["applies"]}


def _video_payment_required(lesson):
    fee = config.video_upload_fee()
    if fee["applies"] and not lesson.video_upload_paid:
        return Response({
            "error": f"A one-off upload fee of ₦{fee['amount']:,.2f} is required to add a video to this lesson.",
            "requiresVideoUploadPayment": True, "lessonId": lesson.id, **video_fee_payload(lesson),
        }, status=status.HTTP_402_PAYMENT_REQUIRED)
    return None


def _apply_fields(lesson, data, creating=False):
    """Copy editable lesson fields from request data. Returns field errors dict."""
    errors = {}
    if "title" in data:
        t = (data.get("title") or "").strip()
        if not t:
            errors["title"] = "Title is required."
        lesson.title = t[:150]
    if "description" in data:
        lesson.description = (data.get("description") or "").strip()
    if "contentType" in data:
        if data["contentType"] not in dict(Lesson.CONTENT_TYPE_CHOICES):
            errors["contentType"] = "Unsupported content type."
        else:
            lesson.content_type = data["contentType"]
    if "textContent" in data:
        lesson.text_content = data.get("textContent") or ""
    if "documentLink" in data:
        if (data.get("documentLink") or "").strip():
            errors["documentLink"] = "Document links are not supported. Upload a PDF, image or text file so it opens inside the app."
        else:
            lesson.document_url = ""
    if "durationSeconds" in data:
        try:
            lesson.duration_seconds = max(int(data.get("durationSeconds") or 0), 0)
        except (TypeError, ValueError):
            errors["durationSeconds"] = "Enter a valid duration."
    if "scheduledDate" in data:
        raw = data.get("scheduledDate")
        lesson.scheduled_date = parse_date(str(raw)[:10]) if raw else None
        if raw and not lesson.scheduled_date:
            errors["scheduledDate"] = "Use YYYY-MM-DD."
    if "scheduledTime" in data:
        raw = data.get("scheduledTime")
        lesson.scheduled_time = parse_time(str(raw)) if raw else None
        if raw and not lesson.scheduled_time:
            errors["scheduledTime"] = "Use HH:MM."
    if "isPublished" in data:
        lesson.is_published = bool(data.get("isPublished"))
    if "price" in data:
        try:
            lesson.price = _parse_price(data.get("price"))
        except ValueError as exc:
            errors["price"] = str(exc)
    if "isLocked" in data:
        lesson.is_locked = bool(data.get("isLocked"))
    if lesson.is_locked and not (lesson.price and lesson.price > 0):
        errors["price"] = "Set a price greater than ₦0 to lock a lesson, or leave it unlocked to keep it free."
    return errors


class ManageLessonsView(APIView):
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        ref = request.GET.get("courseId")
        qs = Lesson.objects.select_related("course")
        if role_for(request.user) == "trainer":
            qs = qs.filter(course__trainer=request.user)
        if ref:
            try:
                qs = qs.filter(course=get_course(ref))
            except Course.DoesNotExist:
                return Response({"lessons": []})
        return Response({"lessons": [lesson_payload(l, request, request.user, manage=True)
                                     for l in qs.order_by("course_id", "order", "id")]})

    def post(self, request):
        if role_for(request.user) != "trainer":
            return Response({"error": "Only the course trainer can add lessons."}, status=status.HTTP_403_FORBIDDEN)
        ref = request.data.get("courseId")
        if not ref:
            return Response({"error": "courseId is required.", "fields": {"courseId": "Choose a course."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            course = get_course(ref, Course.objects.filter(trainer=request.user))
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        data = request.data
        lesson = Lesson(course=course, content_type="text", is_published=True)
        errors = _apply_fields(lesson, data, creating=True)
        if not (lesson.title or "").strip():
            errors["title"] = "Title is required."
        if errors:
            return Response({"error": "Please correct the highlighted fields.", "fields": errors},
                            status=status.HTTP_400_BAD_REQUEST)
        order = data.get("order")
        lesson.order = int(order) if str(order or "").isdigit() else (
            (course.lessons.aggregate(m=Max("order"))["m"] or 0) + 1)
        lesson.save()
        if lesson.is_published:
            announce_lesson(lesson)
        body = {"lesson": lesson_payload(lesson, request, request.user, manage=True), "videoFee": video_fee_payload(lesson)}
        if lesson.content_type == "video":
            body["requiresVideoUploadPayment"] = not video_fee_payload(lesson)["paid"]
        return Response(body, status=status.HTTP_201_CREATED)


def announce_lesson(lesson):
    """Notify enrolled corps members that a new lesson is available (in-app, no email spam)."""
    ids = CourseEnrollment.objects.filter(course=lesson.course, status="confirmed").values_list("student_id", flat=True)[:500]
    for student in User.objects.filter(id__in=list(ids)):
        notify(student, "New lesson published", f"“{lesson.title}” was added to “{lesson.course.title}”.",
               reason="lesson_published", link=course_link(lesson.course, lesson.id), email=False)


class ManageLessonDetailView(APIView):
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def get(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id, for_write=False)
        except Lesson.DoesNotExist:
            return _nf()
        return Response({"lesson": lesson_payload(lesson, request, request.user, manage=True),
                         "videoFee": video_fee_payload(lesson)})

    def patch(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        data = request.data
        was_published = lesson.is_published
        if "videoLink" in data:
            try:
                link = media.clean_link(data.get("videoLink"))
            except media.MediaError as exc:
                return Response({"error": str(exc), "fields": {"videoLink": str(exc)}}, status=status.HTTP_400_BAD_REQUEST)
            if link:
                blocked = _video_payment_required(lesson)
                if blocked:
                    return blocked
                lesson.video_url = link
                lesson.content_type = "video"
            else:
                lesson.video_url = ""
        errors = _apply_fields(lesson, data)
        if errors:
            return Response({"error": "Please correct the highlighted fields.", "fields": errors},
                            status=status.HTTP_400_BAD_REQUEST)
        lesson.save()
        if lesson.is_published and not was_published:
            announce_lesson(lesson)
        return Response({"lesson": lesson_payload(lesson, request, request.user, manage=True)})

    def delete(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        for f in (lesson.video_file, lesson.document_file):
            if f:
                try:
                    f.storage.delete(f.name)
                except Exception:
                    pass
        lesson.delete()
        return Response({"ok": True})


class LessonUploadView(APIView):
    """Upload a lesson's video or document. Videos require the per-lesson platform fee."""
    permission_classes = [HasRole("trainer")]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        kind = (request.data.get("kind") or "").strip().lower()
        if kind not in ("video", "document"):
            return Response({"error": "kind must be 'video' or 'document'."}, status=status.HTTP_400_BAD_REQUEST)
        upload = request.FILES.get("file")
        if not upload:
            return Response({"error": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)
        if kind == "video":
            blocked = _video_payment_required(lesson)   # checked BEFORE accepting any bytes
            if blocked:
                return blocked
        try:
            media.store_lesson_file(lesson, kind, upload)
        except media.MediaError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Lesson upload error", exc=exc)
            return Response({"error": "Upload failed. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"ok": True, "lesson": lesson_payload(lesson, request, request.user, manage=True)})

    def delete(self, request, lesson_id):
        """Remove an attached file/link: ?kind=video|document"""
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        kind = request.GET.get("kind")
        f = lesson.video_file if kind == "video" else lesson.document_file if kind == "document" else None
        if kind not in ("video", "document"):
            return Response({"error": "kind must be 'video' or 'document'."}, status=status.HTTP_400_BAD_REQUEST)
        if f:
            f.storage.delete(f.name)
        if kind == "video":
            lesson.video_file, lesson.video_url, lesson.video_size = None, "", 0
        else:
            lesson.document_file, lesson.document_url, lesson.document_size = None, "", 0
        lesson.save()
        return Response({"ok": True, "lesson": lesson_payload(lesson, request, request.user, manage=True)})


class LessonReorderView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, course_id):
        try:
            course = get_course(course_id, Course.objects.filter(trainer=request.user))
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        ids = request.data.get("order")
        if not isinstance(ids, list):
            return Response({"error": "order must be a list of lesson ids."}, status=status.HTTP_400_BAD_REQUEST)
        existing = set(course.lessons.values_list("id", flat=True))
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            return Response({"error": "Invalid lesson ids."}, status=status.HTTP_400_BAD_REQUEST)
        if set(ids) != existing or len(ids) != len(existing):
            return Response({"error": "order must contain every lesson of the course exactly once."},
                            status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            for pos, lid in enumerate(ids, start=1):
                Lesson.objects.filter(pk=lid, course=course).update(order=pos)
        return Response({"ok": True})


# ── Learner: open a lesson ────────────────────────────────────────────────────
def _viewer_context(request, lesson):
    user = request.user
    course = lesson.course
    owner = access.is_course_owner(user, course)
    admin = access.is_admin(user)
    can = access.can_consume_course(user, course)
    state = access.lesson_state(user, lesson, can_consume=can, owner_or_admin=owner or admin,
                                access_by_lesson=access.access_map(user, [lesson]))
    return owner, admin, can, state


class LessonViewerView(APIView):
    """Everything the in-app lesson page needs: content (if entitled), lock state, payment options."""
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request, lesson_id):
        try:
            lesson = Lesson.objects.select_related("course", "course__trainer", "course__trainer__profile").get(pk=lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        course = lesson.course
        owner, admin, can, state = _viewer_context(request, lesson)
        if not (owner or admin) and (course.is_restricted or not course.is_published or not course.is_active
                                      or not lesson.is_published):
            return _nf()
        payload = lesson_payload(lesson, request, request.user, state, manage=owner)
        siblings = list(course.lessons.filter(is_published=True).values_list("id", flat=True).order_by("order", "id"))
        idx = siblings.index(lesson.id) if lesson.id in siblings else -1
        bank = None
        p = getattr(course.trainer, "profile", None)
        if state["state"] in ("locked", "requested") and p and p.account_number and p.bank_name and p.account_name:
            bank = {"bankName": p.bank_name, "accountNumber": p.account_number,
                    "accountName": p.account_name, "verified": p.bank_verified}
        acc = LessonAccess.objects.filter(student=request.user, lesson=lesson).first()
        return Response({
            "lesson": payload,
            "course": {"id": str(course.public_id), "title": course.title, "courseType": course.course_type,
                       "trainerId": course.trainer_id},
            "previousLessonId": siblings[idx - 1] if idx > 0 else None,
            "nextLessonId": siblings[idx + 1] if 0 <= idx < len(siblings) - 1 else None,
            "canConsumeCourse": can,
            "inCampBlocked": access.in_camp_blocked(request.user, course),
            "paymentOptions": {
                "paystack": bool(state["state"] in ("locked", "requested") and lesson.requires_payment()),
                "bankTransfer": bank,
                "requestStatus": acc.status if acc else None,
            } if lesson.requires_payment() and not (owner or admin) else None,
        })


class LessonMediaView(APIView):
    """Streams a lesson file after re-checking entitlement. Auth: signed token or session."""
    permission_classes = [AllowAny]

    def get(self, request, lesson_id, kind):
        if kind not in ("video", "document"):
            raise Http404
        try:
            lesson = Lesson.objects.select_related("course", "course__trainer").get(pk=lesson_id)
        except Lesson.DoesNotExist:
            raise Http404
        user = None
        token = request.GET.get("t")
        if token:
            uid = media.read_token(token, lesson.id, kind)
            if uid:
                user = User.objects.filter(pk=uid, is_active=True).first()
        elif request.user and request.user.is_authenticated:
            user = request.user
        if user is None:
            return HttpResponse(status=401)
        course = lesson.course
        owner, admin = access.is_course_owner(user, course), access.is_admin(user)
        if not (owner or admin) and (course.is_restricted or not course.is_published or not course.is_active):
            raise Http404
        if not access.user_can_open_lesson(user, lesson):
            return HttpResponse(status=403)
        mode, target = media.resolve(lesson, kind)
        if mode != "file":
            raise Http404
        if kind == "document" and os.path.splitext(target)[1].lower() not in media.INLINE_VIEWABLE:
            # legacy Office files cannot be shown in-app; we never hand them out as downloads
            return Response({"error": "This file format cannot be viewed in the app. Ask your trainer to re-upload it as a PDF."},
                            status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
        resp = media.serve_file(request, target, inline=True)
        origin = getattr(settings, "FRONTEND_URL", "")
        resp["Content-Security-Policy"] = f"frame-ancestors 'self' {origin}".strip()
        resp.xframe_options_exempt = True
        return resp


# ── Premium access: request (bank transfer), grant, revoke ────────────────────
class LessonRequestAccessView(APIView):
    """Corps member says "I have paid the trainer by bank transfer"; trainer confirms later."""
    permission_classes = [HasRole("corps_member")]

    def post(self, request, lesson_id):
        try:
            lesson = Lesson.objects.select_related("course", "course__trainer", "course__trainer__profile").get(
                pk=lesson_id, is_published=True)
        except Lesson.DoesNotExist:
            return _nf()
        course = lesson.course
        if course.is_restricted or not course.is_published:
            return _nf()
        if not lesson.requires_payment():
            return Response({"error": "This lesson is free."}, status=status.HTTP_400_BAD_REQUEST)
        if not access.can_consume_course(request.user, course):
            return Response({"error": "Enrol in the course first."}, status=status.HTTP_403_FORBIDDEN)
        p = getattr(course.trainer, "profile", None)
        if not (p and p.account_number and p.bank_name):
            return Response({"error": "This trainer has not provided bank details. Pay with Paystack instead."},
                            status=status.HTTP_400_BAD_REQUEST)
        note = (request.data.get("note") or "").strip()[:300]
        with transaction.atomic():
            acc, created = LessonAccess.objects.select_for_update().get_or_create(
                student=request.user, lesson=lesson,
                defaults={"status": "requested", "source": "bank_transfer", "note": note})
            if acc.status == "active":
                return Response({"error": "You already have access to this lesson."}, status=status.HTTP_400_BAD_REQUEST)
            acc.status, acc.source = "requested", "bank_transfer"
            acc.note = note or acc.note
            acc.save()
        who = request.user.get_full_name() or request.user.email
        notify(course.trainer, "Lesson access request",
               f"{who} says they paid ₦{lesson.price:,.2f} by bank transfer for “{lesson.title}”. "
               "Confirm receipt, then activate their access.",
               reason="lesson_access_request", link=f"/app/courses/{course.public_id}?lesson={lesson.id}&tab=access",
               cta_label="Review request")
        return Response({"ok": True, "status": "requested",
                         "message": "Request sent. Your access is activated once the trainer confirms your transfer."})


def _access_row(a):
    return {"id": a.id, "studentId": a.student_id,
            "studentName": a.student.get_full_name() or a.student.email, "studentEmail": a.student.email,
            "lessonId": a.lesson_id, "lessonTitle": a.lesson.title,
            "courseId": str(a.lesson.course.public_id), "courseTitle": a.lesson.course.title,
            "status": a.status, "source": a.source, "amountPaid": str(a.amount_paid),
            "paymentReference": a.payment_reference, "note": a.note,
            "updatedAt": a.updated_at.isoformat(), "grantedAt": a.granted_at.isoformat()}


class LessonAccessListView(APIView):
    """Trainer: who has / requested access to a lesson."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def get(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id, for_write=False)
        except Lesson.DoesNotExist:
            return _nf()
        rows = LessonAccess.objects.filter(lesson=lesson).select_related("student", "lesson", "lesson__course")
        enrolled = CourseEnrollment.objects.filter(course=lesson.course, status="confirmed").select_related("student")
        have = {r.student_id for r in rows}
        return Response({
            "access": [_access_row(a) for a in rows],
            "eligibleStudents": [{"id": e.student_id, "fullName": e.student.get_full_name() or e.student.email,
                                  "email": e.student.email} for e in enrolled if e.student_id not in have],
        })


class AccessRequestsView(APIView):
    """Trainer inbox: pending bank-transfer requests across all of their lessons."""
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        rows = LessonAccess.objects.filter(lesson__course__trainer=request.user, status="requested") \
            .select_related("student", "lesson", "lesson__course")
        return Response({"requests": [_access_row(a) for a in rows]})


class LessonGrantAccessView(APIView):
    """Trainer/admin: activate access for one enrolled corps member (free grant, or after confirming a transfer)."""
    permission_classes = [HasRole("trainer")]

    def post(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        sid = request.data.get("studentId") or request.data.get("corperId")
        if not sid:
            return Response({"error": "studentId is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            student = User.objects.get(pk=sid, profile__role="corps_member")
        except (User.DoesNotExist, ValueError):
            return Response({"error": "Corps member not found."}, status=status.HTTP_404_NOT_FOUND)
        course = lesson.course
        has_row = LessonAccess.objects.filter(student=student, lesson=lesson).exists()
        if not (access.is_enrolled(student, course) or has_row):
            return Response({"error": "This corps member is not enrolled in the course."}, status=status.HTTP_400_BAD_REQUEST)
        admin_role = access.is_admin(request.user)
        with transaction.atomic():
            acc, _ = LessonAccess.objects.select_for_update().get_or_create(student=student, lesson=lesson)
            if acc.status == "active":          # never overwrite how access was originally obtained
                return Response({"ok": True, "message": "Already has access.", "access": _access_row(acc)})
            from_transfer = acc.status == "requested" and acc.source == "bank_transfer"
            acc.status = "active"
            acc.source = "bank_transfer" if from_transfer else ("admin_grant" if admin_role else "trainer_grant")
            acc.amount_paid = lesson.price if from_transfer else acc.amount_paid
            acc.granted_by = request.user
            acc.save()
        notify(student, "Lesson access granted", f"You can now open “{lesson.title}”.",
               reason="lesson_access_granted", link=course_link(course, lesson.id), cta_label="Start lesson")
        return Response({"ok": True, "message": "Access granted.", "access": _access_row(acc)})


class LessonRevokeAccessView(APIView):
    permission_classes = [HasRole("trainer")]

    def post(self, request, lesson_id):
        try:
            lesson = _own_lesson(request, lesson_id)
        except Lesson.DoesNotExist:
            return _nf()
        sid = request.data.get("studentId")
        acc = LessonAccess.objects.filter(lesson=lesson, student_id=sid).select_related("student", "lesson", "lesson__course").first() \
            if str(sid or "").isdigit() else None
        if not acc:
            return Response({"error": "No access record for that corps member."}, status=status.HTTP_404_NOT_FOUND)
        was_request = acc.status == "requested"
        acc.status = "revoked"
        acc.granted_by = request.user
        acc.save()
        notify(acc.student, "Lesson access request declined" if was_request else "Lesson access removed",
               f"Access to “{lesson.title}” was {'not confirmed' if was_request else 'removed'} by the trainer.",
               reason="lesson_access_revoked", link=course_link(lesson.course, lesson.id), email=False)
        return Response({"ok": True, "access": _access_row(acc)})
