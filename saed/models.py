from django.conf import settings
from django.db import models


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

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=24, choices=ROLE_CHOICES, default="corps_member")
    phone = models.CharField(max_length=32, blank=True)
    nysc_state_code = models.CharField(max_length=32, blank=True)
    state_of_deployment = models.CharField(max_length=80, blank=True)
    state_of_origin = models.CharField(max_length=80, blank=True)
    lga_of_deployment = models.CharField(max_length=80, blank=True)
    skill_interest = models.CharField(max_length=80, blank=True)
    skill_interests = models.JSONField(default=list, blank=True)
    is_authorized = models.BooleanField(default=False)
    authorization_status = models.CharField(max_length=16, choices=AUTH_STATUS_CHOICES, default="pending")
    has_paid = models.BooleanField(default=False)
    authorized_at = models.DateTimeField(null=True, blank=True)
    is_email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=64, blank=True)

    specialization = models.CharField(max_length=120, blank=True, choices=SKILL_AREAS)
    partner_lgas = models.JSONField(default=list, blank=True)
    years_experience = models.PositiveSmallIntegerField(default=0)
    bio = models.TextField(blank=True)
    company_name = models.CharField(max_length=120, blank=True)
    number_trained = models.PositiveIntegerField(default=0)
    partnership_letter = models.FileField(upload_to="partnership_letters/", blank=True)
    is_verified = models.BooleanField(default=False)
    has_selected_trainers = models.BooleanField(default=False)
    can_upload_fast_track = models.BooleanField(default=False)
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
    updated_at = models.DateTimeField(auto_now=True)
    profile_picture = models.ImageField(upload_to="profile_pictures/", blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.role})"


class Course(models.Model):
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
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    duration_weeks = models.PositiveSmallIntegerField(default=4)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    max_students = models.PositiveIntegerField(default=40)
    is_active = models.BooleanField(default=True)
    has_fast_track = models.BooleanField(default=False)
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class FastTrackVideo(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    order = models.PositiveSmallIntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_free_preview = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.course.title} - {self.title}"


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
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
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
        ordering = ["-enrolled_at"]

    def __str__(self):
        return f"{self.student.username} -> {self.course.title}"


class Program(models.Model):
    CATEGORY_CHOICES = SKILL_AREAS

    title = models.CharField(max_length=120)
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    description = models.TextField()
    duration_weeks = models.PositiveSmallIntegerField(default=4)
    capacity = models.PositiveIntegerField(default=40)
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_programs",
    )
    trainer_name = models.CharField(max_length=120)
    location = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    is_restricted = models.BooleanField(default=False)
    restricted_at = models.DateTimeField(null=True, blank=True)
    restricted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="restricted_programs",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Application(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("completed", "Completed"),
        ("declined", "Declined"),
    ]

    applicant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    motivation = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["applicant", "program"]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.applicant.username} -> {self.program.title}"


class Notification(models.Model):
    REASON_CHOICES = [
        ("program_restricted", "Program Restricted"),
        ("program_unrestricted", "Program Unrestricted"),
        ("course_restricted", "Course Restricted"),
        ("course_unrestricted", "Course Unrestricted"),
        ("connection_request", "Connection Request"),
        ("connection_approved", "Connection Approved"),
        ("admin_update", "Admin Update"),
        ("user_update", "User Update"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField()
    reason = models.CharField(max_length=32, choices=REASON_CHOICES, default="program_restricted")
    created_by_role = models.CharField(max_length=20, blank=True, default="")
    is_read = models.BooleanField(default=False)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, null=True, blank=True, related_name="notifications")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} -> {self.user.username}"


class Complaint(models.Model):
    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints")
    subject = models.CharField(max_length=200)
    message = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.subject} ({self.user.username})"
