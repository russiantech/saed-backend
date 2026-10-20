from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.conf import settings as django_settings

from saed.models import AdminInvitation
from saed.views.base import generate_admin_secret_key, send_admin_invitation_email, clean_email


class Command(BaseCommand):
    help = "Generate a dynamic 20-character secret key and email an admin invitation (valid for 10 minutes)"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Intended admin email address")
        parser.add_argument(
            "--role",
            type=str,
            default="saed_admin",
            choices=["saed_admin", "dunis_admin"],
            help="Admin role (saed_admin or dunis_admin)",
        )

    def handle(self, *args, **options):
        email = clean_email(options["email"])
        role = options["role"]

        if not email:
            raise CommandError("Please provide a valid email address.")

        if User.objects.filter(email__iexact=email).exists():
            raise CommandError(f"A user with email '{email}' already exists.")

        # Invalidate previous unused invitations for this email
        AdminInvitation.objects.filter(email__iexact=email, is_used=False).delete()

        secret_key = generate_admin_secret_key(20)
        expires_at = now() + timedelta(minutes=10)

        invitation = AdminInvitation.objects.create(
            email=email,
            role=role,
            secret_key=secret_key,
            expires_at=expires_at,
        )

        self.stdout.write(f"Connecting to SMTP server and dispatching invitation to {email}...")
        try:
            send_admin_invitation_email(invitation, sync=True)
            self.stdout.write(self.style.SUCCESS(f"Invitation email successfully delivered to {email}."))
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Could not send email automatically ({exc})."))

        frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3000").rstrip("/")
        signup_url = f"{frontend_url}/admin-signup?email={email}&secret={secret_key}&role={role}"

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("ADMIN INVITATION CREATED SUCCESSFULLY"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"Email:       {email}")
        self.stdout.write(f"Role:        {role}")
        self.stdout.write(f"Secret Key:  {secret_key} (20 characters)")
        self.stdout.write(f"Expires In:  10 minutes ({expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')})")
        self.stdout.write(f"Direct URL:  {signup_url}")
        self.stdout.write(self.style.SUCCESS("=" * 60))
