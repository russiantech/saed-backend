from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from saed.models import Profile, Program


PROGRAMS = [
    {
        "title": "Agro Allied Practices",
        "category": "agro_allied",
        "description": (
            "An introduction to agro-allied trades covering post-harvest handling, basic farm mechanization "
            "and the value chains that link smallholder producers to processors and markets. "
            "Participants learn how to reduce losses after harvest through better drying, sorting, storage "
            "and packaging, and they get hands-on time with simple tools such as threshers, de-stoners and "
            "small-scale dryers. The programme also walks through the economics of running a small agribusiness, "
            "including costing, record keeping, and identifying buyers, processors and cooperatives that can "
            "absorb consistent supply. By the end of the training, every corps member should be able to set up "
            "a basic farm operation, keep simple production records and approach a buyer with a credible plan."
        ),
        "duration_weeks": 6,
        "capacity": 50,
        "trainer_name": "AgriSAED",
        "location": "Farm Training Centre",
    },
    {
        "title": "Automobile Maintenance Essentials",
        "category": "automobile",
        "description": (
            "A practical introduction to vehicle maintenance, diagnostics and light repair for motorcycles and "
            "small cars. Trainees learn the routine checks every owner should know: oil and filter changes, "
            "brake inspection, tyre care, battery testing, cooling system maintenance and basic electrical checks. "
            "Sessions are split between classroom explanations of how each system works and shop-floor practice "
            "with the tools of the trade. There is a strong focus on safety, on recognizing problems that should "
            "be referred to a qualified mechanic, and on building a small income through roadside services, fleet "
            "maintenance contracts or eventually a properly registered workshop."
        ),
        "duration_weeks": 6,
        "capacity": 40,
        "trainer_name": "AutoCraft Institute",
        "location": "Motor Skill Hub",
    },
    {
        "title": "Beautification & Personal Care",
        "category": "beautification",
        "description": (
            "Foundational training in skin care, basic makeup, manicure and pedicure, with strong emphasis on "
            "customer service and salon hygiene. Participants learn how to assess skin types, recommend simple "
            "routines, perform safe treatments, and maintain a clean, professional workspace. The course also "
            "covers retail basics, including how to recommend products honestly, how to package services into "
            "affordable bundles, and how to retain customers through good communication and follow-up. By the "
            "end, every trainee is expected to deliver a full home-service or studio session from start to finish "
            "and to understand the steps required to register a small beauty business."
        ),
        "duration_weeks": 4,
        "capacity": 35,
        "trainer_name": "GlowUp Academy",
        "location": "Yaba Studio",
    },
    {
        "title": "Construction Skills Fundamentals",
        "category": "construction",
        "description": (
            "A hands-on introduction to masonry, carpentry, basic site safety and small-works estimating. "
            "Trainees learn how to mix and lay concrete blocks, render and plaster walls, hang doors and "
            "windows, and carry out simple roofing tasks using timber and modern materials. Each session pairs "
            "a short technical briefing with supervised practice, so participants build muscle memory as well "
            "as theoretical knowledge. The course also covers reading basic drawings, measuring accurately, "
            "estimating materials and labour, and understanding the safety rules that protect a small site. "
            "Graduates leave ready to join a building team or to take on small renovation jobs of their own."
        ),
        "duration_weeks": 8,
        "capacity": 45,
        "trainer_name": "BuildRight Trainers",
        "location": "Construction Yard",
    },
    {
        "title": "Cosmetology & Hairdressing",
        "category": "cosmetology",
        "description": (
            "Comprehensive training in hair styling, cutting, chemical treatments and the business side of "
            "running a salon. Trainees practise on manikins and on willing clients, learning braiding, "
            "weaving, relaxed styles, barbering techniques and modern finishing looks. The course places a "
            "high premium on scalp and hair health, so participants are taught to recognise conditions that "
            "need a referral, to handle chemicals safely, and to communicate clearly with clients about "
            "expectations. Business sessions cover pricing, inventory, customer retention and the basic "
            "registration steps required to operate a salon legally in the state."
        ),
        "duration_weeks": 6,
        "capacity": 30,
        "trainer_name": "StyleWorks",
        "location": "Beauty Centre",
    },
    {
        "title": "Culture & Tourism Entrepreneurship",
        "category": "culture_tourism",
        "description": (
            "A practical look at tourism fundamentals, cultural events planning and the setup of small "
            "tourism businesses rooted in local heritage. Participants explore how to design a tour, how to "
            "engage visitors meaningfully and how to coordinate transport, accommodation and food partners. "
            "The programme also dives into event planning, from community festivals to small conferences, "
            "covering budgeting, promotion, vendor management and post-event evaluation. Graduates come "
            "away with a draft business plan for a tour, a homestay, a cultural event or a related micro "
            "business, plus a clear sense of the licences and partnerships they will need."
        ),
        "duration_weeks": 4,
        "capacity": 40,
        "trainer_name": "Heritage Connect",
        "location": "Hybrid",
    },
    {
        "title": "Teaching & Education Methods",
        "category": "education",
        "description": (
            "Foundations of teaching for corps members who will be running lessons, coaching peers or "
            "supporting community learning. The course covers lesson planning, learning outcomes, classroom "
            "management and the basics of adult learning. Trainees learn how to set clear objectives, "
            "design engaging activities, use simple assessment techniques and adjust their style for "
            "different learners. There is a strong practical component, with each participant delivering "
            "short micro-teaching sessions and receiving structured feedback. By the end of the programme, "
            "graduates are ready to step into a classroom, a study group or a community training session "
            "with confidence and a documented plan."
        ),
        "duration_weeks": 6,
        "capacity": 50,
        "trainer_name": "EduBridge",
        "location": "Orientation Camp Hall",
    },
    {
        "title": "Environmental Management Basics",
        "category": "environment",
        "description": (
            "A practical introduction to waste management, sanitation and small-scale environmental "
            "protection techniques that any corps member can apply in their host community. Trainees learn "
            "how to run a clean-up operation, how to sort waste at the source, and how to set up simple "
            "recycling and composting systems. The course also covers basic environmental advocacy, tree "
            "planting, water-source protection and the local government structures that handle sanitation. "
            "Graduates leave with a tool kit they can use immediately and a project template for organising "
            "a small environmental campaign in their place of primary assignment."
        ),
        "duration_weeks": 4,
        "capacity": 40,
        "trainer_name": "Greenfield Initiative",
        "location": "Camp Environment Unit",
    },
    {
        "title": "Film & Photography Production",
        "category": "film_photography",
        "description": (
            "An entry-level, project-driven course covering camera basics, lighting, composition and the "
            "production workflows used in short-form video and photography. Trainees work through the full "
            "production cycle, from planning a shot list and writing a simple script to shooting, editing "
            "and exporting a final piece. The course also covers storytelling, working with talent, "
            "capturing clean audio and using free or low-cost editing tools effectively. By the end of the "
            "programme, every participant will have produced a short film, a photo essay and a portfolio "
            "page that they can use to pitch services to small businesses, NGOs and content creators."
        ),
        "duration_weeks": 8,
        "capacity": 30,
        "trainer_name": "FrameLab",
        "location": "Media Studio",
    },
    {
        "title": "Food Processing & Preservation",
        "category": "food_processing",
        "description": (
            "Hands-on training in food processing, preservation and small-scale packaging for local food "
            "products. Participants learn how to turn seasonal crops into shelf-stable goods such as dried "
            "fruits, juices, spices, snacks, smoked fish and baked treats. The course covers food safety "
            "basics, hygienic processing environments, simple packaging options and the rules around "
            "labelling in Nigeria. There is also a business component that walks trainees through costing, "
            "pricing, distribution channels and the registrations required to sell packaged food legally. "
            "Graduates leave with a finished product, a recipe sheet and a small starter plan."
        ),
        "duration_weeks": 6,
        "capacity": 40,
        "trainer_name": "SafeFoods Academy",
        "location": "Food Tech Lab",
    },
    {
        "title": "ICT Fundamentals & Web",
        "category": "ict",
        "description": (
            "A beginner-friendly track covering essential ICT skills, common office and collaboration "
            "tools, and a practical introduction to web development and online services. Trainees start "
            "with computer basics, file management, email and internet safety, then progress to documents, "
            "spreadsheets and presentations used in everyday work. The second half introduces how the web "
            "works, building simple pages with HTML and CSS, and using no-code tools to launch a basic site "
            "or portfolio. The course closes with sessions on freelancing, online work platforms, and how "
            "to position digital skills for remote or hybrid income after service."
        ),
        "duration_weeks": 8,
        "capacity": 60,
        "trainer_name": "Dunis Technologies",
        "location": "Computer Lab",
    },
    {
        "title": "Power & Energy Basics",
        "category": "power_energy",
        "description": (
            "An introduction to renewable energy, basic electrical safety and small-scale installations for "
            "homes and small businesses. Participants learn how solar photovoltaic systems, inverters, "
            "batteries and small wind or biomass setups actually work, and how to size a system for a given "
            "load. The course places strong emphasis on safety, including the rules around working near "
            "live wiring, earthing, and choosing the right protective devices. Graduates can carry out a "
            "basic site assessment, recommend a suitable system, and supervise the installation done by a "
            "qualified technician. The business track also covers solar sales, after-sales service and the "
            "regulatory steps needed to operate as a small energy services provider."
        ),
        "duration_weeks": 5,
        "capacity": 30,
        "trainer_name": "PowerSkills Academy",
        "location": "Main Camp Workshop",
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
