# """
# Django Data Seeder for NYSC SAED IMS
# ====================================
# Run with:  python manage.py shell < seed_data.py
# Or place in:  <app>/management/commands/seed.py  and run  python manage.py seed

# This script is idempotent — running it multiple times will not create duplicates.
# """

# import os
# import sys
# import django

# # ── Bootstrap Django ─────────────────────────────────────────────────────────
# # If running as a standalone script, point this to your manage.py directory.
# BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
# sys.path.insert(0, BASE_DIR)
# django.setup()

# from django.db import transaction
# from django.contrib.auth import get_user_model
# from django.contrib.auth.hashers import make_password

# from saed.models import (  # <-- replace "your_app" with your actual app name
#     Profile,
#     Course,
#     Program,
#     Notification,
#     Connection,
#     CourseEnrollment,
#     Application,
#     Complaint,
#     SKILL_AREAS,
# )

# User = get_user_model()

# # ── Configuration ────────────────────────────────────────────────────────────
# DEFAULT_PASSWORD = "Admin@1234"  # Change this after first login!

# SEED_ADMINS = [
#     {
#         "username": "saed_admin",
#         "email": "saed.admin@dunistech.ng",
#         "first_name": "SAED",
#         "last_name": "Administrator",
#         "role": "saed_admin",
#         "phone": "08010000001",
#         "is_authorized": True,
#         "authorization_status": "approved",
#         "is_email_verified": True,
#     },
#     {
#         "username": "dunis_admin",
#         "email": "dunis.admin@dunistech.ng",
#         "first_name": "DUNIS",
#         "last_name": "Administrator",
#         "role": "dunis_admin",
#         "phone": "08010000002",
#         "is_authorized": True,
#         "authorization_status": "approved",
#         "is_email_verified": True,
#     },
#     {
#         "username": "superadmin",
#         "email": "super.admin@dunistech.ng",
#         "first_name": "Super",
#         "last_name": "Admin",
#         "role": "dunis_admin",  # or create a separate superuser role
#         "phone": "08010000003",
#         "is_authorized": True,
#         "authorization_status": "approved",
#         "is_email_verified": True,
#         "is_superuser": True,
#         "is_staff": True,
#     },
# ]

# SEED_TRAINERS = [
#     {
#         "username": "trainer_ict",
#         "email": "trainer.ict@dunistech.ng",
#         "first_name": "Ade",
#         "last_name": "Ogunlesi",
#         "role": "trainer",
#         "phone": "08020000001",
#         "specialization": "ict",
#         "partner_lgas": ["Ikeja", "Eti-Osa"],
#         "years_experience": 5,
#         "bio": "Experienced ICT instructor with a passion for youth empowerment.",
#         "company_name": "TechBridge NG",
#         "number_trained": 120,
#         "is_authorized": True,
#         "authorization_status": "approved",
#         "is_email_verified": True,
#         "has_paid": True,
#     },
#     {
#         "username": "trainer_creative",
#         "email": "trainer.creative@dunistech.ng",
#         "first_name": "Chioma",
#         "last_name": "Eze",
#         "role": "trainer",
#         "phone": "08020000002",
#         "specialization": "creative_industry",
#         "partner_lgas": ["Lagos Island", "Surulere"],
#         "years_experience": 3,
#         "bio": "Graphic designer and creative entrepreneur.",
#         "company_name": "Creative Hub Lagos",
#         "number_trained": 85,
#         "is_authorized": True,
#         "authorization_status": "approved",
#         "is_email_verified": True,
#         "has_paid": True,
#     },
# ]

# SEED_CORPERS = [
#     {
#         "username": "corper_001",
#         "email": "corper.001@dunistech.ng",
#         "first_name": "John",
#         "last_name": "Doe",
#         "role": "corps_member",
#         "phone": "08030000001",
#         "nysc_state_code": "LA/26B/0001",
#         "state_of_deployment": "Lagos",
#         "lga_of_deployment": "Ikeja",
#         "skill_interest": "ict",
#         "skill_interests": ["ict", "delivery_logistics"],
#         "is_email_verified": True,
#     },
#     {
#         "username": "corper_002",
#         "email": "corper.002@dunistech.ng",
#         "first_name": "Jane",
#         "last_name": "Smith",
#         "role": "corps_member",
#         "phone": "08030000002",
#         "nysc_state_code": "LA/26B/0002",
#         "state_of_deployment": "Lagos",
#         "lga_of_deployment": "Eti-Osa",
#         "skill_interest": "creative_industry",
#         "skill_interests": ["creative_industry", "cosmetology"],
#         "is_email_verified": True,
#     },
# ]

# SEED_COURSES = [
#     {
#         "title": "Introduction to Web Development",
#         "description": "Learn HTML, CSS, and JavaScript from scratch.",
#         "category": "ict",
#         "price": 15000.00,
#         "duration_weeks": 6,
#         "max_students": 30,
#         "has_fast_track": True,
#     },
#     {
#         "title": "Graphic Design Fundamentals",
#         "description": "Master Photoshop, Illustrator, and design principles.",
#         "category": "creative_industry",
#         "price": 12000.00,
#         "duration_weeks": 4,
#         "max_students": 25,
#         "has_fast_track": False,
#     },
#     {
#         "title": "Agro-Processing Basics",
#         "description": "Learn modern techniques in agricultural processing.",
#         "category": "agro_allied",
#         "price": 10000.00,
#         "duration_weeks": 8,
#         "max_students": 40,
#         "has_fast_track": False,
#     },
# ]

# SEED_PROGRAMS = [
#     {
#         "title": "SAED ICT Bootcamp 2026",
#         "category": "ict",
#         "description": "Intensive 4-week ICT training for corps members.",
#         "duration_weeks": 4,
#         "capacity": 50,
#         "trainer_name": "Ade Ogunlesi",
#         "location": "Ikeja Community Center",
#     },
#     {
#         "title": "Creative Industry Workshop",
#         "category": "creative_industry",
#         "description": "Hands-on training in graphic design and content creation.",
#         "duration_weeks": 3,
#         "capacity": 30,
#         "trainer_name": "Chioma Eze",
#         "location": "Lagos Island Arts Pavilion",
#     },
# ]


# # ── Helpers ──────────────────────────────────────────────────────────────────

# def create_user(data, password=DEFAULT_PASSWORD):
#     """
#     Create or update a User and their Profile.
#     Returns (user, created_bool).
#     """
#     username = data["username"]
#     email = data["email"]

#     user, created = User.objects.get_or_create(
#         username=username,
#         defaults={
#             "email": email,
#             "first_name": data.get("first_name", ""),
#             "last_name": data.get("last_name", ""),
#             "password": make_password(password),
#             "is_active": True,
#             "is_staff": data.get("is_staff", False),
#             "is_superuser": data.get("is_superuser", False),
#         },
#     )

#     if not created:
#         # Ensure existing user has correct password and active status
#         user.set_password(password)
#         user.email = email
#         user.first_name = data.get("first_name", user.first_name)
#         user.last_name = data.get("last_name", user.last_name)
#         user.is_active = True
#         user.is_staff = data.get("is_staff", user.is_staff)
#         user.is_superuser = data.get("is_superuser", user.is_superuser)
#         user.save()

#     # Create or update Profile
#     profile_defaults = {
#         "role": data.get("role", "corps_member"),
#         "phone": data.get("phone", ""),
#         "is_authorized": data.get("is_authorized", False),
#         "authorization_status": data.get("authorization_status", "pending"),
#         "is_email_verified": data.get("is_email_verified", False),
#         "has_paid": data.get("has_paid", False),
#     }

#     # Trainer-specific fields
#     if data.get("role") == "trainer":
#         profile_defaults.update({
#             "specialization": data.get("specialization", ""),
#             "partner_lgas": data.get("partner_lgas", []),
#             "years_experience": data.get("years_experience", 0),
#             "bio": data.get("bio", ""),
#             "company_name": data.get("company_name", ""),
#             "number_trained": data.get("number_trained", 0),
#         })

#     # Corps member-specific fields
#     if data.get("role") == "corps_member":
#         profile_defaults.update({
#             "nysc_state_code": data.get("nysc_state_code", ""),
#             "state_of_deployment": data.get("state_of_deployment", ""),
#             "lga_of_deployment": data.get("lga_of_deployment", ""),
#             "skill_interest": data.get("skill_interest", ""),
#             "skill_interests": data.get("skill_interests", []),
#         })

#     Profile.objects.update_or_create(
#         user=user,
#         defaults=profile_defaults,
#     )

#     return user, created


# def seed_admins():
#     print("\n Seeding Admins...")
#     for data in SEED_ADMINS:
#         user, created = create_user(data)
#         action = "Created" if created else "Updated"
#         print(f"   {action}: {user.username} ({data['role']}) — {user.email}")


# def seed_trainers():
#     print("\n Seeding Trainers...")
#     for data in SEED_TRAINERS:
#         user, created = create_user(data)
#         action = "Created" if created else "Updated"
#         print(f"   {action}: {user.username} ({data['specialization']})")


# def seed_corpers():
#     print("\n Seeding Corps Members...")
#     for data in SEED_CORPERS:
#         user, created = create_user(data)
#         action = "Created" if created else "Updated"
#         print(f"   {action}: {user.username} ({data['nysc_state_code']})")


# def seed_courses():
#     print("\n Seeding Courses...")
#     # Get trainers to assign courses to
#     trainer_ict = User.objects.filter(
#         profile__role="trainer",
#         profile__specialization="ict",
#     ).first()
#     trainer_creative = User.objects.filter(
#         profile__role="trainer",
#         profile__specialization="creative_industry",
#     ).first()

#     course_map = [
#         (SEED_COURSES[0], trainer_ict),
#         (SEED_COURSES[1], trainer_creative),
#         (SEED_COURSES[2], None),  # unassigned
#     ]

#     for data, trainer in course_map:
#         course, created = Course.objects.get_or_create(
#             title=data["title"],
#             defaults={
#                 "description": data["description"],
#                 "category": data["category"],
#                 "price": data["price"],
#                 "duration_weeks": data["duration_weeks"],
#                 "max_students": data["max_students"],
#                 "has_fast_track": data["has_fast_track"],
#                 "trainer": trainer,
#                 "is_active": True,
#             },
#         )
#         action = "Created" if created else "Updated"
#         trainer_label = f" (trainer: {trainer.username})" if trainer else " (no trainer)"
#         print(f"   {action}: {course.title}{trainer_label}")


# def seed_programs():
#     print("\n Seeding Programs...")
#     for data in SEED_PROGRAMS:
#         # Find a trainer matching the category
#         trainer = User.objects.filter(
#             profile__role="trainer",
#             profile__specialization=data["category"],
#         ).first()

#         program, created = Program.objects.get_or_create(
#             title=data["title"],
#             defaults={
#                 "category": data["category"],
#                 "description": data["description"],
#                 "duration_weeks": data["duration_weeks"],
#                 "capacity": data["capacity"],
#                 "trainer": trainer,
#                 "trainer_name": data["trainer_name"],
#                 "location": data["location"],
#                 "is_active": True,
#             },
#         )
#         action = "Created" if created else "Updated"
#         print(f"   {action}: {program.title}")


# def print_summary():
#     print("\n" + "=" * 60)
#     print("SEED SUMMARY")
#     print("=" * 60)
#     print(f"   Users:        {User.objects.count()}")
#     print(f"   Profiles:     {Profile.objects.count()}")
#     print(f"   Courses:      {Course.objects.count()}")
#     print(f"   Programs:     {Program.objects.count()}")
#     print(f"   Connections:  {Connection.objects.count()}")
#     print(f"   Enrollments:  {CourseEnrollment.objects.count()}")
#     print(f"   Applications: {Application.objects.count()}")
#     print(f"   Complaints:   {Complaint.objects.count()}")
#     print("=" * 60)
#     print(f"\n Default password for all seeded users: {DEFAULT_PASSWORD}")
#     print(" Change these passwords immediately after first login!\n")


# # ── Main ─────────────────────────────────────────────────────────────────────

# def run(seed_all=False):
#     """
#     seed_all=False  → only seed admins (safer for production)
#     seed_all=True   → seed admins + trainers + corpers + courses + programs
#     """
#     with transaction.atomic():
#         seed_admins()

#         if seed_all:
#             seed_trainers()
#             seed_corpers()
#             seed_courses()
#             seed_programs()

#     print_summary()


# if __name__ == "__main__":
#     # Default: seed only admins. Pass --all to seed everything.
#     seed_everything = "--all" in sys.argv
#     run(seed_all=seed_everything)





# v2
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from saed.models import (
    Profile,
    Course,
    Program,
    Connection,
    CourseEnrollment,
    Application,
    Complaint,
)

User = get_user_model()

DEFAULT_PASSWORD = "edidem-X-edet-900"

SEED_ADMINS = [
    {
        "username": "saed_admin",
        "email": "saed.admin@example.com",
        "first_name": "SAED",
        "last_name": "Administrator",
        "role": "saed_admin",
        "phone": "08010000001",
        "is_authorized": True,
        "authorization_status": "approved",
        "is_email_verified": True,
    },
    {
        "username": "dunis_admin",
        "email": "dunis.admin@example.com",
        "first_name": "DUNIS",
        "last_name": "Administrator",
        "role": "dunis_admin",
        "phone": "08010000002",
        "is_authorized": True,
        "authorization_status": "approved",
        "is_email_verified": True,
    },
    {
        "username": "superadmin",
        "email": "super.admin@example.com",
        "first_name": "Super",
        "last_name": "Admin",
        "role": "dunis_admin",
        "phone": "08010000003",
        "is_authorized": True,
        "authorization_status": "approved",
        "is_email_verified": True,
        "is_superuser": True,
        "is_staff": True,
    },
]

SEED_TRAINERS = [
    {
        "username": "trainer_ict",
        "email": "trainer.ict@example.com",
        "first_name": "Ade",
        "last_name": "Ogunlesi",
        "role": "trainer",
        "phone": "08020000001",
        "specialization": "ict",
        "partner_lgas": ["Ikeja", "Eti-Osa"],
        "years_experience": 5,
        "bio": "Experienced ICT instructor with a passion for youth empowerment.",
        "company_name": "TechBridge NG",
        "number_trained": 120,
        "is_authorized": True,
        "authorization_status": "approved",
        "is_email_verified": True,
        "has_paid": True,
    },
    {
        "username": "trainer_creative",
        "email": "trainer.creative@example.com",
        "first_name": "Chioma",
        "last_name": "Eze",
        "role": "trainer",
        "phone": "08020000002",
        "specialization": "creative_industry",
        "partner_lgas": ["Lagos Island", "Surulere"],
        "years_experience": 3,
        "bio": "Graphic designer and creative entrepreneur.",
        "company_name": "Creative Hub Lagos",
        "number_trained": 85,
        "is_authorized": True,
        "authorization_status": "approved",
        "is_email_verified": True,
        "has_paid": True,
    },
]

SEED_CORPERS = [
    {
        "username": "corper_001",
        "email": "corper.001@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "role": "corps_member",
        "phone": "08030000001",
        "nysc_state_code": "LA/26B/0001",
        "state_of_deployment": "Lagos",
        "lga_of_deployment": "Ikeja",
        "skill_interest": "ict",
        "skill_interests": ["ict", "delivery_logistics"],
        "is_email_verified": True,
    },
    {
        "username": "corper_002",
        "email": "corper.002@example.com",
        "first_name": "Jane",
        "last_name": "Smith",
        "role": "corps_member",
        "phone": "08030000002",
        "nysc_state_code": "LA/26B/0002",
        "state_of_deployment": "Lagos",
        "lga_of_deployment": "Eti-Osa",
        "skill_interest": "creative_industry",
        "skill_interests": ["creative_industry", "cosmetology"],
        "is_email_verified": True,
    },
]

SEED_COURSES = [
    {
        "title": "Introduction to Web Development",
        "description": "Learn HTML, CSS, and JavaScript from scratch.",
        "category": "ict",
        "price": 15000.00,
        "duration_weeks": 6,
        "max_students": 30,
        "has_fast_track": True,
    },
    {
        "title": "Graphic Design Fundamentals",
        "description": "Master Photoshop, Illustrator, and design principles.",
        "category": "creative_industry",
        "price": 12000.00,
        "duration_weeks": 4,
        "max_students": 25,
        "has_fast_track": False,
    },
    {
        "title": "Agro-Processing Basics",
        "description": "Learn modern techniques in agricultural processing.",
        "category": "agro_allied",
        "price": 10000.00,
        "duration_weeks": 8,
        "max_students": 40,
        "has_fast_track": False,
    },
]

SEED_PROGRAMS = [
    {
        "title": "SAED ICT Bootcamp 2026",
        "category": "ict",
        "description": "Intensive 4-week ICT training for corps members.",
        "duration_weeks": 4,
        "capacity": 50,
        "trainer_name": "Ade Ogunlesi",
        "location": "Ikeja Community Center",
    },
    {
        "title": "Creative Industry Workshop",
        "category": "creative_industry",
        "description": "Hands-on training in graphic design and content creation.",
        "duration_weeks": 3,
        "capacity": 30,
        "trainer_name": "Chioma Eze",
        "location": "Lagos Island Arts Pavilion",
    },
]


def create_user(data, password=DEFAULT_PASSWORD):
    username = data["username"]
    email = data["email"]

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": data.get("first_name", ""),
            "last_name": data.get("last_name", ""),
            "password": make_password(password),
            "is_active": True,
            "is_staff": data.get("is_staff", False),
            "is_superuser": data.get("is_superuser", False),
        },
    )

    if not created:
        user.set_password(password)
        user.email = email
        user.first_name = data.get("first_name", user.first_name)
        user.last_name = data.get("last_name", user.last_name)
        user.is_active = True
        user.is_staff = data.get("is_staff", user.is_staff)
        user.is_superuser = data.get("is_superuser", user.is_superuser)
        user.save()

    profile_defaults = {
        "role": data.get("role", "corps_member"),
        "phone": data.get("phone", ""),
        "is_authorized": data.get("is_authorized", False),
        "authorization_status": data.get("authorization_status", "pending"),
        "is_email_verified": data.get("is_email_verified", False),
        "has_paid": data.get("has_paid", False),
    }

    if data.get("role") == "trainer":
        profile_defaults.update({
            "specialization": data.get("specialization", ""),
            "partner_lgas": data.get("partner_lgas", []),
            "years_experience": data.get("years_experience", 0),
            "bio": data.get("bio", ""),
            "company_name": data.get("company_name", ""),
            "number_trained": data.get("number_trained", 0),
        })

    if data.get("role") == "corps_member":
        profile_defaults.update({
            "nysc_state_code": data.get("nysc_state_code", ""),
            "state_of_deployment": data.get("state_of_deployment", ""),
            "lga_of_deployment": data.get("lga_of_deployment", ""),
            "skill_interest": data.get("skill_interest", ""),
            "skill_interests": data.get("skill_interests", []),
        })

    Profile.objects.update_or_create(
        user=user,
        defaults=profile_defaults,
    )

    return user, created


class Command(BaseCommand):
    help = "Seed the database with initial data (admins, trainers, corpers, courses, programs)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Seed everything (admins + trainers + corpers + courses + programs)",
        )

    def handle(self, *args, **options):
        seed_all = options["all"]

        with transaction.atomic():
            self.stdout.write(self.style.HTTP_INFO("\n Seeding Admins..."))
            for data in SEED_ADMINS:
                user, created = create_user(data)
                action = "Created" if created else "Updated"
                self.stdout.write(f"   {action}: {user.username} ({data['role']})")

            if seed_all:
                self.stdout.write(self.style.HTTP_INFO("\n Seeding Trainers..."))
                for data in SEED_TRAINERS:
                    user, created = create_user(data)
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"   {action}: {user.username}")

                self.stdout.write(self.style.HTTP_INFO("\n Seeding Corps Members..."))
                for data in SEED_CORPERS:
                    user, created = create_user(data)
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"   {action}: {user.username}")

                self.stdout.write(self.style.HTTP_INFO("\n Seeding Courses..."))
                trainer_ict = User.objects.filter(
                    profile__role="trainer", profile__specialization="ict"
                ).first()
                trainer_creative = User.objects.filter(
                    profile__role="trainer", profile__specialization="creative_industry"
                ).first()

                course_map = [
                    (SEED_COURSES[0], trainer_ict),
                    (SEED_COURSES[1], trainer_creative),
                    (SEED_COURSES[2], None),
                ]

                for data, trainer in course_map:
                    course, created = Course.objects.get_or_create(
                        title=data["title"],
                        defaults={
                            "description": data["description"],
                            "category": data["category"],
                            "price": data["price"],
                            "duration_weeks": data["duration_weeks"],
                            "max_students": data["max_students"],
                            "has_fast_track": data["has_fast_track"],
                            "trainer": trainer,
                            "is_active": True,
                        },
                    )
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"   {action}: {course.title}")

                self.stdout.write(self.style.HTTP_INFO("\n Seeding Programs..."))
                for data in SEED_PROGRAMS:
                    trainer = User.objects.filter(
                        profile__role="trainer",
                        profile__specialization=data["category"],
                    ).first()

                    program, created = Program.objects.get_or_create(
                        title=data["title"],
                        defaults={
                            "category": data["category"],
                            "description": data["description"],
                            "duration_weeks": data["duration_weeks"],
                            "capacity": data["capacity"],
                            "trainer": trainer,
                            "trainer_name": data["trainer_name"],
                            "location": data["location"],
                            "is_active": True,
                        },
                    )
                    action = "Created" if created else "Updated"
                    self.stdout.write(f"   {action}: {program.title}")

        # Summary
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 50))
        self.stdout.write(self.style.SUCCESS("SEED SUMMARY"))
        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(f"   Users:        {User.objects.count()}")
        self.stdout.write(f"   Profiles:     {Profile.objects.count()}")
        self.stdout.write(f"   Courses:      {Course.objects.count()}")
        self.stdout.write(f"   Programs:     {Program.objects.count()}")
        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(self.style.WARNING(f"\n Default password: {DEFAULT_PASSWORD}"))
        self.stdout.write(self.style.WARNING(" Change these passwords immediately!\n"))

