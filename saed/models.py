from django.conf import settings
from django.db import models
from django.utils.timezone import now

from .storage import get_private_storage


SKILL_AREAS = [
    ("creative_industry", "Creative Industry"),
    ("automobile", "Automobile"),
    ("construction", "Construction"),
    ("agro_allied", "Agro-Allied"),
    ("delivery_logistics", "Delivery & Logistics"),
    ("culinary_catering", "Culinary & Catering"),
    ("cleaning_services", "Cleaning Services"),
    ("green_energy_satellite_security", "Green Energy & Satellite Security"),
    ("ict", "ICT"),
    ("cosmetology", "Cosmetology"),
    ("education", "Education"),
]

SKILL_AREA_KEYS = [k for k, _ in SKILL_AREAS]


class Profile(models.Model):
    ROLE_CHOICES = [
        ("corps_member", "Corps Member"),
        ("trainer", "Trainer"),
        ("saed_admin", "SAED Admin"),
        ("dunis_admin", "Dunis Admin"),
    ]
    AUTH_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("declined", "Declined"),
        ("removed", "Removed"),
        ("restricted", "Restricted"),
    ]
    # Which programme the account belongs to. In-Camp and Post-Camp are separate tracks that never mix.
    ACCOUNT_MODE_CHOICES = [
        ("in_camp", "In-Camp"),
        ("post_camp", "Post-Camp"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=24, choices=ROLE_CHOICES, default="corps_member")
    phone = models.CharField(max_length=32, blank=True)
    nysc_state_code = models.CharField(max_length=32, blank=True)
    state_of_deployment = models.CharField(max_length=80, blank=True)
    state_of_origin = models.CharField(max_length=80, blank=True)
    lga_of_deployment = models.CharField(max_length=80, blank=True)
    # Place of Primary Assignment (used for Post-Camp discovery)
    ppa = models.CharField(max_length=200, blank=True)
    skill_interest = models.CharField(max_length=80, blank=True)
    skill_interests = models.JSONField(default=list, blank=True)
    is_authorized = models.BooleanField(default=False)
    authorization_status = models.CharField(max_length=16, choices=AUTH_STATUS_CHOICES, default="pending")
    has_paid = models.BooleanField(default=False)
    authorized_at = models.DateTimeField(null=True, blank=True)
    is_email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=64, blank=True)
    email_verification_code = models.CharField(max_length=6, blank=True)
    email_verification_code_at = models.DateTimeField(null=True, blank=True)
    password_reset_token = models.CharField(max_length=64, blank=True)
    password_reset_code = models.CharField(max_length=6, blank=True)

    specialization = models.CharField(max_length=120, blank=True, choices=SKILL_AREAS)
    partner_lgas = models.JSONField(default=list, blank=True)
    years_experience = models.PositiveSmallIntegerField(default=0)
    bio = models.TextField(blank=True)
    company_name = models.CharField(max_length=120, blank=True)
    number_trained = models.PositiveIntegerField(default=0)
    partnership_letter = models.FileField(upload_to="partnership_letters/", storage=get_private_storage, blank=True, max_length=300)
    is_verified = models.BooleanField(default=False)
    has_selected_trainers = models.BooleanField(default=False)
    is_busy_corper = models.BooleanField(default=False)
    payment_verified = models.BooleanField(default=False)
    payment_reference = models.CharField(max_length=128, blank=True)
    payment_verified_at = models.DateTimeField(null=True, blank=True)
    restricted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restricted_profiles",
    )
    restricted_at = models.DateTimeField(null=True, blank=True)
    is_hidden = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    profile_picture = models.ImageField(upload_to="profile_pictures/", blank=True)

    # ─── In-Camp / Post-Camp extensions ───────────────────────────────────────
    account_mode = models.CharField(
        max_length=16, choices=ACCOUNT_MODE_CHOICES, default="post_camp", blank=True
    )
    orientation_camp = models.ForeignKey(
        "OrientationCamp",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="corps_members",
    )
    # When True, In-Camp resources are blocked (set by scheduled task)
    in_camp_access_active = models.BooleanField(default=True)
    in_camp_deactivated_at = models.DateTimeField(null=True, blank=True)

    # Trainer payout details (Paystack split / transfer later)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_code = models.CharField(max_length=20, blank=True)  # Paystack bank code
    account_number = models.CharField(max_length=20, blank=True)
    account_name = models.CharField(max_length=120, blank=True)
    paystack_subaccount_code = models.CharField(max_length=64, blank=True)
    paystack_recipient_code = models.CharField(max_length=64, blank=True)
    # True only after the account name was resolved through Paystack.
    bank_verified = models.BooleanField(default=False)
    bank_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["role", "authorization_status"]), models.Index(fields=["role", "is_authorized"])]

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role})"


class Stream(models.Model):
    """One NYSC orientation stream (up to six per year). Every In-Camp account and course lives inside one stream."""
    year = models.PositiveSmallIntegerField()
    number = models.PositiveSmallIntegerField()  # 1..6
    label = models.CharField(max_length=80, blank=True)  # e.g. "October – November"
    start_date = models.DateField()
    end_date = models.DateField()
    # Days after end_date before the stream's accounts switch off (0 = the day after end_date).
    deactivation_grace_days = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="streams_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-number"]
        constraints = [models.UniqueConstraint(fields=["year", "number"], name="uniq_stream_year_number")]

    def __str__(self):
        return self.name

    @property
    def name(self):
        return f"{self.year} Stream {self.number}" + (f" ({self.label})" if self.label else "")

    @property
    def deactivation_date(self):
        from datetime import timedelta
        return self.end_date + timedelta(days=self.deactivation_grace_days)

    def is_past_deactivation(self, today=None):
        return (today or now().date()) > self.deactivation_date

    def status(self, today=None):
        today = today or now().date()
        if not self.is_active:
            return "closed"
        if today < self.start_date:
            return "upcoming"
        if today <= self.end_date:
            return "running"
        return "grace" if today <= self.deactivation_date else "ended"


class StreamMembership(models.Model):
    """A trainer's or In-Camp corps member's account window inside one stream (life-cycle is per stream)."""
    STATUS_CHOICES = [("active", "Active"), ("expired", "Expired"), ("deactivated", "Deactivated")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stream_memberships")
    stream = models.ForeignKey(Stream, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=24, choices=[("corps_member", "Corps Member"), ("trainer", "Trainer")])
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "stream"], name="uniq_membership_user_stream")]
        indexes = [models.Index(fields=["stream", "role", "status"]), models.Index(fields=["user", "status"])]

    def __str__(self):
        return f"{self.user_id} @ {self.stream_id} ({self.status})"


class OrientationCamp(models.Model):
    """Official NYSC orientation camp period used for In-Camp SAED."""
    name = models.CharField(max_length=120)  # e.g. "Lagos Orientation Camp Batch A 2026"
    state = models.CharField(max_length=80)
    location = models.CharField(max_length=200, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    # Grace period after end_date before auto-deactivation (default 7 days)
    deactivation_grace_days = models.PositiveSmallIntegerField(default=7)
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True, related_name="camps")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]

    def __str__(self):
        return self.name

    @property
    def deactivation_date(self):
        from datetime import timedelta
        return self.end_date + timedelta(days=self.deactivation_grace_days)

    def is_past_deactivation(self):
        return now().date() > self.deactivation_date


class PlatformSetting(models.Model):
    """
    Singleton-style configurable platform settings.
    Used for premium feature pricing, default grace days, etc.
    """
    key = models.CharField(max_length=64, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.key

    @classmethod
    def get(cls, key, default=None):
        try:
            return cls.objects.get(key=key).value
        except cls.DoesNotExist:
            return default

    @classmethod
    def set(cls, key, value):
        obj, _ = cls.objects.update_or_create(key=key, defaults={"value": value})
        return obj


import uuid as _uuid


class Course(models.Model):
    """A training programme. Course → Lessons (no modules, no course-level price)."""
    COURSE_TYPE_CHOICES = [
        ("in_camp", "In-Camp"),
        ("post_camp", "Post-Camp"),
    ]

    # Public identifier used in URLs instead of the sequential integer pk.
    public_id = models.UUIDField(default=_uuid.uuid4, unique=True, editable=False)
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
    )
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, blank=True, choices=SKILL_AREAS)
    duration_weeks = models.PositiveSmallIntegerField(default=4)
    location = models.CharField(max_length=120, blank=True, default="Lagos")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    max_students = models.PositiveIntegerField(default=40)
    is_active = models.BooleanField(default=True)
    is_restricted = models.BooleanField(default=False)
    restricted_at = models.DateTimeField(null=True, blank=True)
    restricted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restricted_courses",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    course_type = models.CharField(
        max_length=16, choices=COURSE_TYPE_CHOICES, default="post_camp"
    )
    orientation_camp = models.ForeignKey(
        OrientationCamp,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="courses",
    )
    learning_objectives = models.JSONField(default=list, blank=True)
    prerequisites = models.TextField(blank=True)
    training_location = models.CharField(max_length=200, blank=True)
    training_lga = models.CharField(max_length=80, blank=True)
    training_state = models.CharField(max_length=80, blank=True)
    is_published = models.BooleanField(default=False)
    # In-Camp courses belong to one stream and are proposed by trainers, then opened (approved) by SAED admin.
    stream = models.ForeignKey("Stream", on_delete=models.SET_NULL, null=True, blank=True, related_name="courses")
    APPROVAL_CHOICES = [("pending", "Pending review"), ("approved", "Approved"), ("declined", "Declined")]
    approval_status = models.CharField(max_length=16, choices=APPROVAL_CHOICES, default="approved")
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["stream", "course_type", "approval_status"]),
            models.Index(fields=["course_type", "is_published", "is_active"]),
            models.Index(fields=["trainer", "course_type"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"[{self.course_type}] {self.title}"


class TrainingSession(models.Model):
    """
    Scheduled In-Camp training session (date + time) under a Course.
    """
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="sessions"
    )
    title = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)
    scheduled_date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    is_cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scheduled_date", "start_time"]

    def __str__(self):
        return f"{self.course.title} @ {self.scheduled_date}"


class Lesson(models.Model):
    """
    One unit of learning inside a course. Supports video, documents (PDF etc.),
    text and scheduling. A lesson is FREE unless it is locked AND has a price.
    """
    CONTENT_TYPE_CHOICES = [
        ("video", "Video"),
        ("text", "Text"),
        ("quiz", "Quiz"),
        ("document", "Document"),
    ]
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    content_type = models.CharField(max_length=16, choices=CONTENT_TYPE_CHOICES, default="text")
    # Uploaded material lives in PRIVATE storage and is streamed through the API.
    video_file = models.FileField(
        upload_to="lesson_videos/", storage=get_private_storage, blank=True, max_length=300
    )
    document_file = models.FileField(
        upload_to="lesson_documents/", storage=get_private_storage, blank=True, max_length=300
    )
    video_size = models.BigIntegerField(default=0)
    document_size = models.BigIntegerField(default=0)
    # External links (e.g. YouTube) and legacy values. Never used for uploaded files.
    video_url = models.URLField(blank=True, max_length=500)
    document_url = models.URLField(blank=True, max_length=500)
    text_content = models.TextField(blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    is_published = models.BooleanField(default=True)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_time = models.TimeField(null=True, blank=True)
    # Corps-member access price in NGN. A lesson is paid only when locked AND price > 0.
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_locked = models.BooleanField(default=False)
    # Trainer paid the platform fee for attaching a video to THIS lesson.
    video_upload_paid = models.BooleanField(default=False)
    video_upload_reference = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["course", "is_published", "order"]),
            models.Index(fields=["course", "scheduled_date"]),
        ]

    def __str__(self):
        return self.title

    @property
    def is_paid(self):
        return bool(self.price and self.price > 0)

    def requires_payment(self):
        """Locked + price > 0 → corps member must pay (or be granted access)."""
        return bool(self.is_locked and self.is_paid)

    @property
    def has_video(self):
        return bool(self.video_file or self.video_url)

    @property
    def has_document(self):
        return bool(self.document_file or self.document_url)


class LessonProgress(models.Model):
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_progress"
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="progress")
    completed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "lesson")

    def __str__(self):
        return f"{self.student} - {self.lesson}"


class Payment(models.Model):
    """
    Single ledger for every Paystack transaction.

    payment_type:
      trainer_activation  trainer  → SAED/Dunis   (account activation)
      video_upload        trainer  → SAED/Dunis   (per-lesson video upload fee)
      lesson_access       corps    → trainer      (premium lesson, optional split)
    Amounts are stored in KOBO (integers) to avoid float/decimal drift.
    """
    TYPE_CHOICES = [
        ("trainer_activation", "Trainer activation"),
        ("video_upload", "Video upload fee"),
        ("lesson_access", "Premium lesson access"),
        ("legacy_feature", "Legacy content-locking fee"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("abandoned", "Abandoned"),
        ("mismatch", "Needs review (amount/currency mismatch)"),
        ("refunded", "Refunded"),
    ]

    reference = models.CharField(max_length=64, unique=True)
    payment_type = models.CharField(max_length=24, choices=TYPE_CHOICES)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="payments_made"
    )
    payer_email = models.EmailField(blank=True)
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="payments_received",
    )
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")
    lesson = models.ForeignKey(Lesson, on_delete=models.SET_NULL, null=True, blank=True, related_name="payments")

    currency = models.CharField(max_length=3, default="NGN")
    expected_amount_kobo = models.BigIntegerField()
    paid_amount_kobo = models.BigIntegerField(default=0)       # gateway `amount` (may include fees)
    requested_amount_kobo = models.BigIntegerField(default=0)  # gateway `requested_amount`
    gateway_fees_kobo = models.BigIntegerField(default=0)
    platform_fee_kobo = models.BigIntegerField(default=0)      # SAED/Dunis share
    trainer_share_kobo = models.BigIntegerField(default=0)     # trainer share (lesson_access)
    subaccount_code = models.CharField(max_length=64, blank=True)

    gateway_status = models.CharField(max_length=32, blank=True)
    gateway_message = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=32, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["payment_type", "status"]),
            models.Index(fields=["payer", "status"]),
            models.Index(fields=["trainer", "status"]),
        ]

    def __str__(self):
        return f"{self.reference} {self.payment_type} {self.status}"

    @property
    def expected_amount(self):
        return self.expected_amount_kobo / 100


class WebhookEvent(models.Model):
    """Idempotency + audit trail for Paystack webhooks."""
    key = models.CharField(max_length=128, unique=True)  # "<event>:<transaction id or reference>"
    event = models.CharField(max_length=64)
    reference = models.CharField(max_length=64, blank=True)
    outcome = models.CharField(max_length=32, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-received_at"]


class LessonAccess(models.Model):
    """
    Per-corps-member entitlement to a locked lesson.
    Created by: verified Paystack payment, trainer/admin manual grant, or a
    direct bank-transfer request that the trainer activates.
    """
    SOURCE_CHOICES = [
        ("paystack", "Paystack payment"),
        ("bank_transfer", "Direct bank transfer"),
        ("trainer_grant", "Granted by trainer"),
        ("admin_grant", "Granted by admin"),
        ("legacy_module", "Migrated module purchase"),
    ]
    STATUS_CHOICES = [
        ("pending", "Awaiting payment"),
        ("requested", "Transfer claimed – awaiting trainer confirmation"),
        ("active", "Active"),
        ("revoked", "Revoked"),
    ]
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lesson_accesses"
    )
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="accesses")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="paystack")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="pending")
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="accesses")
    payment_reference = models.CharField(max_length=128, blank=True, default="")
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    note = models.CharField(max_length=300, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="lesson_accesses_granted",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["student", "lesson"]
        ordering = ["-updated_at"]

    @property
    def is_active(self):
        return self.status == "active"


class Connection(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("active", "Active"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    corps_member = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="corpers",
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    connected_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["corps_member", "trainer"]
        ordering = ["-connected_at"]

    def __str__(self):
        return f"{self.corps_member.username} -> {self.trainer.username}"


class CourseEnrollment(models.Model):
    """Free enrolment in a course. Payment fields are retained for historic records."""
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("confirmed", "Confirmed"),
        ("rejected", "Rejected"),
        ("refunded", "Refunded"),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="course_enrollments",
    )
    course = models.ForeignKey(
        "Course",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    payment_reference = models.CharField(max_length=100, blank=True, default="")
    payment_verified = models.BooleanField(default=False)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_enrollments",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    refund_requested = models.BooleanField(default=False)
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refund_processed = models.BooleanField(default=False)
    refund_processed_at = models.DateTimeField(null=True, blank=True)
    refund_note = models.TextField(blank=True, default="")
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["student", "course"]
        indexes = [models.Index(fields=["course", "status"]), models.Index(fields=["student", "status"])]
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.student.username} -> {self.course.title}"


class Notification(models.Model):
    REASON_CHOICES = [
        ("course_restricted", "Course Restricted"),
        ("course_unrestricted", "Course Unrestricted"),
        ("course_published", "Course Published"),
        ("lesson_published", "Lesson Published"),
        ("course_update", "Course Update"),
        ("enrolment", "Enrolment"),
        ("connection_request", "Connection Request"),
        ("connection_approved", "Connection Approved"),
        ("connection_declined", "Connection Declined"),
        ("trainer_connected", "Trainer Connected"),
        ("admin_update", "Admin Update"),
        ("user_update", "User Update"),
        ("payment_initiated", "Payment Initiated"),
        ("payment_success", "Payment Confirmed"),
        ("payment_failed", "Payment Problem"),
        ("lesson_access_granted", "Lesson Access Granted"),
        ("lesson_access_revoked", "Lesson Access Revoked"),
        ("lesson_access_request", "Lesson Access Request"),
        ("trainer_verified", "Trainer Verification"),
        ("bank_verified", "Bank Account"),
        ("in_camp_deactivated", "In-Camp Access Deactivated"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    reason = models.CharField(max_length=40, choices=REASON_CHOICES, default="user_update")
    # In-app route the notification should open (e.g. /app/courses/<uuid>?lesson=12)
    link = models.CharField(max_length=300, blank=True, default="")
    created_by_role = models.CharField(max_length=20, blank=True, default="")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read", "-created_at"])]

    def __str__(self):
        return f"{self.title} -> {self.user.username}"


class Complaint(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints"
    )
    subject = models.CharField(max_length=200)
    message = models.TextField()
    attachment_url = models.URLField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.user.username})"
