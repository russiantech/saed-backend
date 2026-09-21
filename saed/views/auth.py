"""
Authentication views: login, logout, signup, trainer signup, email verify, password reset.
"""

import json
import random
import string
from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from ..models import Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async,
    _notify_admins, _notify_admins_email, _notify_user,
    read_json, clean_email, user_payload, _safe_int, validation_error,
    HasRole,
)


class LoginView(APIView):
    
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        login_id = data.get("email", "").strip()
        password = data.get("password", "")

        if not login_id or not password:
            return Response(
                {"error": "Enter your username/email and password.",
                 "fields": {"email": "Username or email is required.", "password": "Password is required."}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = None
        authenticated = None
        try:
            user = User.objects.filter(email__iexact=login_id).first()
            if not user:
                user = User.objects.filter(username__iexact=login_id).first()

            if user:
                authenticated = authenticate(request, username=user.username, password=password)
                if authenticated is None and user.check_password(password):
                    authenticated = user
                    authenticated.backend = "django.contrib.auth.backends.ModelBackend"
            else:
                authenticated = authenticate(request, username=login_id, password=password)

            if authenticated is None:
                _log_warning("Failed login attempt", extra={"login_id": login_id})
                return Response({"error": "Invalid username/email or password."},
                                status=status.HTTP_400_BAD_REQUEST)

            user = authenticated

            profile = getattr(user, "profile", None)
            if profile and not profile.is_email_verified:
                _log_warning(f"Login blocked: unverified email for user {user.id}")
                return Response(
                    {"error": "Please verify your email address before logging in.",
                     "email_not_verified": True,
                     "email": user.email},
                    status=status.HTTP_403_FORBIDDEN,
                )

            login(request, user)

            remember = data.get("remember", False)
            if not remember:
                request.session.set_expiry(0)
            else:
                request.session.set_expiry(60 * 60 * 24 * 30)

            _log_info(f"User {user.id} logged in")
            return Response({"user": user_payload(user, request)})

        except Exception as exc:
            _log_error("Login error", exc=exc, extra={"login_id": login_id}) 
            return Response({"error": "Login failed. Please try again."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            # user_id = request.user.id if request.user.is_authenticated else None
            user = getattr(request, "user", None)

            user_id = user.id if user and user.is_authenticated else None

            logout(request)
            _log_info(f"User {user_id} logged out")
        except Exception as exc:
            _log_error("Logout error", exc=exc)
        return Response({"ok": True})


class SignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        full_name = data.get("fullName", "").strip()
        username = data.get("username", "").strip()
        email = clean_email(data.get("email", ""))
        password = data.get("password", "")
        role = data.get("role", "corps_member")
        fields = {}

        if not username:
            fields["username"] = "Username is required."
        elif User.objects.filter(username__iexact=username).exists():
            fields["username"] = "This username is already taken."
        if len(full_name.split()) < 2:
            fields["fullName"] = "Enter first and last name."
        if not email:
            fields["email"] = "Enter a valid email address."
        elif User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        if role != "corps_member":
            fields["role"] = "Public signup is only available for corps members."
        if role == "corps_member":
            if not data.get("phone", "").strip():
                fields["phone"] = "Phone number is required."
            elif Profile.objects.filter(phone=data.get("phone", "").strip()).exists():
                fields["phone"] = "An account with this phone number already exists."
            if not data.get("nyscStateCode", "").strip():
                fields["nyscStateCode"] = "NYSC state code is required."
            if not data.get("stateOfDeployment", "").strip():
                fields["stateOfDeployment"] = "State of deployment is required."
            if not data.get("lgaOfDeployment", "").strip():
                fields["lgaOfDeployment"] = "LGA of deployment is required."
            if not data.get("skillInterest", "").strip():
                fields["skillInterest"] = "Skill interest is required."
        try:
            validate_password(password)
        except ValidationError as exc:
            fields["password"] = " ".join(exc.messages)

        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=full_name.split(" ", 1)[0],
                last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
            )
        except IntegrityError:
            return Response({"error": "An account with this email already exists.",
                             "fields": {"email": "Email is already registered."}},
                            status=status.HTTP_400_BAD_REQUEST)

        verification_token = get_random_string(64)
        Profile.objects.create(
            user=user, role=role,
            phone=data.get("phone", "").strip(),
            nysc_state_code=data.get("nyscStateCode", "").strip(),
            state_of_deployment=data.get("stateOfDeployment", "").strip(),
            state_of_origin=data.get("stateOfOrigin", "").strip(),
            lga_of_deployment=data.get("lgaOfDeployment", "").strip(),
            skill_interest=data.get("skillInterest", "").strip(),
            skill_interests=data.get("skillInterests", []),
        )

        _notify_admins(
            title="New Corps Member Registration",
            message=f"{full_name} ({email}) has registered as a corps member.",
            reason="admin_update",
        )

        _notify_admins_email(
            subject=f"New Corps Member Registration: {full_name}",
            message=(
                f"A new corps member has registered.\n"
                f"Name: {full_name}\nEmail: {email}\n"
                f"Phone: {data.get('phone', '').strip()}\n"
                f"State Code: {data.get('nyscStateCode', '').strip()}"
            ),
            email_type="general",
            html_message=(
                f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                f'<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                f'<h2 style="color:#1a5f2a;margin-top:0;">New Corps Member Registration</h2>'
                f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                f'<tr><td style="padding:8px;font-weight:bold;">Name</td><td style="padding:8px;">{full_name}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">{email}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">Phone</td><td style="padding:8px;">{data.get("phone", "").strip()}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">State Code</td><td style="padding:8px;">{data.get("nyscStateCode", "").strip()}</td></tr>'
                f'</table></div></div>'
            ),
        )

        return Response({
            "ok": True,
            "message": "Account created. Please verify your email.",
            "email": email,
        }, status=status.HTTP_201_CREATED)


class TrainerSignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.content_type and "multipart/form-data" in request.content_type:
            data = request.POST
            partner_lgas_raw = data.get("partnerLgas", "[]")
            try:
                partner_lgas = json.loads(partner_lgas_raw)
            except (json.JSONDecodeError, TypeError):
                partner_lgas = []
        else:
            data = request.data
            partner_lgas = data.get("partnerLgas", [])

        full_name = data.get("fullName", "").strip()
        email = clean_email(data.get("email", ""))
        password = data.get("password", "")
        phone = data.get("phone", "").strip()
        specialization = data.get("specialization", "").strip()
        years_experience = data.get("yearsExperience", 0)
        bio = data.get("bio", "").strip()
        company_name = data.get("companyName", "").strip()
        number_trained = data.get("numberTrained", 0)

        fields = {}
        if len(full_name.split()) < 2:
            fields["fullName"] = "Enter first and last name."
        if not email:
            fields["email"] = "Enter a valid email address."
        elif User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        if not phone:
            fields["phone"] = "Phone number is required."
        elif Profile.objects.filter(phone=phone).exists():
            fields["phone"] = "An account with this phone number already exists."
        if not specialization:
            fields["specialization"] = "Specialization is required."
        if not partner_lgas:
            fields["partnerLgas"] = "Select at least one LGA."

        partnership_letter = request.FILES.get("partnershipLetter")
        if not partnership_letter:
            fields["partnershipLetter"] = "Partnership letter is required during registration."

        _log_info(f"Trainer signup: full_name={full_name!r} email={email!r} phone={phone!r} spec={specialization!r} lgas={partner_lgas!r} has_file={bool(partnership_letter)} has_pwd={bool(password)} fields={fields}")

        try:
            validate_password(password)
        except ValidationError as exc:
            fields["password"] = " ".join(exc.messages)

        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=email, email=email, password=password,
                    first_name=full_name.split(" ", 1)[0],
                    last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
                )
                verification_token = get_random_string(64)
                profile = Profile.objects.create(
                    user=user, role="trainer", phone=phone,
                    specialization=specialization, partner_lgas=partner_lgas,
                    years_experience=_safe_int(years_experience, 0),
                    bio=bio, company_name=company_name,
                    number_trained=_safe_int(number_trained, 0),
                    is_authorized=False, authorization_status="pending",
                    has_paid=False, email_verification_token=verification_token,
                )
                if partnership_letter:
                    profile.partnership_letter = partnership_letter
                    profile.save(update_fields=["partnership_letter"])
                login(request, user)
                _log_info(f"New trainer signed up: user {user.id}")

        except IntegrityError:
            return Response({"error": "An account with this email already exists.",
                             "fields": {"email": "Email is already registered."}},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Trainer signup error", exc=exc)
            return Response({"error": "Signup failed. Please try again."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        frontend_url = getattr(django_settings, 'FRONTEND_URL', 'http://localhost:3002')
        verify_url = f"{frontend_url}/verify-email?token={verification_token}"

        _send_email_async(
            subject="Verify your SAED IMS email address",
            message=f"Hello {full_name},\n\nVerify your email: {verify_url}\n\nBest regards,\nNYSC SAED IMS",
            recipient_list=[email],
            html_message=(
                f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                f'<h1 style="color:#fff;margin:0;font-size:22px;">NYSC SAED IMS</h1></div>'
                f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                f'<h2 style="color:#1a5f2a;margin-top:0;">Email Verification</h2>'
                f'<p>Hello <strong>{full_name}</strong>,</p>'
                f'<p>Please verify your email address by clicking the button below:</p>'
                f'<p style="text-align:center;margin:30px 0;">'
                f'<a href="{verify_url}" style="background:#1a5f2a;color:#fff;padding:14px 32px;text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block;">Verify Email</a></p>'
                f'<p style="color:#666;font-size:13px;">If you did not create this account, please ignore this email.</p></div>'
                f'<div style="text-align:center;padding:15px;color:#999;font-size:12px;">&copy; 2026 NYSC SAED IMS.</div></div>'
            ),
        )

        _notify_admins_email(
            subject=f"New Trainer Registration: {full_name}",
            message=(
                f"A new trainer has registered.\n"
                f"Name: {full_name}\nEmail: {email}\n"
                f"Phone: {phone}\nSpecialization: {specialization}"
            ),
            email_type="trainer",
            from_email=email,
            html_message=(
                f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                f'<h1 style="color:#fff;margin:0;">NYSC SAED IMS</h1></div>'
                f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                f'<h2 style="color:#1a5f2a;margin-top:0;">New Trainer Registration</h2>'
                f'<table style="width:100%;border-collapse:collapse;margin:20px 0;">'
                f'<tr><td style="padding:8px;font-weight:bold;">Name</td><td style="padding:8px;">{full_name}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">Email</td><td style="padding:8px;">{email}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">Phone</td><td style="padding:8px;">{phone}</td></tr>'
                f'<tr><td style="padding:8px;font-weight:bold;">Specialization</td><td style="padding:8px;">{specialization}</td></tr>'
                f'</table></div></div>'
            ),
        )

        return Response({"user": user_payload(user, request)}, status=status.HTTP_201_CREATED)


class PasswordResetRequestView(APIView):
    """Step 1: Send 6-digit code to email, return token."""
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        if not email:
            return Response({"error": "Enter a valid email address.",
                             "fields": {"email": "Use a valid email address."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                code = get_random_string(6, allowed_chars="0123456789")
                token = get_random_string(64)
                profile = Profile.objects.filter(user=user).first()
                if profile:
                    profile.password_reset_token = token
                    profile.password_reset_code = code
                    profile.save(update_fields=["password_reset_token", "password_reset_code"])
                _send_email_async(
                    subject="SAED - Password Reset Code",
                    message=f"Your password reset code is: {code}",
                    recipient_list=[user.email],
                    html_message=(
                        f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                        f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                        f'<h1 style="color:#fff;margin:0;font-size:22px;">NYSC SAED IMS</h1></div>'
                        f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                        f'<h2 style="color:#1a5f2a;margin-top:0;">Password Reset Code</h2>'
                        f'<p>Hello <strong>{user.get_full_name() or user.username}</strong>,</p>'
                        f'<p>Your password reset code is:</p>'
                        f'<p style="text-align:center;margin:30px 0;"><span style="font-size:32px;letter-spacing:8px;font-weight:bold;color:#1a5f2a;">{code}</span></p>'
                        f'<p style="color:#666;font-size:13px;">This code expires in 15 minutes. If you did not request a reset, ignore this email.</p></div>'
                        f'<div style="text-align:center;padding:15px;color:#999;font-size:12px;">&copy; 2026 NYSC SAED IMS.</div></div>'
                    ),
                )
            return Response({"ok": True, "token": token if user else get_random_string(64),
                             "message": "If that email exists, a reset code was sent."})
        except Exception as exc:
            _log_error("Password reset request error", exc=exc)
            return Response({"error": "Password reset failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VerifyResetCodeView(APIView):
    """Step 2: Verify the 6-digit code."""
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        code = data.get("code", "").strip()
        token = data.get("token", "").strip()

        if not email or not code or not token:
            return Response({"error": "Email, code, and token are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if not user:
                return Response({"error": "Invalid code."},
                                status=status.HTTP_400_BAD_REQUEST)
            profile = Profile.objects.filter(user=user, password_reset_token=token, password_reset_code=code).first()
            if not profile:
                return Response({"error": "Invalid or expired code."},
                                status=status.HTTP_400_BAD_REQUEST)
            return Response({"ok": True, "message": "Code verified."})
        except Exception as exc:
            _log_error("Verify reset code error", exc=exc)
            return Response({"error": "Verification failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ResetPasswordView(APIView):
    """Step 3: Set new password."""
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        token = data.get("token", "").strip()
        code = data.get("code", "").strip()
        password = data.get("password", "")

        if not email or not token or not code or not password:
            return Response({"error": "All fields are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if not user:
                return Response({"error": "Invalid request."},
                                status=status.HTTP_400_BAD_REQUEST)
            profile = Profile.objects.filter(user=user, password_reset_token=token, password_reset_code=code).first()
            if not profile:
                return Response({"error": "Invalid or expired reset request."},
                                status=status.HTTP_400_BAD_REQUEST)
            try:
                validate_password(password, user)
            except ValidationError as exc:
                return Response({"error": "Choose a stronger password.",
                                 "fields": {"password": " ".join(exc.messages)}},
                                status=status.HTTP_400_BAD_REQUEST)
            user.set_password(password)
            user.save(update_fields=["password"])
            profile.password_reset_token = ""
            profile.password_reset_code = ""
            profile.save(update_fields=["password_reset_token", "password_reset_code"])
            return Response({"ok": True, "message": "Password reset successfully."})
        except Exception as exc:
            _log_error("Password reset error", exc=exc)
            return Response({"error": "Password reset failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminSignupView(APIView):
    """Admin signup — accessible at secret URL, creates saed_admin or dunis_admin."""
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        username = data.get("username", "").strip()
        password = data.get("password", "")
        phone = data.get("phone", "").strip()
        full_name = data.get("fullName", "").strip()
        role = data.get("role", "saed_admin")
        if role not in ("saed_admin", "dunis_admin"):
            role = "saed_admin"
        fields = {}

        if not email:
            fields["email"] = "Email is required."
        elif User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        if not username:
            fields["username"] = "Username is required."
        elif User.objects.filter(username__iexact=username).exists():
            fields["username"] = "This username is already taken."
        if not full_name or len(full_name.split()) < 2:
            fields["fullName"] = "Enter first and last name."
        if not password:
            fields["password"] = "Password is required."
        if phone and Profile.objects.filter(phone=phone).exists():
            fields["phone"] = f"An account with this phone number [{phone}] already exists."
        if fields:
            return Response(
                {"error": "Please correct the highlighted fields.", "fields": fields},
                status=status.HTTP_400_BAD_REQUEST
                )

        try:
            validate_password(password)
        except ValidationError as exc:
            return Response({"error": "Choose a stronger password.",
                             "fields": {"password": " ".join(exc.messages)}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                parts = full_name.split(None, 1)
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                )
                Profile.objects.create(
                    user=user,
                    role=role,
                    phone=phone,
                    is_email_verified=True,
                    is_hidden=True,
                )
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            _log_info(f"Admin account created: {email} (role={role})")
            return Response({"user": user_payload(user)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Admin signup error", exc=exc)
            return Response({"error": "Signup failed. Please try again."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HiddenAdminSignupView(APIView):
    """Hidden admin signup — requires secret key. Creates saed_admin or dunis_admin."""
    permission_classes = [AllowAny]

    def post(self, request):
        secret = request.data.get("secret", "").strip()
        expected = getattr(django_settings, "ADMIN_SIGNUP_SECRET", "")
        if not expected or secret != expected:
            return Response({"error": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        email = clean_email(data.get("email", ""))
        username = data.get("username", "").strip()
        password = data.get("password", "")
        phone = data.get("phone", "").strip()
        full_name = data.get("fullName", "").strip()
        role = data.get("role", "saed_admin")

        if role not in ("saed_admin", "dunis_admin"):
            return Response({"error": "Invalid role."}, status=status.HTTP_400_BAD_REQUEST)

        fields = {}
        if not email:
            fields["email"] = "Email is required."
        elif User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        if not username:
            fields["username"] = "Username is required."
        elif User.objects.filter(username__iexact=username).exists():
            fields["username"] = "This username is already taken."
        if not full_name or len(full_name.split()) < 2:
            fields["fullName"] = "Enter first and last name."
        if not password:
            fields["password"] = "Password is required."
        if phone and Profile.objects.filter(phone=phone).exists():
            fields["phone"] = "An account with this phone number already exists."
        if fields:
            return Response({"error": "Please correct the highlighted fields.", "fields": fields},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(password)
        except ValidationError as exc:
            return Response({"error": "Choose a stronger password.",
                             "fields": {"password": " ".join(exc.messages)}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                parts = full_name.split(None, 1)
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=parts[0],
                    last_name=parts[1] if len(parts) > 1 else "",
                )
                Profile.objects.create(
                    user=user,
                    role=role,
                    phone=phone,
                    is_email_verified=True,
                )
            _log_info(f"Hidden admin account created: {email} (role={role})")
            return Response({"ok": True, "message": f"Admin account created ({role})."},
                            status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Hidden admin signup error", exc=exc)
            return Response({"error": "Signup failed. Please try again."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendCodeView(APIView):
    """Send a 6-digit verification code to the user's email."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = clean_email(request.data.get("email", ""))
        if not email:
            return Response({"error": "Enter a valid email address.",
                             "fields": {"email": "Email is required."}},
                            status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            return Response({"ok": True, "message": "If that email exists, a code was sent."})

        profile = Profile.objects.filter(user=user).first()
        if not profile:
            return Response({"ok": True, "message": "If that email exists, a code was sent."})

        if profile.is_email_verified:
            return Response({"ok": True, "message": "Email is already verified."})

        code = "".join(random.choices(string.digits, k=6))
        profile.email_verification_code = code
        profile.email_verification_code_at = now()
        profile.save(update_fields=["email_verification_code", "email_verification_code_at"])

        _send_email_async(
            subject="SAED IMS - Your Verification Code",
            message=f"Your verification code is: {code}",
            recipient_list=[user.email],
            html_message=(
                f'<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;">'
                f'<div style="background:#1a5f2a;padding:20px;border-radius:8px 8px 0 0;">'
                f'<h1 style="color:#fff;margin:0;font-size:22px;">NYSC SAED IMS</h1></div>'
                f'<div style="background:#f9f9f9;padding:30px;border:1px solid #e0e0e0;">'
                f'<h2 style="color:#1a5f2a;margin-top:0;">Email Verification</h2>'
                f'<p>Hello <strong>{user.get_full_name() or user.username}</strong>,</p>'
                f'<p>Your verification code is:</p>'
                f'<p style="text-align:center;margin:30px 0;"><span style="font-size:32px;letter-spacing:8px;font-weight:bold;color:#1a5f2a;">{code}</span></p>'
                f'<p style="color:#666;font-size:13px;">This code expires in 10 minutes. If you did not create this account, ignore this email.</p></div>'
                f'<div style="text-align:center;padding:15px;color:#999;font-size:12px;">&copy; 2026 NYSC SAED IMS.</div></div>'
            ),
        )

        _log_info(f"Verification code sent to {email}")
        return Response({"ok": True, "message": "Code sent to your email."})


class VerifyCodeView(APIView):
    """Verify the 6-digit code and log the user in."""
    permission_classes = [AllowAny]

    def post(self, request):
        email = clean_email(request.data.get("email", ""))
        code = request.data.get("code", "").strip()

        if not email or not code:
            return Response({"error": "Email and code are required.",
                             "fields": {"email": "Email is required." if not email else "",
                                        "code": "Code is required." if not code else ""}},
                            status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            return Response({"error": "Invalid code.",
                             "fields": {"code": "Invalid code."}},
                            status=status.HTTP_400_BAD_REQUEST)

        profile = Profile.objects.filter(user=user).first()
        if not profile:
            return Response({"error": "Invalid code.",
                             "fields": {"code": "Invalid code."}},
                            status=status.HTTP_400_BAD_REQUEST)

        if profile.is_email_verified:
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return Response({"user": user_payload(user, request)})

        if not profile.email_verification_code or profile.email_verification_code != code:
            return Response({"error": "Invalid code.",
                             "fields": {"code": "Invalid or incorrect code."}},
                            status=status.HTTP_400_BAD_REQUEST)

        if profile.email_verification_code_at:
            elapsed = (now() - profile.email_verification_code_at).total_seconds()
            if elapsed > 600:
                return Response({"error": "Code has expired.",
                                 "fields": {"code": "Code has expired. Please request a new one."}},
                                status=status.HTTP_400_BAD_REQUEST)

        profile.is_email_verified = True
        profile.is_verified = True
        profile.email_verification_code = ""
        profile.email_verification_code_at = None
        profile.save(update_fields=["is_email_verified", "is_verified", "email_verification_code", "email_verification_code_at"])

        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        _log_info(f"User {user.id} verified email via code and logged in")
        return Response({"user": user_payload(user, request)})
