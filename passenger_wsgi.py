"""cPanel / CloudLinux "Setup Python App" (Phusion Passenger) entry point.

In the Python App screen set:  Application root = this folder,  Application startup file = passenger_wsgi.py,
Application Entry point = application.  See docs/DEPLOY-CPANEL.md.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from config.wsgi import application  # noqa: E402,F401
