from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from saed.models import Profile, Program


PROGRAMS = [
    {
        "title": "Creative Industry Fundamentals",
        "category": "creative_industry",
        "description": (
            "A practical introduction to the creative economy covering graphic design, branding, "
            "content creation and the basics of running a creative business. Trainees learn how to "
            "develop visual identities, create digital content and market their services to small "
            "businesses. The course covers pricing, client management and the legal steps needed to "
            "register a creative practice."
        ),
        "duration_weeks": 6,
        "capacity": 40,
        "trainer_name": "CreativesSAED",
        "location": "Innovation Hub",
    },
    {
        "title": "Automobile Maintenance Essentials",
        "category": "automobile",
        "description": (
            "A practical introduction to vehicle maintenance, diagnostics and light repair for motorcycles and "
            "small cars. Trainees learn the routine checks every owner should know: oil and filter changes, "
            "brake inspection, tyre care, battery testing, cooling system maintenance and basic electrical checks. "
            "Sessions are split between classroom explanations and shop-floor practice with the tools of the trade."
        ),
        "duration_weeks": 6,
        "capacity": 40,
        "trainer_name": "AutoCraft Institute",
        "location": "Motor Skill Hub",
    },
    {
        "title": "Construction Skills Fundamentals",
        "category": "construction",
        "description": (
            "A hands-on introduction to masonry, carpentry, basic site safety and small-works estimating. "
            "Trainees learn how to mix and lay concrete blocks, render and plaster walls, hang doors and "
            "windows, and carry out simple roofing tasks. The course also covers reading basic drawings, "
            "measuring accurately and estimating materials and labour."
        ),
        "duration_weeks": 8,
        "capacity": 45,
        "trainer_name": "BuildRight Trainers",
        "location": "Construction Yard",
    },
    {
        "title": "Agro Allied Practices",
        "category": "agro_allied",
        "description": (
            "An introduction to agro-allied trades covering post-harvest handling, basic farm mechanization "
            "and the value chains that link smallholder producers to processors and markets. Participants "
            "learn how to reduce losses after harvest through better drying, sorting, storage and packaging."
        ),
        "duration_weeks": 6,
        "capacity": 50,
        "trainer_name": "AgriSAED",
        "location": "Farm Training Centre",
    },
    {
        "title": "Delivery & Logistics Operations",
        "category": "delivery_logistics",
        "description": (
            "A practical course covering last-mile delivery, route planning, fleet management and the "
            "basics of running a logistics business. Trainees learn how to optimize delivery routes, "
            "manage inventory, handle customer service and use digital tools for tracking shipments."
        ),
        "duration_weeks": 4,
        "capacity": 35,
        "trainer_name": "LogiTech Academy",
        "location": "Distribution Centre",
    },
    {
        "title": "Culinary Arts & Catering",
        "category": "culinary_catering",
        "description": (
            "Hands-on training in cooking techniques, food hygiene, menu planning and running a catering "
            "business. Trainees learn to prepare a range of Nigerian and continental dishes, manage a "
            "kitchen, cost meals and handle food safety compliance."
        ),
        "duration_weeks": 6,
        "capacity": 30,
        "trainer_name": "ChefSkills Academy",
        "location": "Culinary Training Centre",
    },
    {
        "title": "Professional Cleaning Services",
        "category": "cleaning_services",
        "description": (
            "Training in professional cleaning techniques, equipment handling, chemical safety and "
            "building a cleaning service business. Trainees learn industrial and residential cleaning "
            "methods, waste management, health and safety standards and client acquisition strategies."
        ),
        "duration_weeks": 4,
        "capacity": 35,
        "trainer_name": "CleanPro Institute",
        "location": "Service Training Centre",
    },
    {
        "title": "Green Energy & Security Technology",
        "category": "green_energy_satellite_security",
        "description": (
            "A combined track covering renewable energy installations and satellite-based security "
            "systems. Trainees learn solar PV sizing, installation and maintenance alongside CCTV, "
            "access control and alarm system setup for homes and small businesses."
        ),
        "duration_weeks": 6,
        "capacity": 30,
        "trainer_name": "GreenSecure Academy",
        "location": "Tech Workshop",
    },
    {
        "title": "ICT Fundamentals & Web",
        "category": "ict",
        "description": (
            "A beginner-friendly track covering essential ICT skills, common office and collaboration "
            "tools, and a practical introduction to web development. Trainees start with computer basics "
            "and progress to building simple websites with HTML and CSS, and using no-code tools to "
            "launch a basic site or portfolio."
        ),
        "duration_weeks": 8,
        "capacity": 60,
        "trainer_name": "Dunis Technologies",
        "location": "Computer Lab",
    },
    {
        "title": "Cosmetology & Hairdressing",
        "category": "cosmetology",
        "description": (
            "Comprehensive training in hair styling, cutting, chemical treatments and the business side "
            "of running a salon. Trainees practise braiding, weaving, barbering techniques and modern "
            "finishing looks. Business sessions cover pricing, inventory and customer retention."
        ),
        "duration_weeks": 6,
        "capacity": 30,
        "trainer_name": "StyleWorks",
        "location": "Beauty Centre",
    },
    {
        "title": "Teaching & Education Methods",
        "category": "education",
        "description": (
            "Foundations of teaching for corps members who will be running lessons, coaching peers or "
            "supporting community learning. The course covers lesson planning, learning outcomes, "
            "classroom management and the basics of adult learning."
        ),
        "duration_weeks": 6,
        "capacity": 50,
        "trainer_name": "EduBridge",
        "location": "Orientation Camp Hall",
    },
]


class Command(BaseCommand):
    help = "Seed the local SAED IMS database with demo users and programs."

    def handle(self, *args, **options):
        admin, _ = User.objects.get_or_create(
            username="admin@saed.test",
            defaults={"email": "admin@saed.test", "is_staff": True, "is_superuser": True},
        )
        admin.set_password("password123")
        admin.email = "admin@saed.test"
        admin.is_active = True
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        admin_profile, _ = Profile.objects.get_or_create(user=admin, defaults={"role": "saed_admin"})
        admin_profile.role = "saed_admin"
        admin_profile.save(update_fields=["role"])

        trainer, _ = User.objects.get_or_create(
            username="trainer@saed.test",
            defaults={"email": "trainer@saed.test", "first_name": "SAED", "last_name": "Trainer"},
        )
        trainer.set_password("password123")
        trainer.email = "trainer@saed.test"
        trainer.is_active = True
        trainer.save()
        trainer_profile, _ = Profile.objects.get_or_create(user=trainer, defaults={"role": "trainer", "phone": "08000000000"})
        trainer_profile.role = "trainer"
        trainer_profile.phone = trainer_profile.phone or "08000000000"
        trainer_profile.is_authorized = True
        trainer_profile.has_paid = True
        trainer_profile.payment_verified = True
        trainer_profile.save(update_fields=["role", "phone", "is_authorized", "has_paid", "payment_verified"])

        member, _ = User.objects.get_or_create(
            username="member@saed.test",
            defaults={"email": "member@saed.test", "first_name": "John", "last_name": "Member"},
        )
        member.set_password("password123")
        member.email = "member@saed.test"
        member.is_active = True
        member.save()
        member_profile, _ = Profile.objects.get_or_create(user=member, defaults={"role": "corps_member", "phone": "07000000000"})
        member_profile.role = "corps_member"
        member_profile.save(update_fields=["role"])

        for item in PROGRAMS:
            Program.objects.update_or_create(title=item["title"], defaults={**item, "trainer": trainer})

        self.stdout.write(self.style.SUCCESS("Seeded SAED IMS demo data."))
