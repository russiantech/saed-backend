"""
Send all 9 SAED IMS emails with REAL tokens to lordhunter5522@gmail.com
"""
import os, sys, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'saed-backend'))
django.setup()

from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.core.mail import send_mail
from django.conf import settings
from saed.models import Profile, Course, CourseEnrollment
from datetime import date, timedelta

TO = "lordhunter5522@gmail.com"
count = 0

def send(name, subject, text, html):
    global count
    count += 1
    send_mail(subject=subject, message=text, from_email=settings.DEFAULT_FROM_EMAIL,
              recipient_list=[TO], fail_silently=False, html_message=html)
    print(f"  [{count}] {name}")

print(f"Sending 9 emails with REAL tokens to {TO} ...\n")

# Create trainer with real verification token
token = get_random_string(64)
trainer, created = User.objects.get_or_create(
    username="real_trainer_email",
    defaults={"email": "real_trainer_verify@test.com", "first_name": "Real", "last_name": "Trainer"}
)
if created:
    trainer.set_password("Pass1234!")
    trainer.save()
profile, _ = Profile.objects.get_or_create(user=trainer, defaults={"role": "trainer", "phone": "08012345678"})
profile.email_verification_token = token
profile.save(update_fields=["email_verification_token"])
verify_url = f"http://localhost:3002/verify-email?token={token}"
print(f"  Real token: {token}")
print(f"  Verify URL: {verify_url}\n")

# Create corper
corper, _ = User.objects.get_or_create(
    username="real_corper_email",
    defaults={"email": "real_corper@test.com", "first_name": "Real", "last_name": "Corper"}
)
if corper._state.adding:
    corper.set_password("Pass1234!")
    corper.save()
Profile.objects.get_or_create(user=corper, defaults={
    "role": "corps_member", "phone": "08012345678",
    "nysc_state_code": "LA/26/1234", "state_of_deployment": "Lagos",
    "lga_of_deployment": "Ikeja", "skill_interest": "Web Development",
})

# 1. Trainer Email Verification
send("Trainer Email Verification",
    "Verify your SAED IMS email address",
    f"Hello Real Trainer, verify your email: {verify_url}",
    f'<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    f'<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    f'<h2 style="color:#1a5f2a;margin-top:0;">Email Verification</h2>'
    f'<p>Hello <strong>Real Trainer</strong>,</p>'
    f'<p>Please verify your email address by clicking the button below:</p>'
    f'<p style="text-align:center;margin:30px 0;">'
    f'<a href="{verify_url}" style="background:#1a5f2a;color:#fff;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">Verify Email</a></p>'
    f'<p style="color:#666;font-size:13px;">If you did not create this account, please ignore this email.</p></div>'
    f'<div style="text-align:center;padding:15px;color:#999;font-size:12px;">2026 NYSC SAED IMS</div></div>')

# 2. Trainer Signup - MD Notification
send("Trainer Signup - MD Notification",
    "New Trainer Registration: Real Trainer",
    "A new trainer has registered. Name: Real Trainer, Email: real_trainer_verify@test.com",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">New Trainer Registration</h2>'
    '<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
    '<tr><td style="padding:8px;font-weight:bold;">Name</td><td style="padding:8px;">Real Trainer</td></tr>'
    '<tr><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">real_trainer_verify@test.com</td></tr>'
    '<tr><td style="padding:8px;font-weight:bold;">Specialization</td><td style="padding:8px;">Web Development</td></tr>'
    '</table></div></div>')

# 3. Enrollment Confirmed
send("Enrollment Confirmed",
    "SAED IMS - Course Enrollment Confirmed",
    "Hello Real Corper, Your payment has been confirmed.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Enrollment Confirmed</h2>'
    '<p>Your payment for <strong>Real Token Course</strong> has been confirmed.</p></div></div>')

# 4. Payment Not Verified
send("Payment Not Verified",
    "SAED IMS - Course Payment Not Verified",
    "Hello Real Corper, Your payment could not be verified. A refund has been initiated.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#c0392b;margin-top:0;">Payment Not Verified</h2>'
    '<p>Your payment for <strong>Real Token Course</strong> could not be verified. A refund of <strong>N50,000</strong> has been initiated.</p></div></div>')

# 5. Refund Processed
send("Refund Processed",
    "SAED IMS - Refund Processed",
    "Hello Real Corper, Your refund of N50,000 has been processed.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Refund Processed</h2>'
    '<p>Your refund of <strong>N50,000</strong> for <strong>Real Token Course</strong> has been processed.</p></div></div>')

# 6. Refund Denied
send("Refund Denied",
    "SAED IMS - Refund Denied",
    "Hello Real Corper, Your refund request has been denied.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#c0392b;margin-top:0;">Refund Denied</h2>'
    '<p>Your refund request for <strong>N50,000</strong> (Real Token Course) has been denied.</p></div></div>')

# 7. Connection Request
send("Connection Request",
    "SAED IMS - New Connection Request",
    "Hello Real Trainer, Real Corper wants to connect with you.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">New Connection Request</h2>'
    '<p><strong>Real Corper</strong> wants to connect with you.</p></div></div>')

# 8. Connection Approved
send("Connection Approved",
    "SAED IMS - Connection Approved!",
    "Hello Real Corper, Your connection with Real Trainer has been approved!",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Connection Approved!</h2>'
    '<p>Your connection with <strong>Real Trainer</strong> has been approved!</p></div></div>')

# 9. Account Activated
send("Account Activated",
    "SAED IMS - Account Activated!",
    "Hello Real Trainer, Your payment has been verified and your account has been activated.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Account Activated!</h2>'
    '<p>Your payment has been verified and your account has been <strong>activated</strong>.</p></div></div>')

print(f"\nDone! {count} emails sent to {TO}")
print(f"\nEmail #1 has a REAL token. Click this to verify:")
print(f"  {verify_url}")
