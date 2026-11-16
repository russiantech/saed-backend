"""Backward-compatible alias. Django's own SMTP backend is used (it supports Python 3.12+)."""
from django.core.mail.backends.smtp import EmailBackend  # noqa: F401
