"""
SAED IMS - Send all 9 email scenarios to lordhunter5522@gmail.com
"""
import os, sys, django, time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'saed-backend'))
django.setup()

from django.core.mail import send_mail
from django.conf import settings

TO = "lordhunter5522@gmail.com"
count = 0

def send(name, subject, text, html):
    global count
    count += 1
    send_mail(subject=subject, message=text, from_email=settings.DEFAULT_FROM_EMAIL,
              recipient_list=[TO], fail_silently=False, html_message=html)
    print(f"  [{count}] {name}")

print("Sending 9 emails to lordhunter5522@gmail.com ...\n")

# 1. Trainer Email Verification
send("Trainer Email Verification",
    "Verify your SAED IMS email address",
    "Hello New Trainer, verify your email: http://localhost:3002/verify-email?token=test123",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Email Verification</h2>'
    '<p>Hello <strong>New Trainer</strong>,</p>'
    '<p>Please verify your email address by clicking the button below:</p>'
    '<p style="text-align:center;margin:30px 0;">'
    '<a href="http://localhost:3002/verify-email?token=test123" style="background:#1a5f2a;color:#fff;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">Verify Email</a></p>'
    '<p style="color:#666;font-size:13px;">If you did not create this account, please ignore this email.</p></div>'
    '<div style="text-align:center;padding:15px;color:#999;font-size:12px;">2026 NYSC SAED IMS</div></div>')

# 2. Trainer Signup - MD Notification
send("Trainer Signup - MD Notification",
    "New Trainer Registration: New Test Trainer",
    "A new trainer has registered. Name: New Test Trainer, Email: newtrainer@test.com",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">New Trainer Registration</h2>'
    '<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
    '<tr><td style="padding:8px;font-weight:bold;">Name</td><td style="padding:8px;">New Test Trainer</td></tr>'
    '<tr><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">newtrainer@test.com</td></tr>'
    '<tr><td style="padding:8px;font-weight:bold;">Phone</td><td style="padding:8px;">08012345678</td></tr>'
    '<tr><td style="padding:8px;font-weight:bold;">Specialization</td><td style="padding:8px;">Web Development</td></tr>'
    '</table></div></div>')

# 3. Enrollment Confirmed
send("Enrollment Confirmed",
    "SAED IMS - Course Enrollment Confirmed",
    "Hello Test Corper, Your payment for Web Development Bootcamp has been confirmed.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Enrollment Confirmed</h2>'
    '<p>Your payment for <strong>Web Development Bootcamp</strong> has been confirmed.</p>'
    '<p>You now have full access to the course materials.</p></div></div>')

# 4. Payment Not Verified
send("Payment Not Verified",
    "SAED IMS - Course Payment Not Verified",
    "Hello Test Corper, Your payment could not be verified. A refund has been initiated.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#c0392b;margin-top:0;">Payment Not Verified</h2>'
    '<p>Your payment for <strong>Web Development Bootcamp</strong> could not be verified.</p>'
    '<p>A refund of <strong>N50,000</strong> has been initiated.</p></div></div>')

# 5. Refund Processed
send("Refund Processed",
    "SAED IMS - Refund Processed",
    "Hello Test Corper, Your refund of N75,000 has been processed.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Refund Processed</h2>'
    '<p>Your refund of <strong>N75,000</strong> for <strong>Data Science Course</strong> has been processed.</p>'
    '<p>The refund will reflect in your account within 3-5 business days.</p></div></div>')

# 6. Refund Denied
send("Refund Denied",
    "SAED IMS - Refund Denied",
    "Hello Test Corper, Your refund request has been denied.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#c0392b;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#c0392b;margin-top:0;">Refund Denied</h2>'
    '<p>Your refund request for <strong>N25,000</strong> (Web Development Bootcamp) has been denied.</p>'
    '<p>Contact support for more information.</p></div></div>')

# 7. Connection Request
send("Connection Request",
    "SAED IMS - New Connection Request",
    "Hello Test Trainer, Test Corper wants to connect with you.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">New Connection Request</h2>'
    '<p><strong>Test Corper</strong> wants to connect with you.</p>'
    '<p>Log in to accept or decline this request.</p></div></div>')

# 8. Connection Approved
send("Connection Approved",
    "SAED IMS - Connection Approved!",
    "Hello Test Corper, Your connection with Test Trainer has been approved!",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Connection Approved!</h2>'
    '<p>Your connection with <strong>Test Trainer</strong> has been approved!</p>'
    '<p>You can now communicate and collaborate.</p></div></div>')

# 9. Account Activated
send("Account Activated",
    "SAED IMS - Account Activated!",
    "Hello Test Trainer, Your payment has been verified and your account has been activated.",
    '<div style="font-family:Arial;max-width:600px;margin:0 auto;padding:20px;">'
    '<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
    '<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
    '<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
    '<h2 style="color:#1a5f2a;margin-top:0;">Account Activated!</h2>'
    '<p>Your payment has been verified and your account has been <strong>activated</strong>.</p>'
    '<p>You can now create courses and connect with corps members.</p>'
    '<p>Payment Reference: SAED-PAY-TEST123</p></div></div>')

print(f"\nDone! {count} emails sent to {TO}")
