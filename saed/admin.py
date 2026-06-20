from django.contrib import admin

from .models import Application, Connection, Course, FastTrackVideo, Profile, Program


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


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "duration_weeks",
        "capacity",
        "trainer_name",
        "location",
        "is_active",
        "created_at",
    )
    list_filter = ("category", "is_active", "location")
    search_fields = (
        "title",
        "description",
        "trainer_name",
        "location",
    )
    autocomplete_fields = ("trainer",)
    list_select_related = ("trainer",)
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "applicant",
        "applicant_email",
        "program",
        "program_category",
        "status",
        "created_at",
    )
    list_filter = ("status", "program__category", "created_at")
    search_fields = (
        "applicant__first_name",
        "applicant__last_name",
        "applicant__username",
        "applicant__email",
        "program__title",
        "motivation",
    )
    autocomplete_fields = ("applicant", "program")
    list_select_related = ("applicant", "program")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    actions = ("mark_pending", "mark_approved", "mark_completed", "mark_declined")

    @admin.display(ordering="applicant__email")
    def applicant_email(self, application):
        return application.applicant.email

    @admin.display(ordering="program__category")
    def program_category(self, application):
        return application.program.get_category_display()

    @admin.action(description="Mark selected applications as pending")
    def mark_pending(self, request, queryset):
        updated = queryset.exclude(status="completed").update(status="pending")
        skipped = queryset.count() - updated
        if skipped:
            self.message_user(request, f"Skipped {skipped} completed application(s).")

    @admin.action(description="Approve selected applications")
    def mark_approved(self, request, queryset):
        updated = queryset.exclude(status="completed").update(status="approved")
        skipped = queryset.count() - updated
        if skipped:
            self.message_user(request, f"Skipped {skipped} completed application(s).")

    @admin.action(description="Mark selected applications as completed")
    def mark_completed(self, request, queryset):
        # Only update those that are not already completed
        updated = queryset.exclude(status="completed").update(status="completed")
        skipped = queryset.count() - updated
        if skipped:
            self.message_user(request, f"Skipped {skipped} already-completed application(s).")

    @admin.action(description="Decline selected applications")
    def mark_declined(self, request, queryset):
        updated = queryset.exclude(status="completed").update(status="declined")
        skipped = queryset.count() - updated
        if skipped:
            self.message_user(request, f"Skipped {skipped} completed application(s).")

    def get_readonly_fields(self, request, obj=None):
        """Make the `status` field readonly for applications that are completed."""
        readonly = list(self.readonly_fields)
        if obj and getattr(obj, "status", None) == "completed":
            readonly.append("status")
        return readonly
