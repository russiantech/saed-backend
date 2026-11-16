"""Step 2/3: DATA migration.

* gives every course a public UUID and keeps currently-visible courses published
* moves every lesson onto its course (Course → Lessons) and renumbers lesson order
* module price/lock  → per-lesson price/lock (total price preserved, split evenly)
* paid module purchases (ModuleAccess) → LessonAccess for each lesson in the module
* FastTrackVideo rows → video Lessons (price kept, upload fee treated as already paid)
* TrainerFeaturePayment rows → Payment ledger (type "legacy_feature")
* LessonAccess legacy status values mapped to the new vocabulary
"""
import math
import uuid
from decimal import Decimal

from django.db import migrations


def forwards(apps, schema_editor):
    Course = apps.get_model("saed", "Course")
    Module = apps.get_model("saed", "Module")
    Lesson = apps.get_model("saed", "Lesson")
    LessonAccess = apps.get_model("saed", "LessonAccess")
    ModuleAccess = apps.get_model("saed", "ModuleAccess")
    FastTrackVideo = apps.get_model("saed", "FastTrackVideo")
    TrainerFeaturePayment = apps.get_model("saed", "TrainerFeaturePayment")
    Payment = apps.get_model("saed", "Payment")

    # 1. public ids + keep currently visible courses visible
    for course in Course.objects.all().iterator():
        course.public_id = uuid.uuid4()
        if course.is_active:
            course.is_published = True
        course.save(update_fields=["public_id", "is_published"])

    # 2. lessons onto their course; orphans removed
    for lesson in Lesson.objects.filter(course__isnull=True).select_related("module"):
        if lesson.module_id:
            lesson.course_id = lesson.module.course_id
            lesson.save(update_fields=["course"])
        else:
            lesson.delete()

    # 3. module pricing → lesson pricing (total preserved, split evenly, whole naira)
    for module in Module.objects.all():
        if not (module.is_locked and module.price and module.price > 0):
            continue
        lessons = list(Lesson.objects.filter(module_id=module.id, is_free_preview=False))
        if not lessons:
            continue
        per = Decimal(math.ceil(Decimal(module.price) / len(lessons)))
        for les in lessons:
            if not (les.price and les.price > 0):
                les.price = per
                les.is_locked = True
                les.save(update_fields=["price", "is_locked"])

    # 4. paid module purchases → access to every lesson of that module
    for ma in ModuleAccess.objects.filter(status="success", payment_verified=True):
        first = True
        for les in Lesson.objects.filter(module_id=ma.module_id):
            la, _ = LessonAccess.objects.get_or_create(
                student_id=ma.student_id, lesson_id=les.id,
                defaults={"status": "active"},
            )
            la.status = "active"
            la.source = "legacy_module"
            la.payment_reference = la.payment_reference or ma.payment_reference
            if first:
                la.amount_paid = ma.amount_paid
                first = False
            la.save()

    # legacy LessonAccess vocabulary
    for la in LessonAccess.objects.exclude(source="legacy_module"):
        old = la.status
        if old == "success":
            la.status = "active"
            la.source = "paystack" if la.payment_reference else "trainer_grant"
        elif old in ("refunded",):
            la.status = "revoked"
        elif old not in ("pending", "requested", "active", "revoked"):
            la.status = "pending"
        la.save(update_fields=["status", "source"])

    # 5/7. order lessons per course, then append fast-track videos as lessons
    for course in Course.objects.all().iterator():
        existing = list(
            Lesson.objects.filter(course_id=course.id).select_related("module")
        )
        existing.sort(key=lambda l: ((l.module.order if l.module_id else 0), l.order, l.id))
        n = 0
        for les in existing:
            n += 1
            if les.order != n:
                les.order = n
                les.save(update_fields=["order"])
        for v in FastTrackVideo.objects.filter(course_id=course.id).order_by("order", "id"):
            n += 1
            price = v.price or Decimal("0")
            Lesson.objects.create(
                course_id=course.id, title=v.title[:150], description=v.description,
                content_type="video", video_url=v.video_url, duration_seconds=v.duration_seconds,
                order=n, price=price,
                is_locked=bool(price > 0 and not v.is_free_preview),
                video_upload_paid=True, video_upload_reference="legacy-fast-track",
                is_published=True,
            )

    # 6. content-locking fee history → unified ledger
    status_map = {"success": "success", "failed": "failed", "refunded": "refunded"}
    for p in TrainerFeaturePayment.objects.all():
        kobo = int(round(float(p.amount) * 100))
        ok = p.status == "success"
        Payment.objects.get_or_create(
            reference=p.payment_reference[:64],
            defaults=dict(
                payment_type="legacy_feature",
                status=status_map.get(p.status, "pending"),
                payer_id=p.trainer_id, trainer_id=p.trainer_id,
                payer_email="", expected_amount_kobo=kobo,
                paid_amount_kobo=kobo if ok else 0, requested_amount_kobo=kobo if ok else 0,
                platform_fee_kobo=kobo if ok else 0,
                verified_at=p.verified_at, metadata=p.metadata or {},
            ),
        )


class Migration(migrations.Migration):

    dependencies = [("saed", "0002_unified_lessons_payments_schema")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
