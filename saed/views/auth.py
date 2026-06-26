"""
Authentication views: login, logout, signup, trainer signup, email verify, password reset.
"""

import json
from django.conf import settings as django_settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.models import User
from django.utils.crypto import get_random_string
from django.utils.encoding import force_str, force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from ..models import Profile
from .base import (
    _log_error, _log_info, _log_warning, _send_email_async,
    _notify_admins_email, _notify_user,
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

            login(request, user)
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


class ValidateSignupView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        fields = {}

        email = clean_email(data.get("email", ""))
        phone = data.get("phone", "").strip()
        username = data.get("username", "").strip()

        if email and User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        if phone and Profile.objects.filter(phone=phone).exists():
            fields["phone"] = "An account with this phone number already exists."
        if username and User.objects.filter(username__iexact=username).exists():
            fields["username"] = "This username is already taken."

        if fields:
            return Response({"ok": False, "fields": fields}, status=status.HTTP_400_BAD_REQUEST)
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
        login(request, user)
        return Response({"user": user_payload(user, request)}, status=status.HTTP_201_CREATED)


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


class EmailVerifyView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        token = data.get("token", "")
        if not token:
            return Response({"error": "Verification token is required.",
                             "fields": {"token": "Token is required."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            profile = Profile.objects.filter(email_verification_token=token).select_related("user").first()
            if not profile:
                return Response({"error": "Invalid or expired verification token."},
                                status=status.HTTP_400_BAD_REQUEST)
            profile.is_email_verified = True
            profile.email_verification_token = ""
            profile.save(update_fields=["is_email_verified", "email_verification_token"])
            return Response({"ok": True, "message": "Email verified successfully."})
        except Exception as exc:
            _log_error("Email verification error", exc=exc)
            return Response({"error": "Verification failed. Please try again."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        if not email:
            return Response({"error": "Enter a valid email address.",
                             "fields": {"email": "Use a valid email address."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            user = User.objects.filter(email=email, is_active=True).first()
            if user:
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)
                frontend_url = getattr(django_settings, "FRONTEND_URL", "http://localhost:3002")
                reset_url = f"{frontend_url}/reset-password?uid={uid}&token={token}"
                _send_email_async(
                    subject="SAED - Password Reset",
                    message=f"Click the link to reset your password: {reset_url}",
                    recipient_list=[user.email],
                )
            return Response({"ok": True, "message": "If that email exists, reset instructions were sent."})
        except Exception as exc:
            _log_error("Password reset request error", exc=exc)
            return Response({"error": "Password reset failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        uid = data.get("uid", "")
        token = data.get("token", "")
        password = data.get("password", "")

        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id, is_active=True)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is None or not default_token_generator.check_token(user, token):
            return Response({"error": "This password reset link is invalid or has expired.",
                             "fields": {"token": "Request a new reset link."}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            validate_password(password, user)
        except ValidationError as exc:
            return Response({"error": "Choose a stronger password.",
                             "fields": {"password": " ".join(exc.messages)}},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            user.set_password(password)
            user.save(update_fields=["password"])
            return Response({"ok": True})
        except Exception as exc:
            _log_error("Password reset save error", exc=exc)
            return Response({"error": "Password reset failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminSignupView(APIView):
    """Admin signup — requires existing admin authentication."""
    permission_classes = [HasRole("saed_admin")]

    def post(self, request):
        data = request.data
        email = clean_email(data.get("email", ""))
        username = data.get("username", "").strip()
        password = data.get("password", "")
        phone = data.get("phone", "").strip()
        full_name = data.get("fullName", "").strip()
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
                    role="dunis_admin",
                    phone=phone,
                    is_email_verified=True,
                    is_hidden=True,
                )
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            _log_info(f"Hidden admin account created: {email}")
            return Response({"user": user_payload(user)}, status=status.HTTP_201_CREATED)
        except Exception as exc:
            _log_error("Admin signup error", exc=exc)
            return Response({"error": "Signup failed. Please try again."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)
