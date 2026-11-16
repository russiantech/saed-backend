import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand

from saed.models import Profile


class Command(BaseCommand):
    help = "Move partnership letters uploaded by older versions from public MEDIA_ROOT into private storage."

    def handle(self, *args, **opts):
        moved = missing = 0
        for p in Profile.objects.exclude(partnership_letter=""):
            name = p.partnership_letter.name
            src = os.path.join(str(settings.MEDIA_ROOT), name)
            dst = os.path.join(str(settings.PRIVATE_MEDIA_ROOT), name)
            if os.path.isfile(dst):
                continue
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            else:
                missing += 1
                self.stderr.write(f"missing file for user {p.user_id}: {name}")
        self.stdout.write(self.style.SUCCESS(f"moved={moved} missing={missing}"))
