"""
Management command: deactivate In-Camp access for expired orientation camps.

Usage (cron recommended, daily):
    python manage.py deactivate_incamp

Schedule example (crontab):
    0 2 * * * cd /path/to/project && python manage.py deactivate_incamp >> /var/log/saed_incamp.log 2>&1
"""

from django.core.management.base import BaseCommand

from saed.views.incamp import deactivate_expired_in_camp_accounts  # adjust app label if needed


class Command(BaseCommand):
    help = "Deactivate In-Camp SAED access for corps members whose orientation camp + grace period has ended."

    def handle(self, *args, **options):
        try:
            # Import from the views package relative to this app structure
            from views.incamp import deactivate_expired_in_camp_accounts
        except ImportError:
            try:
                from saed.views.incamp import deactivate_expired_in_camp_accounts
            except ImportError:
                # Fallback: direct model logic
                from datetime import timedelta
                from django.utils.timezone import now
                from ...models import OrientationCamp, Profile

                today = now().date()
                count = 0
                for camp in OrientationCamp.objects.filter(is_active=True):
                    if today > camp.deactivation_date:
                        n = Profile.objects.filter(
                            role="corps_member",
                            orientation_camp=camp,
                            in_camp_access_active=True,
                        ).update(
                            in_camp_access_active=False,
                            in_camp_deactivated_at=now(),
                        )
                        count += n
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"Camp '{camp.name}': deactivated {n} accounts"
                            )
                        )
                self.stdout.write(self.style.SUCCESS(f"Total deactivated: {count}"))
                return

        count = deactivate_expired_in_camp_accounts()
        self.stdout.write(self.style.SUCCESS(f"Deactivated {count} In-Camp accounts."))
