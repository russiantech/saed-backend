"""Private storage for paid / protected learning material.

Files here are NEVER exposed under MEDIA_URL. They are only reachable through the
authenticated, permission-checked streaming endpoint (see services/media.py).
"""
import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
    """Always resolves PRIVATE_MEDIA_ROOT lazily, so the setting can be overridden (tests, deployments)."""

    @property
    def base_location(self):
        return str(settings.PRIVATE_MEDIA_ROOT)

    @property
    def location(self):
        return os.path.abspath(self.base_location)


def get_private_storage():
    return PrivateStorage(base_url=None)
