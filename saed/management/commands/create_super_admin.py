import getpass

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from saed.models import Profile


class Command(BaseCommand):
    help = "Create a hidden super admin account (invisible in user listings)"

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, help="Email for the super admin")
        parser.add_argument("--username", type=str, help="Username for the super admin")
        parser.add_argument("--phone", type=str, default="", help="Phone number (10 digits)")

    def handle(self, *args, **options):
        email = options["email"] or input("Email: ").strip()
        username = options["username"] or input("Username: ").strip()
        phone = options["phone"] or input("Phone (10 digits, optional): ").strip()

        if User.objects.filter(email=email).exists():
            self.stderr.write(self.style.ERROR(f"Email '{email}' already exists."))
            return
        if User.objects.filter(username=username).exists():
            self.stderr.write(self.style.ERROR(f"Username '{username}' already exists."))
            return

        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            self.stderr.write(self.style.ERROR("Passwords do not match."))
            return
        if len(password) < 8:
            self.stderr.write(self.style.ERROR("Password must be at least 8 characters."))
            return

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name="Super",
            last_name="Admin",
        )
        Profile.objects.create(
            user=user,
            role="dunis_admin",
            phone=phone,
            is_email_verified=True,
            is_hidden=True,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Hidden super admin '{email}' created. "
            f"This account will not appear in user listings."
        ))
