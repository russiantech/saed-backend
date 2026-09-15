from django.contrib import admin

from .models import Connection, Course, CourseEnrollment, Complaint, FastTrackVideo, Notification, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "email",
        "role",
        "phone",
        "nysc_state_code",
        "state_of_deployment",
        "skill_interest",
        "is_verified",
        "is_active",
    )
    list_filter = ("role", "skill_interest", "is_verified", "user__is_active")
    search_fields = (
        "user__first_name",
        "user__last_name",
        "user__username",
        "user__email",
        "phone",
        "nysc_state_code",
        "state_of_deployment",
        "skill_interest",
    )
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("authorized_at",)

    def get_fieldsets(self, request, obj=None):
        basic = [
            ("User Information", {"fields": ("user", "role")}),
            ("Contact", {"fields": ("phone",)}),
            ("NYSC Details", {"fields": ("nysc_state_code", "state_of_deployment", "skill_interest")}),
        ]
        if obj:
            if obj.role == "trainer":
                return basic + [
                    ("Trainer Details", {"fields": ("specialization", "partner_lgas", "years_experience", "bio", "company_name", "number_trained", "partnership_letter")}),
                    ("Authorization", {"fields": ("is_authorized", "authorization_status", "has_paid", "payment_verified", "payment_reference", "authorized_at", "payment_verified_at", "is_verified", "can_upload_fast_track")}),
                ]
            elif obj.role == "corps_member":
                return basic + [
                    ("Corps Member Details", {"fields": ("state_of_origin", "lga_of_deployment")}),
                ]
        return basic

    @admin.display(ordering="user__email")
    def email(self, profile):
        return profile.user.email

    @admin.display(boolean=True, ordering="user__is_active")
    def is_active(self, profile):
        return profile.user.is_active


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "trainer", "category", "price", "duration_weeks", "is_active", "created_at")
    list_filter = ("category", "is_active")
    search_fields = ("title", "description")
    autocomplete_fields = ("trainer",)
    list_select_related = ("trainer",)
    readonly_fields = ("created_at",)


@admin.register(FastTrackVideo)
class FastTrackVideoAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "duration_seconds", "price", "is_free_preview", "created_at")
    list_filter = ("is_free_preview",)
    search_fields = ("title", "description")
    autocomplete_fields = ("course",)
    list_select_related = ("course",)
    readonly_fields = ("created_at",)


@admin.register(Connection)
class ConnectionAdmin(admin.ModelAdmin):
    list_display = ("corps_member", "trainer", "status", "connected_at")
    list_filter = ("status",)
    search_fields = ("corps_member__username", "trainer__username")
    autocomplete_fields = ("corps_member", "trainer")
    list_select_related = ("corps_member", "trainer")
    readonly_fields = ("connected_at",)


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "status", "amount_paid", "enrolled_at")
    list_filter = ("status",)
    search_fields = ("student__username", "course__title", "payment_reference")
    autocomplete_fields = ("student", "course", "confirmed_by")
    list_select_related = ("student", "course", "confirmed_by")
    readonly_fields = ("enrolled_at", "confirmed_at", "refund_requested_at", "refund_processed_at")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "reason", "is_read", "created_at")
    list_filter = ("reason", "is_read")
    search_fields = ("title", "message", "user__username")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at",)


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("subject", "user", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("subject", "message", "user__username")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("created_at",)
