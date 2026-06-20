from django.core.management.base import BaseCommand

from saed.models import Program


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
    help = "Assign categories to programs that have missing or invalid category values."

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true', dest='apply', default=False,
            help='Apply changes to the database instead of just showing suggestions.'
        )

    def handle(self, *args, **options):
        apply_changes = options.get('apply')

        allowed = [c[0] for c in Program.CATEGORY_CHOICES]
        qs = Program.objects.exclude(category__in=allowed)

        if not qs.exists():
            self.stdout.write(self.style.SUCCESS('No programs with missing or invalid categories found.'))
            return

        updates = []
        for p in qs:
            # try direct mapping from existing category value first
            old_cat = (p.category or '').strip().lower()
            assigned = None
            if old_cat and old_cat in OLD_MAP:
                assigned = OLD_MAP[old_cat]
            else:
                text = (p.title or '') + ' ' + (p.description or '')
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

            updates.append((p, assigned))

        # Print suggestions
        for prog, new_cat in updates:
            self.stdout.write(f"{prog.id}: '{prog.title}' (was: '{prog.category}') => suggested: '{new_cat}'")

        if not apply_changes:
            self.stdout.write(self.style.WARNING("Dry run complete. Rerun with --apply to save changes."))
            return

        # Apply
        for prog, new_cat in updates:
            prog.category = new_cat
            prog.save()

        self.stdout.write(self.style.SUCCESS(f"Updated {len(updates)} program(s).") )
