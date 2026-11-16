"""Step 3/3: remove obsolete structures now that their data lives in lessons/payments."""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("saed", "0003_migrate_modules_fasttrack_to_lessons")]

    operations = [
        # Course: unique public id, no price, no fast-track flag
        migrations.AlterField(model_name="course", name="public_id", field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
        migrations.RemoveField(model_name="course", name="price"),
        migrations.RemoveField(model_name="course", name="has_fast_track"),
        # Lesson: strictly Course → Lessons
        migrations.AlterField(model_name="lesson", name="course", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lessons", to="saed.course")),
        migrations.RemoveField(model_name="lesson", name="module"),
        migrations.RemoveField(model_name="lesson", name="is_free_preview"),
        migrations.AlterModelOptions(name="lesson", options={"ordering": ["order", "id"]}),
        migrations.DeleteModel(name="ModuleAccess"),
        migrations.DeleteModel(name="Module"),
        migrations.DeleteModel(name="FastTrackVideo"),
        migrations.DeleteModel(name="TrainerFeaturePayment"),
        # LessonAccess: payment_verified superseded by status == "active"
        migrations.RemoveField(model_name="lessonaccess", name="payment_verified"),
        migrations.AlterModelOptions(name="lessonaccess", options={"ordering": ["-updated_at"]}),
        # Profile: fast-track / content-locking removed
        migrations.RemoveField(model_name="profile", name="can_upload_fast_track"),
        migrations.RemoveField(model_name="profile", name="content_locking_enabled"),
        migrations.RemoveField(model_name="profile", name="content_locking_activated_at"),
        migrations.RemoveField(model_name="profile", name="content_locking_payment_reference"),
        # Notification
        migrations.AlterField(model_name="notification", name="reason", field=models.CharField(choices=[("course_restricted", "Course Restricted"), ("course_unrestricted", "Course Unrestricted"), ("course_published", "Course Published"), ("lesson_published", "Lesson Published"), ("course_update", "Course Update"), ("enrolment", "Enrolment"), ("connection_request", "Connection Request"), ("connection_approved", "Connection Approved"), ("connection_declined", "Connection Declined"), ("trainer_connected", "Trainer Connected"), ("admin_update", "Admin Update"), ("user_update", "User Update"), ("payment_initiated", "Payment Initiated"), ("payment_success", "Payment Confirmed"), ("payment_failed", "Payment Problem"), ("lesson_access_granted", "Lesson Access Granted"), ("lesson_access_revoked", "Lesson Access Revoked"), ("lesson_access_request", "Lesson Access Request"), ("trainer_verified", "Trainer Verification"), ("bank_verified", "Bank Account"), ("in_camp_deactivated", "In-Camp Access Deactivated")], default="user_update", max_length=40)),
        migrations.AddIndex(model_name="course", index=models.Index(fields=["course_type", "is_published", "is_active"], name="saed_course_course__01b316_idx")),
    ]
