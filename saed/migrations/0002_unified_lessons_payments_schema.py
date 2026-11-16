"""Step 1/3 of the Course → Lessons refactor: ADDITIVE schema changes only.

Nothing is dropped here, so existing data stays intact until 0003 has copied it.
"""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import saed.storage


class Migration(migrations.Migration):

    dependencies = [
        ("saed", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ── Payment ledger + webhook idempotency ─────────────────────────────
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(max_length=64, unique=True)),
                ("payment_type", models.CharField(choices=[("trainer_activation", "Trainer activation"), ("video_upload", "Video upload fee"), ("lesson_access", "Premium lesson access"), ("legacy_feature", "Legacy content-locking fee")], max_length=24)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("success", "Success"), ("failed", "Failed"), ("abandoned", "Abandoned"), ("mismatch", "Needs review (amount/currency mismatch)"), ("refunded", "Refunded")], default="pending", max_length=12)),
                ("payer_email", models.EmailField(blank=True, max_length=254)),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("expected_amount_kobo", models.BigIntegerField()),
                ("paid_amount_kobo", models.BigIntegerField(default=0)),
                ("requested_amount_kobo", models.BigIntegerField(default=0)),
                ("gateway_fees_kobo", models.BigIntegerField(default=0)),
                ("platform_fee_kobo", models.BigIntegerField(default=0)),
                ("trainer_share_kobo", models.BigIntegerField(default=0)),
                ("subaccount_code", models.CharField(blank=True, max_length=64)),
                ("gateway_status", models.CharField(blank=True, max_length=32)),
                ("gateway_message", models.CharField(blank=True, max_length=255)),
                ("channel", models.CharField(blank=True, max_length=32)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("course", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments", to="saed.course")),
                ("payer", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments_made", to=settings.AUTH_USER_MODEL)),
                ("trainer", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments_received", to=settings.AUTH_USER_MODEL)),
                ("lesson", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="payments", to="saed.lesson")),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="payment", index=models.Index(fields=["payment_type", "status"], name="saed_paymen_payment_97b624_idx")),
        migrations.AddIndex(model_name="payment", index=models.Index(fields=["payer", "status"], name="saed_paymen_payer_i_149e99_idx")),
        migrations.AddIndex(model_name="payment", index=models.Index(fields=["trainer", "status"], name="saed_paymen_trainer_00f8fa_idx")),
        migrations.CreateModel(
            name="WebhookEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=128, unique=True)),
                ("event", models.CharField(max_length=64)),
                ("reference", models.CharField(blank=True, max_length=64)),
                ("outcome", models.CharField(blank=True, max_length=32)),
                ("received_at", models.DateTimeField(auto_now_add=True)),
                ("attempts", models.PositiveIntegerField(default=1)),
            ],
            options={"ordering": ["-received_at"]},
        ),
        # ── Course ───────────────────────────────────────────────────────────
        migrations.AddField(model_name="course", name="public_id", field=models.UUIDField(editable=False, null=True)),
        # ── Lesson ───────────────────────────────────────────────────────────
        migrations.AddField(model_name="lesson", name="video_file", field=models.FileField(blank=True, max_length=300, storage=saed.storage.get_private_storage, upload_to="lesson_videos/")),
        migrations.AddField(model_name="lesson", name="document_file", field=models.FileField(blank=True, max_length=300, storage=saed.storage.get_private_storage, upload_to="lesson_documents/")),
        migrations.AddField(model_name="lesson", name="video_size", field=models.BigIntegerField(default=0)),
        migrations.AddField(model_name="lesson", name="document_size", field=models.BigIntegerField(default=0)),
        migrations.AddField(model_name="lesson", name="is_published", field=models.BooleanField(default=True)),
        migrations.AddField(model_name="lesson", name="updated_at", field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False),
        # ── LessonAccess ─────────────────────────────────────────────────────
        migrations.AddField(model_name="lessonaccess", name="source", field=models.CharField(choices=[("paystack", "Paystack payment"), ("bank_transfer", "Direct bank transfer"), ("trainer_grant", "Granted by trainer"), ("admin_grant", "Granted by admin"), ("legacy_module", "Migrated module purchase")], default="paystack", max_length=16)),
        migrations.AddField(model_name="lessonaccess", name="note", field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name="lessonaccess", name="updated_at", field=models.DateTimeField(auto_now=True, default=django.utils.timezone.now), preserve_default=False),
        migrations.AddField(model_name="lessonaccess", name="payment", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="accesses", to="saed.payment")),
        migrations.AddField(model_name="lessonaccess", name="granted_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="lesson_accesses_granted", to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name="lessonaccess", name="status", field=models.CharField(choices=[("pending", "Awaiting payment"), ("requested", "Transfer claimed – awaiting trainer confirmation"), ("active", "Active"), ("revoked", "Revoked")], default="pending", max_length=12)),
        # ── Notification / Profile ───────────────────────────────────────────
        migrations.AddField(model_name="notification", name="link", field=models.CharField(blank=True, default="", max_length=300)),
        migrations.AddField(model_name="profile", name="bank_verified", field=models.BooleanField(default=False)),
        migrations.AddField(model_name="profile", name="bank_verified_at", field=models.DateTimeField(blank=True, null=True)),
    ]
