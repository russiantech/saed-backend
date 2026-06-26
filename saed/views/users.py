"""
User management views (admin).
"""

import json
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.utils.crypto import get_random_string
from django.utils.timezone import now
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Profile
from .base import (
    _log_error, _log_info, _log_warning,
    read_json, clean_email, user_payload, _safe_int,
    validation_error, role_for, VALID_AUTH_STATUSES, HasRole,
)


class ManageUsersView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request):
        try:
            users = User.objects.select_related("profile").exclude(profile__is_hidden=True).order_by("first_name", "email")
            if role_for(request.user) == "saed_admin":
                users = users.exclude(
                    profile__authorization_status="restricted",
                    profile__restricted_by__profile__role="dunis_admin"
                )
            return Response({"users": [user_payload(u) for u in users]})
        except Exception as exc:
            _log_error("User list error", exc=exc)
            return Response({"error": "Failed to load users."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        if request.content_type and "multipart/form-data" in request.content_type:
            data = request.POST
        else:
            data = request.data

        full_name = data.get("fullName", "").strip()
        email = clean_email(data.get("email", ""))
        role = data.get("role", "trainer")
        password = data.get("password", "")
        fields = {}

        if len(full_name.split()) < 2:
            fields["fullName"] = "Enter first and last name."
        if not email:
            fields["email"] = "Enter a valid email address."
        elif User.objects.filter(email__iexact=email).exists():
            fields["email"] = "An account with this email already exists."
        phone = data.get("phone", "").strip()
        if phone and Profile.objects.filter(phone=phone).exists():
            fields["phone"] = "An account with this phone number already exists."
        if role != "trainer":
            fields["role"] = "Admins can create trainer accounts only."
        if password:
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
                    username=email, email=email,
                    password=password or get_random_string(20),
                    first_name=full_name.split(" ", 1)[0],
                    last_name=full_name.split(" ", 1)[1] if " " in full_name else "",
                )
                Profile.objects.create(
                    user=user, role="trainer",
                    phone=data.get("phone", "").strip(),
                    specialization=data.get("specialization", "").strip(),
                    years_experience=_safe_int(data.get("yearsExperience", 0), 0),
                    company_name=data.get("companyName", "").strip(),
                    bio=data.get("bio", "").strip(),
                    number_trained=_safe_int(data.get("numberTrained", 0), 0),
                    partner_lgas=json.loads(data.get("partnerLgas", "[]"))
                        if isinstance(data.get("partnerLgas"), str)
                        else data.get("partnerLgas", []),
                    is_authorized=True,
                )
                partnership_letter = request.FILES.get("partnershipLetter")
                if partnership_letter:
                    user.profile.partnership_letter = partnership_letter
                    user.profile.save(update_fields=["partnership_letter"])
                return Response({"user": user_payload(user)}, status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({"error": "An account with this email already exists.",
                             "fields": {"email": "Email is already registered."}},
                            status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            _log_error("Admin user creation error", exc=exc)
            return Response({"error": "User creation failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ManageUserDetailView(APIView):
    permission_classes = [HasRole("saed_admin", "dunis_admin")]

    def get(self, request, user_id):
        try:
            user = User.objects.select_related("profile").get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"user": user_payload(user, request)})

    def patch(self, request, user_id):
        try:
            user = User.objects.select_related("profile").get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        profile = getattr(user, "profile", None)
        if not profile:
            profile = Profile.objects.create(user=user)

        try:
            with transaction.atomic():
                if "fullName" in data:
                    full_name = data.get("fullName", "").strip()
                    if len(full_name.split()) < 2:
                        return Response({"error": "Enter first and last name.",
                                         "fields": {"fullName": "First and last name required."}},
                                        status=status.HTTP_400_BAD_REQUEST)
                    user.first_name = full_name.split(" ", 1)[0]
                    user.last_name = full_name.split(" ", 1)[1] if " " in full_name else ""

                if "role" in data:
                    if user.id == request.user.id:
                        return Response({"error": "You cannot change your own role."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    if data["role"] not in {"corps_member", "trainer"}:
                        return Response({"error": "Admins can only assign corps member or trainer roles."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    profile.role = data["role"]

                if "phone" in data:
                    phone_val = data.get("phone", "").strip()
                    if phone_val and Profile.objects.filter(phone=phone_val).exclude(user=user).exists():
                        return Response({"error": "An account with this phone number already exists.",
                                         "fields": {"phone": "Phone number already in use."}},
                                        status=status.HTTP_400_BAD_REQUEST)
                    profile.phone = phone_val
                if "isActive" in data:
                    if user.id == request.user.id and not bool(data["isActive"]):
                        return Response({"error": "You cannot deactivate your own account."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    user.is_active = bool(data["isActive"])
                if "isAuthorized" in data:
                    profile.is_authorized = bool(data["isAuthorized"])
                    if profile.is_authorized:
                        profile.authorization_status = "approved"
                        profile.authorized_at = now()
                    else:
                        profile.authorization_status = "pending"
                        profile.authorized_at = None
                if "authorizationStatus" in data:
                    status_val = data["authorizationStatus"]
                    if status_val in VALID_AUTH_STATUSES:
                        profile.authorization_status = status_val
                        profile.is_authorized = status_val == "approved"
                        profile.authorized_at = now() if status_val == "approved" else None
                if "hasPaid" in data:
                    profile.has_paid = bool(data["hasPaid"])
                if "canUploadFastTrack" in data:
                    profile.can_upload_fast_track = bool(data["canUploadFastTrack"])
                if "isBusyCorper" in data:
                    profile.is_busy_corper = bool(data["isBusyCorper"])
                if "paymentVerified" in data:
                    profile.payment_verified = bool(data["paymentVerified"])
                    profile.payment_verified_at = now() if profile.payment_verified else None
                    if profile.payment_verified and profile.is_authorized:
                        profile.has_paid = True

                user.save()
                profile.save()
        except Exception as exc:
            _log_error(f"User update error for {user_id}", exc=exc)
            return Response({"error": "User update failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"user": user_payload(user, request)})
