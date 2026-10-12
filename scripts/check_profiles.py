import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django
django.setup()
from django.contrib.auth import get_user_model
from saed.models import Profile

User = get_user_model()
for u in User.objects.all():
    p = getattr(u, 'profile', None)
    if p:
        print(f"User(id={u.id}): email={u.email}, first={u.first_name}, last={u.last_name}")
        print(f"  Profile(id={p.id}): role={p.role}, has_paid={p.has_paid}, is_authorized={p.is_authorized}")
    else:
        print(f"User(id={u.id}): email={u.email}, first={u.first_name}, last={u.last_name} -- NO PROFILE")
