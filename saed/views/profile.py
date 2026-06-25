"""
Profile views.
"""
import json
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import Profile
from .base import (
    _log_error, _log_info, _log_warning, read_json, user_payload,
    _safe_int, _parse_multipart, validation_error, IsAuthenticatedAPI,
)


class UpdateProfileView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def patch(self, request):
        parsed_data, parsed_files = _parse_multipart(request)
        data = parsed_data if parsed_data is not None else request.data

        user = request.user
        profile = getattr(user, "profile", None)
        if not profile:
            return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

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
                    user.save(update_fields=["first_name", "last_name"])

                field_mappings = {
                    "skillInterest": "skill_interest",
                    "skillInterests": "skill_interests",
                    "lgaOfDeployment": "lga_of_deployment",
                    "phone": "phone",
                    "stateOfOrigin": "state_of_origin",
                }
                for frontend_key, model_key in field_mappings.items():
                    if frontend_key in data:
                        value = data[frontend_key]
                        if frontend_key == "skillInterests":
                            if isinstance(value, str):
                                try:
                                    value = json.loads(value)
                                except (json.JSONDecodeError, TypeError):
                                    value = []
                            profile.skill_interests = value
                            if value:
                                profile.skill_interest = value[0] if value else ""
                        else:
                            setattr(profile, model_key, str(value).strip() if value else "")

                if "phone" in data:
                    phone_val = data.get("phone", "").strip()
                    if phone_val and Profile.objects.filter(phone=phone_val).exclude(user=user).exists():
                        return Response({"error": "An account with this phone number already exists.",
                                         "fields": {"phone": "Phone number already in use."}},
                                        status=status.HTTP_400_BAD_REQUEST)

                if profile.role == "trainer":
                    trainer_fields = {
                        "bio": "bio", "companyName": "company_name",
                        "yearsExperience": "years_experience",
                        "specialization": "specialization",
                        "partnerLgas": "partner_lgas",
                    }
                    for frontend_key, model_key in trainer_fields.items():
                        if frontend_key in data:
                            value = data[frontend_key]
                            if frontend_key == "partnerLgas":
                                if isinstance(value, str):
                                    try:
                                        value = json.loads(value)
                                    except (json.JSONDecodeError, TypeError):
                                        value = []
                                profile.partner_lgas = value
                            elif frontend_key == "yearsExperience":
                                profile.years_experience = _safe_int(value, 0)
                            else:
                                setattr(profile, model_key, str(value).strip() if value else "")

                files = parsed_files if parsed_files is not None else request.FILES
                if files:
                    profile_picture = files.get("profilePicture")
                    if profile_picture:
                        profile.profile_picture = profile_picture
                    partnership_letter = files.get("partnershipLetter")
                    if partnership_letter:
                        profile.partnership_letter = partnership_letter

                profile.save()
        except Exception as exc:
            _log_error(f"Profile update failed for user {user.id}", exc=exc)
            return Response({"error": "Profile update failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"user": user_payload(user, request)})
