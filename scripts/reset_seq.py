import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django; django.setup()
from django.db import connection
c = connection.cursor()
c.execute("DELETE FROM sqlite_sequence WHERE name='auth_user'")
c.execute("DELETE FROM sqlite_sequence WHERE name='saed_profile'")
print("Reset ID counts for auth_user and saed_profile")
