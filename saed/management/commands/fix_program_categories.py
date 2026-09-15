from django.core.management.base import BaseCommand

from saed.models import Course, SKILL_AREAS


MAPPING = [
    (['agri', 'agriculture', 'farm', 'crop', 'poultry', 'agro'], 'agro_allied'),
    (['auto', 'automobile', 'vehicle', 'motor'], 'automobile'),
    (['beauty', 'beautification', 'makeup', 'manicure', 'pedicure', 'fashion', 'branding'], 'beautification'),
    (['construction', 'masonry', 'carpentry'], 'construction'),
    (['cosmetology', 'hairdressing', 'hair', 'salon', 'barber'], 'cosmetology'),
    (['culture', 'tourism', 'heritage', 'travel', 'tour'], 'culture_tourism'),
    (['teach', 'education', 'lesson', 'class', 'teacher', 'training'], 'education'),
    (['environment', 'waste', 'sanitation', 'recycle', 'green'], 'environment'),
    (['film', 'photo', 'photography', 'camera', 'video'], 'film_photography'),
    (['food', 'processing', 'preservation', 'packaging'], 'food_processing'),
    (['ict', 'web', 'react', 'javascript', 'computer', 'digital', 'software'], 'ict'),
    (['power', 'energy', 'solar', 'electrical', 'renewable'], 'power_energy'),
]

# Prefer direct mapping from legacy category names to new slugs when possible
OLD_MAP = {
    'technology': 'ict',
    'agriculture': 'agro_allied',
    'business': 'education',
    'creative': 'beautification',
    'vocational': 'power_energy',
}


class Command(BaseCommand):
    help = "Assign categories to courses that have missing or invalid category values."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true', dest='apply', default=False,
            help='Apply changes to the database instead of just showing suggestions.'
        )

    def handle(self, *args, **options):
        apply_changes = options.get('apply')

        allowed = [c[0] for c in SKILL_AREAS]
        qs = Course.objects.exclude(category__in=allowed)

        if not qs.exists():
            self.stdout.write(self.style.SUCCESS('No courses with missing or invalid categories found.'))
            return

        updates = []
        for c in qs:
            old_cat = (c.category or '').strip().lower()
            assigned = None
            if old_cat and old_cat in OLD_MAP:
                assigned = OLD_MAP[old_cat]
            else:
                text = (c.title or '') + ' ' + (c.description or '')
                text = text.lower()
                for keywords, cat in MAPPING:
                    for kw in keywords:
                        if kw in text:
                            assigned = cat
                            break
                    if assigned:
                        break

            if not assigned:
                assigned = 'education'

            updates.append((c, assigned))

        for course, new_cat in updates:
            self.stdout.write(f"{course.id}: '{course.title}' (was: '{course.category}') => suggested: '{new_cat}'")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete. Rerun with --apply to save changes."))
            return

        for course, new_cat in updates:
            course.category = new_cat
            course.save()

        self.stdout.write(self.style.SUCCESS(f"Updated {len(updates)} course(s)."))
