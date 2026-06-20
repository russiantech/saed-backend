from datetime import timedelta
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from saed.models import Course


COURSES = [
    # Ola Adebayo (ICT)
    {"trainer_email": "ola.adebayo@saed.test", "title": "Web Development Fundamentals", "category": "ict", "description": "Learn HTML, CSS, JavaScript and build responsive websites from scratch.", "price": 25000, "duration_weeks": 8, "max_students": 30},
    {"trainer_email": "ola.adebayo@saed.test", "title": "Mobile App Development with React Native", "category": "ict", "description": "Build cross-platform mobile apps using React Native and JavaScript.", "price": 35000, "duration_weeks": 10, "max_students": 25, "has_fast_track": True},

    # Fatima Hassan (Education)
    {"trainer_email": "fatima.hassan@saed.test", "title": "Effective Teaching Methods", "category": "education", "description": "Master lesson planning, classroom management and student engagement techniques.", "price": 15000, "duration_weeks": 6, "max_students": 40},
    {"trainer_email": "fatima.hassan@saed.test", "title": "Community Education Programs", "category": "education", "description": "Design and run impactful community learning initiatives and workshops.", "price": 20000, "duration_weeks": 4, "max_students": 35},

    # Chukwuma Okafor (Construction)
    {"trainer_email": "chukwuma.okafor@saed.test", "title": "Practical Masonry & Blocklaying", "category": "construction", "description": "Hands-on training in mixing concrete, laying blocks and plastering walls.", "price": 30000, "duration_weeks": 8, "max_students": 20},
    {"trainer_email": "chukwuma.okafor@saed.test", "title": "Carpentry & Woodwork Essentials", "category": "construction", "description": "Learn carpentry fundamentals including joinery, roofing and furniture making.", "price": 28000, "duration_weeks": 6, "max_students": 25},

    # Amara Nwosu (Cosmetology)
    {"trainer_email": "amara.nwosu@saed.test", "title": "Professional Hair Braiding & Styling", "category": "cosmetology", "description": "Master modern braiding techniques, weaving and protective styles.", "price": 20000, "duration_weeks": 6, "max_students": 25},
    {"trainer_email": "amara.nwosu@saed.test", "title": "Skincare & Makeup Artistry", "category": "cosmetology", "description": "Learn skincare routines, facial treatments and professional makeup application.", "price": 25000, "duration_weeks": 4, "max_students": 30, "has_fast_track": True},

    # Ibrahim Mohammed (Agro Allied)
    {"trainer_email": "ibrahim.mohammed@saed.test", "title": "Small-Scale Farming Techniques", "category": "agro_allied", "description": "Practical introduction to crop cultivation, soil management and farm mechanization.", "price": 18000, "duration_weeks": 6, "max_students": 35},
    {"trainer_email": "ibrahim.mohammed@saed.test", "title": "Agribusiness & Market Access", "category": "agro_allied", "description": "Learn how to package, price and distribute agricultural products profitably.", "price": 22000, "duration_weeks": 4, "max_students": 30},

    # Blessing Ogundimu (Film & Photography)
    {"trainer_email": "blessing.ogundimu@saed.test", "title": "Cinematography & Video Production", "category": "film_photography", "description": "Camera operation, lighting, composition and storytelling for short films.", "price": 30000, "duration_weeks": 8, "max_students": 20, "has_fast_track": True},
    {"trainer_email": "blessing.ogundimu@saed.test", "title": "Photography for Business", "category": "film_photography", "description": "Product photography, portrait sessions and editing for commercial clients.", "price": 25000, "duration_weeks": 6, "max_students": 25},

    # Emeka Uzor (Automobile)
    {"trainer_email": "emeka.uzor@saed.test", "title": "Vehicle Diagnostics & Maintenance", "category": "automobile", "description": "Engine diagnostics, brake systems, electrical checks and routine servicing.", "price": 35000, "duration_weeks": 8, "max_students": 20},
    {"trainer_email": "emeka.uzor@saed.test", "title": "Motorcycle Repair & Servicing", "category": "automobile", "description": "Complete motorcycle maintenance from engine tuning to bodywork repair.", "price": 25000, "duration_weeks": 6, "max_students": 25, "has_fast_track": True},

    # Zainab Abdullahi (Food Processing)
    {"trainer_email": "zainab.abdullahi@saed.test", "title": "Food Preservation & Packaging", "category": "food_processing", "description": "Drying, smoking, canning and modern packaging techniques for shelf-stable products.", "price": 20000, "duration_weeks": 6, "max_students": 30},
    {"trainer_email": "zainab.abdullahi@saed.test", "title": "Baking & Confectionery", "category": "food_processing", "description": "Bread, pastries, cakes and snacks production for commercial sale.", "price": 25000, "duration_weeks": 8, "max_students": 25},

    # Tunde Ajayi (Power & Energy)
    {"trainer_email": "tunde.ajayi@saed.test", "title": "Solar PV System Installation", "category": "power_energy", "description": "Site assessment, system sizing, panel mounting and inverter configuration.", "price": 40000, "duration_weeks": 6, "max_students": 20, "has_fast_track": True},
    {"trainer_email": "tunde.ajayi@saed.test", "title": "Basic Electrical Wiring & Safety", "category": "power_energy", "description": "Residential wiring, circuit protection, earthing and electrical safety standards.", "price": 30000, "duration_weeks": 5, "max_students": 25},

    # Ngozi Ekwueme (Culture & Tourism)
    {"trainer_email": "ngozi.ekwueme@saed.test", "title": "Tourism Business Startup", "category": "culture_tourism", "description": "How to plan tours, engage visitors and build a sustainable tourism business.", "price": 22000, "duration_weeks": 4, "max_students": 35},
    {"trainer_email": "ngozi.ekwueme@saed.test", "title": "Event Planning & Management", "category": "culture_tourism", "description": "Budgeting, vendor coordination, promotion and execution for events of all sizes.", "price": 28000, "duration_weeks": 6, "max_students": 30},
]


class Command(BaseCommand):
    help = "Seed demo courses for all trainers."

    def handle(self, *args, **options):
        created = 0
        for c in COURSES:
            try:
                trainer = User.objects.get(username=c["trainer_email"])
            except User.DoesNotExist:
                self.stdout.write(self.style.WARNING(f"Trainer {c['trainer_email']} not found, skipping."))
                continue

            if Course.objects.filter(trainer=trainer, title=c["title"]).exists():
                continue

            start = timezone.now().date() + timedelta(weeks=1)
            end = start + timedelta(weeks=c["duration_weeks"])

            Course.objects.create(
                trainer=trainer,
                title=c["title"],
                description=c["description"],
                category=c["category"],
                price=c["price"],
                duration_weeks=c["duration_weeks"],
                start_date=start,
                end_date=end,
                max_students=c["max_students"],
                is_active=True,
                has_fast_track=c.get("has_fast_track", False),
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} courses."))
