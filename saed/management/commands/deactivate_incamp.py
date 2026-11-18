"""
Management command: deactivate In-Camp accounts (corps members and trainers) whose stream has ended.

Expiry is also enforced live from the stream dates on every request; this command persists it, notifies the
people affected and keeps reports accurate. Run it daily:

    0 2 * * * cd /path/to/backend && python manage.py deactivate_incamp
"""
from django.core.management.base import BaseCommand

from saed.services.streams import expire_memberships


class Command(BaseCommand):
    help = "Deactivate In-Camp accounts whose stream (plus grace period) has ended."

    def handle(self, *args, **options):
        counts = expire_memberships()
        self.stdout.write(self.style.SUCCESS(
            f"Deactivated {counts.get('corps_member', 0)} corps member(s) and {counts.get('trainer', 0)} trainer(s)."))
