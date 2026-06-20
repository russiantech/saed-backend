import json
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from saed.models import Profile


TRAINERS = [
    {
        "email": "ola.adebayo@saed.test",
        "full_name": "Ola Adebayo",
        "specialization": "ICT",
        "partner_lgas": ["Lagos Island", "Eti-Osa", "Ikeja"],
        "years_experience": 8,
        "bio": "Full-stack developer and tech educator with 8 years of experience training youth in web development, mobile apps, and digital literacy.",
        "company_name": "CodeCraft Academy",
        "number_trained": 250,
        "phone": "08012345001",
        "nysc_state_code": "LA/20/001",
        "lga_of_deployment": "Lagos Island",
        "skill_interest": "ICT",
    },
    {
        "email": "fatima.hassan@saed.test",
        "full_name": "Fatima Hassan",
        "specialization": "Education",
        "partner_lgas": ["Surulere", "Yaba", "Shomolu"],
        "years_experience": 6,
        "bio": "Experienced educator specializing in adult learning, curriculum development, and community education programs.",
        "company_name": "EduBridge Lagos",
        "number_trained": 180,
        "phone": "08012345002",
        "nysc_state_code": "LA/20/002",
        "lga_of_deployment": "Surulere",
        "skill_interest": "Education",
    },
    {
        "email": "chukwuma.okafor@saed.test",
        "full_name": "Chukwuma Okafor",
        "specialization": "Construction",
        "partner_lgas": ["Ikorodu", "Mushin", "Oshodi-Isolo"],
        "years_experience": 10,
        "bio": "Certified building technologist with a decade of hands-on experience in residential and commercial construction projects.",
        "company_name": "BuildRight Trainers",
        "number_trained": 320,
        "phone": "08012345003",
        "nysc_state_code": "LA/20/003",
        "lga_of_deployment": "Ikorodu",
        "skill_interest": "Construction",
    },
    {
        "email": "amara.nwosu@saed.test",
        "full_name": "Amara Nwosu",
        "specialization": "Cosmetology",
        "partner_lgas": ["Lagos Island", "Victoria Island", "Lekki"],
        "years_experience": 5,
        "bio": "Professional hair stylist and beauty educator passionate about empowering youth through cosmetology skills.",
        "company_name": "GlowUp Academy",
        "number_trained": 150,
        "phone": "08012345004",
        "nysc_state_code": "LA/20/004",
        "lga_of_deployment": "Lagos Island",
        "skill_interest": "Cosmetology",
    },
    {
        "email": "ibrahim.mohammed@saed.test",
        "full_name": "Ibrahim Mohammed",
        "specialization": "Agro Allied",
        "partner_lgas": ["Badagry", "Ojo", "Amuwo-Odofin"],
        "years_experience": 7,
        "bio": "Agricultural extension officer and agribusiness consultant helping smallholder farmers improve productivity and market access.",
        "company_name": "Greenfield Agro",
        "number_trained": 200,
        "phone": "08012345005",
        "nysc_state_code": "LA/20/005",
        "lga_of_deployment": "Badagry",
        "skill_interest": "Agro Allied",
    },
    {
        "email": "blessing.ogundimu@saed.test",
        "full_name": "Blessing Ogundimu",
        "specialization": "Film & Photography",
        "partner_lgas": ["Ikeja", "Ojodu", "Ifako-Ijaiye"],
        "years_experience": 4,
        "bio": "Filmmaker and visual storyteller with expertise in short-form video production, photography, and content creation.",
        "company_name": "FrameLab Studios",
        "number_trained": 95,
        "phone": "08012345006",
        "nysc_state_code": "LA/20/006",
        "lga_of_deployment": "Ikeja",
        "skill_interest": "Film & Photography",
    },
    {
        "email": "emeka.uzor@saed.test",
        "full_name": "Emeka Uzor",
        "specialization": "Automobile",
        "partner_lgas": ["Mushin", "Surulere", "Ajeromi-Ifelodun"],
        "years_experience": 9,
        "bio": "Automotive technician and trainer specializing in vehicle diagnostics, maintenance, and small engine repair.",
        "company_name": "AutoCraft Institute",
        "number_trained": 280,
        "phone": "08012345007",
        "nysc_state_code": "LA/20/007",
        "lga_of_deployment": "Mushin",
        "skill_interest": "Automobile",
    },
    {
        "email": "zainab.abdullahi@saed.test",
        "full_name": "Zainab Abdullahi",
        "specialization": "Food Processing",
        "partner_lgas": ["Shomolu", "Kosofe", "Ikorodu"],
        "years_experience": 6,
        "bio": "Food scientist and processing consultant helping entrepreneurs turn raw agricultural products into market-ready goods.",
        "company_name": "SafeFoods Academy",
        "number_trained": 160,
        "phone": "08012345008",
        "nysc_state_code": "LA/20/008",
        "lga_of_deployment": "Shomolu",
        "skill_interest": "Food Processing",
    },
    {
        "email": "tunde.ajayi@saed.test",
        "full_name": "Tunde Ajayi",
        "specialization": "Power & Energy",
        "partner_lgas": ["Eti-Osa", "Lagos Island", "Victoria Island"],
        "years_experience": 5,
        "bio": "Renewable energy engineer with expertise in solar PV systems, energy audits, and clean energy solutions for homes and businesses.",
        "company_name": "PowerSkills Academy",
        "number_trained": 120,
        "phone": "08012345009",
        "nysc_state_code": "LA/20/009",
        "lga_of_deployment": "Eti-Osa",
        "skill_interest": "Power & Energy",
    },
    {
        "email": "ngozi.ekwueme@saed.test",
        "full_name": "Ngozi Ekwueme",
        "specialization": "Culture & Tourism",
        "partner_lgas": ["Lagos Island", "Eti-Osa", "Badagry"],
        "years_experience": 7,
        "bio": "Cultural tourism specialist and event planner with deep knowledge of Lagos heritage sites and community-based tourism.",
        "company_name": "Heritage Connect",
        "number_trained": 140,
        "phone": "08012345010",
        "nysc_state_code": "LA/20/010",
        "lga_of_deployment": "Lagos Island",
        "skill_interest": "Culture & Tourism",
    },
]


class Command(BaseCommand):
    help = "Seed the database with demo trainer accounts for testing."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for t in TRAINERS:
            user, created = User.objects.get_or_create(
                username=t["email"],
                defaults={
                    "email": t["email"],
                    "first_name": t["full_name"].split(" ", 1)[0],
                    "last_name": t["full_name"].split(" ", 1)[1] if " " in t["full_name"] else "",
                    "is_active": True,
                },
            )
            user.set_password("password123")
            user.email = t["email"]
            user.save()

            profile, profile_created = Profile.objects.get_or_create(
                user=user,
                defaults={
                    "role": "trainer",
                    "phone": t["phone"],
                    "nysc_state_code": t["nysc_state_code"],
                    "state_of_deployment": "Lagos",
                    "lga_of_deployment": t["lga_of_deployment"],
                    "skill_interest": t["skill_interest"],
                    "specialization": t["specialization"],
                    "partner_lgas": t["partner_lgas"],
                    "years_experience": t["years_experience"],
                    "bio": t["bio"],
                    "company_name": t["company_name"],
                    "number_trained": t["number_trained"],
                    "is_authorized": True,
                    "authorization_status": "approved",
                },
            )

            if not profile_created:
                profile.specialization = t["specialization"]
                profile.partner_lgas = t["partner_lgas"]
                profile.years_experience = t["years_experience"]
                profile.bio = t["bio"]
                profile.company_name = t["company_name"]
                profile.number_trained = t["number_trained"]
                profile.is_authorized = True
                profile.authorization_status = "approved"
                profile.save()
                updated_count += 1
            else:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_count} new trainers, updated {updated_count} existing trainers."
            )
        )
