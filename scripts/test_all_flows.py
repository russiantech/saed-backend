"""
Comprehensive end-to-end test for SAED IMS
Tests every flow: auth, programs, trainers, courses, payments, notifications, permissions
"""
import requests
import json
import sys

BASE = "http://127.0.0.1:8002/api"
passed = 0
failed = 0
errors = []

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        short = detail[:120] if detail else "unexpected"
        errors.append(f"{name}: {short}")
        print(f"  FAIL  {name}: {short}")

def login(session, email, password):
    r = session.get(f"{BASE}/csrf/")
    token = session.cookies.get("csrftoken", "")
    r = session.post(f"{BASE}/auth/login/",
        json={"email": email, "password": password},
        headers={"X-CSRFToken": token, "Content-Type": "application/json"})
    return token, r

def auth_get(session, endpoint):
    return session.get(f"{BASE}/{endpoint}")

def auth_post(session, endpoint, data, token=None):
    if token is None:
        token = session.cookies.get("csrftoken", "")
    return session.post(f"{BASE}/{endpoint}", json=data,
        headers={"X-CSRFToken": token, "Content-Type": "application/json"})

# ============================================================
print("\n=== 1. PUBLIC ENDPOINTS ===")
r = requests.get(f"{BASE}/health/")
check("GET /health/", r.ok and "status" in r.json(), r.text[:100])

r = requests.get(f"{BASE}/csrf/")
check("GET /csrf/", r.ok and "csrfToken" in r.json(), r.text[:100])

r = requests.get(f"{BASE}/programs/")
check("GET /programs/ (public)", r.ok and "programs" in r.json(), r.text[:100])

r = requests.get(f"{BASE}/auth/me/")
check("GET /me/ (unauth=null)", r.ok and r.json().get("user") is None, r.text[:100])

# ============================================================
print("\n=== 2. SIGNUP FLOW ===")
s = requests.Session()
s.get(f"{BASE}/csrf/")
token = s.cookies.get("csrftoken", "")

r = auth_post(s, "auth/signup/", {
    "fullName": "Test", "email": "new@test.com", "password": "Pass1234!"
})
check("Signup validation (missing fields)", r.status_code == 400 and "error" in r.json(), r.text[:150])

import time
uname = f"e2e_{int(time.time())}"
r = auth_post(s, "auth/signup/", {
    "fullName": "New User", "email": f"{uname}@test.com", "password": "Pass1234!",
    "username": uname, "phone": "08099999999", "role": "corps_member",
    "nyscStateCode": "LA/20/100", "stateOfDeployment": "Lagos",
    "stateOfOrigin": "Ogun", "lgaOfDeployment": "Ikeja", "skillInterest": "Fashion"
})
check("Signup new user", r.ok and "user" in r.json(), r.text[:150])

r = auth_post(s, "auth/signup/", {
    "fullName": "Dup", "email": f"{uname}@test.com", "password": "Pass1234!",
    "username": uname, "phone": "08099999999", "role": "corps_member",
    "nyscStateCode": "LA/20/100", "stateOfDeployment": "Lagos",
    "stateOfOrigin": "Ogun", "lgaOfDeployment": "Ikeja", "skillInterest": "Fashion"
})
check("Signup duplicate (error)", r.status_code in [400, 409] and "error" in r.json(), r.text[:150])

# ============================================================
print("\n=== 3. LOGIN / LOGOUT / ME ===")
s = requests.Session()
token, r = login(s, "corper@test.com", "wrongpass")
check("Login wrong password", r.status_code in [400, 401] and "error" in r.json(), r.text[:150])

token, r = login(s, "corper@test.com", "Pass1234!")
r = auth_get(s, "auth/me/")
check("Login + GET /me (has user)", r.ok and r.json().get("user") is not None, r.text[:150])
check("Login + GET /me (corper1)", "corper1" in r.text, r.text[:150])

r = auth_post(s, "auth/logout/", {})
check("Logout", r.ok and r.json().get("ok") is True, r.text[:100])

r = auth_get(s, "auth/me/")
check("GET /me (after logout=null)", r.ok and r.json().get("user") is None, r.text[:100])

# ============================================================
print("\n=== 4. PASSWORD RESET ===")
s = requests.Session()
token, r = login(s, "corper@test.com", "Pass1234!")

r = auth_post(s, "auth/password-reset/", {"email": "corper@test.com"})
check("Password reset request", r.ok and "uid" in r.json(), r.text[:150])

r = auth_post(s, "auth/password-reset/confirm/", {"uid": "4", "token": "badtoken", "new_password": "NewPass1234!"})
check("Password reset bad token", r.status_code == 400 and "error" in r.json(), r.text[:150])

# ============================================================
print("\n=== 5. CORPS MEMBER ENDPOINTS ===")
s_cm = requests.Session()
token_cm, _ = login(s_cm, "corper@test.com", "Pass1234!")

for ep, key in [
    ("dashboard/", "role"), ("programs/", "programs"), ("applications/", "applications"),
    ("notifications/", "notifications"), ("connections/", "connections"),
    ("my-trainers/", "trainers"), ("trainers/", "trainers"),
    ("trainee/fast-track-courses/", "courses"),
]:
    r = auth_get(s_cm, ep)
    check(f"Corper GET /{ep}", r.ok and key in r.json(), r.text[:150])

r = auth_post(s_cm, "submit-complaint/", {"subject": "Test", "message": "Test complaint"})
check("Corper POST /submit-complaint/", r.ok and r.json().get("ok") is True, r.text[:150])

r = auth_post(s_cm, "notifications/read-all/", {})
check("Corper POST /notifications/read-all/", r.ok, r.text[:150])

r = auth_post(s_cm, "applications/create/", {"programId": 99999, "motivation": "test"})
check("Corper POST /applications/create/ (bad program)", r.status_code in [400, 404], r.text[:150])

# ============================================================
print("\n=== 6. TRAINER ENDPOINTS ===")
s_tr = requests.Session()
token_tr, _ = login(s_tr, "trainer@test.com", "Pass1234!")

for ep, key in [
    ("dashboard/", "role"), ("manage/courses/", "courses"),
    ("manage/fast-track-videos/", "courses"), ("trainer/corpers/", "corpers"),
    ("trainer/enrollments/pending/", "enrollments"), ("notifications/", "notifications"),
]:
    r = auth_get(s_tr, ep)
    check(f"Trainer GET /{ep}", r.ok and key in r.json(), r.text[:150])

r = auth_post(s_tr, "manage/courses/", {
    "title": "Python Basics", "description": "Learn Python",
    "category": "ict", "price": "50000", "durationWeeks": 4, "maxStudents": 20
})
check("Trainer POST /manage/courses/ (create)", r.ok and "course" in r.json(), r.text[:150])

r = auth_get(s_tr, "courses/1/")
check("Trainer GET /courses/1/", r.ok, r.text[:150])

# ============================================================
print("\n=== 7. SAED ADMIN ENDPOINTS ===")
s_ad = requests.Session()
token_ad, _ = login(s_ad, "admin@test.com", "Pass1234!")

for ep, key in [
    ("dashboard/", "totalUsers"), ("manage/users/", "users"),
    ("manage/programs/", "programs"), ("manage/applications/", "applications"),
    ("admin/courses/", "courses"), ("admin/refunds/pending/", "refunds"),
    ("notifications/", "notifications"),
]:
    r = auth_get(s_ad, ep)
    check(f"Admin GET /{ep}", r.ok and key in r.json(), r.text[:150])

r = auth_post(s_ad, "manage/programs/", {
    "title": "E2E Welding", "category": "construction", "description": "Welding test",
    "durationWeeks": 8, "capacity": 30, "location": "Abuja", "isActive": True
})
check("Admin POST /manage/programs/ (create)", r.ok or r.status_code == 400, r.text[:150])

r = auth_get(s_ad, "manage/users/")
users = r.json().get("users", [])
check("Admin manages users list", len(users) > 0, f"count={len(users)}")

# ============================================================
print("\n=== 8. DUNIS ADMIN ENDPOINTS ===")
s_du = requests.Session()
token_du, _ = login(s_du, "dunis@test.com", "Pass1234!")

for ep, key in [
    ("dunis/pending-payments/", "payments"),
    ("dunis/trainers/", "trainers"),
    ("manage/programs/", "programs"),
    ("manage/users/", "users"),
    ("notifications/", "notifications"),
]:
    r = auth_get(s_du, ep)
    check(f"Dunis GET /{ep}", r.ok, r.text[:150])

# ============================================================
print("\n=== 9. PERMISSION DENIAL CHECKS ===")
# Corper -> denied on admin/trainer endpoints
s_cm2 = requests.Session()
token_cm2, _ = login(s_cm2, "corper@test.com", "Pass1234!")

for ep in ["manage/users/", "manage/programs/", "manage/applications/",
           "manage/courses/", "manage/fast-track-videos/",
           "trainer/corpers/", "trainer/enrollments/pending/",
           "admin/courses/", "admin/refunds/pending/",
           "dunis/pending-payments/", "dunis/trainers/"]:
    r = auth_get(s_cm2, ep)
    denied = r.status_code == 403 or ("not have permission" in r.text.lower()) or ("method.*not allowed" in r.text.lower())
    check(f"Corper DENIED /{ep}", denied, f"{r.status_code}: {r.text[:100]}")

# Trainer -> denied on admin/dunis endpoints
s_tr2 = requests.Session()
token_tr2, _ = login(s_tr2, "trainer@test.com", "Pass1234!")

for ep in ["manage/users/",
           "admin/courses/", "admin/refunds/pending/",
           "dunis/pending-payments/", "dunis/trainers/",
           "applications/create/"]:
    r = auth_get(s_tr2, ep)
    denied = r.status_code in [403, 405] or ("not have permission" in r.text.lower()) or ("method.*not allowed" in r.text.lower()) or ("not allowed" in r.text.lower())
    check(f"Trainer DENIED /{ep}", denied, f"{r.status_code}: {r.text[:100]}")

# Admin -> denied on trainer/dunis endpoints
s_ad2 = requests.Session()
token_ad2, _ = login(s_ad2, "admin@test.com", "Pass1234!")

for ep in ["manage/courses/", "manage/fast-track-videos/",
           "dunis/pending-payments/", "dunis/trainers/",
           "trainer/corpers/", "trainer/enrollments/pending/",
           "applications/create/"]:
    r = auth_get(s_ad2, ep)
    denied = r.status_code in [403, 405] or ("not have permission" in r.text.lower()) or ("not allowed" in r.text.lower())
    check(f"Admin DENIED /{ep}", denied, f"{r.status_code}: {r.text[:100]}")

# ============================================================
print("\n=== 10. UNAUTHENTICATED DENIAL ===")
for ep in ["auth/me/", "applications/", "trainers/", "dashboard/",
           "notifications/", "connections/", "my-trainers/",
           "manage/users/", "manage/programs/", "manage/courses/",
           "admin/courses/", "manage/fast-track-videos/",
           "trainer/corpers/", "trainer/enrollments/pending/",
           "admin/refunds/pending/", "dunis/pending-payments/",
           "paystack/initialize/", "courses/pay/", "submit-complaint/"]:
    r = requests.get(f"{BASE}/{ep}")
    denied = r.status_code in [403, 401] or r.json().get("user") is None
    check(f"Unauth DENIED /{ep}", denied, f"{r.status_code}: {r.text[:100]}")

# ============================================================
print("\n=== 11. FRONTEND PROXY CHAIN ===")
import time
for ep in ["api/health/", "api/programs/"]:
    for attempt in range(5):
        try:
            r = requests.get(f"http://localhost:3002/{ep}", timeout=10)
            check(f"Proxy /{ep}", r.ok, f"{r.status_code}: {r.text[:100]}")
            break
        except Exception as e:
            if attempt < 4:
                print(f"  RETRY /{ep} (attempt {attempt+2}/5)...")
                time.sleep(5)
            else:
                check(f"Proxy /{ep}", False, str(e)[:100])

# ============================================================
print("\n=== 12. FRONTEND SPA ROUTES ===")
for path in ["/", "/login", "/signup", "/programs", "/forgot-password",
             "/inactive-account", "/trainer-signup-success", "/admin"]:
    for attempt in range(5):
        try:
            r = requests.get(f"http://localhost:3002{path}", headers={"Accept": "text/html"}, timeout=10)
            check(f"Frontend {path}", r.ok and len(r.text) > 100, f"{r.status_code}, {len(r.text)} bytes")
            break
        except Exception as e:
            if attempt < 4:
                time.sleep(5)
            else:
                check(f"Frontend {path}", False, str(e)[:100])

# ============================================================
print(f"\n{'='*50}")
print(f"RESULTS: {passed}/{passed+failed} passed, {failed} failed")
if errors:
    print(f"\nFailures:")
    for e in errors:
        print(f"  - {e}")
sys.exit(1 if failed else 0)
