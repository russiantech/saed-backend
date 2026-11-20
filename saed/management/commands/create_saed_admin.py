"""Create (or promote) an administrator account. Use it once on a fresh install, e.g. on shared hosting.

    python manage.py create_saed_admin --email admin@example.org --first-name Ada --last-name Obi --phone 08012345678
    (the password is prompted for; or pass --password / set SAED_ADMIN_PASSWORD for non-interactive use)

Roles: saed_admin (default; runs streams, In-Camp trainers, proposals, reports) or dunis_admin (also fees & payments).
Running it again for an existing e-mail updates the role/phone and, if a password is given, resets it.
"""
import getpass
import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saed.models import Profile


class Command(BaseCommand):
    help = "Create or promote a SAED / Dunis administrator account."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", default="")
        parser.add_argument("--last-name", default="")
        parser.add_argument("--phone", default="")
        parser.add_argument("--role", choices=["saed_admin", "dunis_admin"], default="saed_admin")
        parser.add_argument("--password", default=os.environ.get("SAED_ADMIN_PASSWORD", ""))
        parser.add_argument("--staff", action="store_true", help="also allow sign-in to /admin/ (Django admin site)")

    @transaction.atomic
    def handle(self, *args, **o):
        User = get_user_model()
        email = o["email"].strip().lower()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        password = o["password"]
        if created and not password:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Password (again): "):
                raise CommandError("Passwords did not match.")
        if password:
            try:
                validate_password(password)
            except ValidationError as e:
                raise CommandError("; ".join(e.messages))
        if created:
            user = User(username=email, email=email)
        if o["first_name"]:
            user.first_name = o["first_name"]
        if o["last_name"]:
            user.last_name = o["last_name"]
        if o["staff"]:
            user.is_staff = True
        user.is_active = True
        if password:
            user.set_password(password)
        user.save()
        profile, _ = Profile.objects.get_or_create(user=user)
        if o["phone"]:
            clash = Profile.objects.filter(phone=o["phone"]).exclude(pk=profile.pk).exists()
            if clash:
                raise CommandError("That phone number belongs to another account.")
            profile.phone = o["phone"]
        profile.role = o["role"]
        profile.is_authorized = True
        profile.authorization_status = "approved"
        profile.is_email_verified = True
        profile.save()
        self.stdout.write(self.style.SUCCESS(f"{'Created' if created else 'Updated'} {o['role']} {email}"))
