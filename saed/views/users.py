
"""
User management views (admin).

Authorization state machine
----------------------------
`authorization_status` is the single source of truth for a trainer's
review state. `is_authorized` is a derived convenience flag kept in sync
with it automatically (`is_authorized == (authorization_status == "approved")`)
and is never accepted as an independent value from a client anymore --
that was the source of a real bug where a client could send `isAuthorized`
without `authorizationStatus` and produce a contradictory record.

States:
    pending   - default / awaiting admin review. Not authorized.
    approved  - reviewed and authorized to act as a trainer.
    declined  - reviewed and rejected. Can still be reconsidered later
                and approved directly by a saed_admin.
    removed   - hard-revoked by a dunis_admin. Forces the account inactive
                (isActive=False). Can ONLY re-enter the workflow via
                Restore, which always lands back on "pending" -- this is
                intentional: removal can happen from approved, pending,
                or declined, and we deliberately don't remember which, so
                that a restored account is always re-reviewed rather than
                silently regaining its old approval.

Allowed transitions are enforced here (ALLOWED_AUTH_TRANSITIONS) so that,
regardless of what the frontend's buttons currently allow, the backend
can never be pushed into an inconsistent state (e.g. "removed" ->
"approved" while still deactivated -- previously possible because the
Approve button didn't exclude "removed").

NOTE: the queryset below excludes `profile__authorization_status="restricted"`
for saed_admin, but "restricted" does not appear in VALID_AUTH_STATUSES or
anywhere in the frontend (no filter tab, no label, not in this transition
map). Confirm whether "restricted" is a real, reachable status that needs
wiring into VALID_AUTH_STATUSES / ALLOWED_AUTH_TRANSITIONS / the frontend,
or whether this exclusion clause is leftover dead code that can be removed.
"""

import json

from django.contrib.auth.models import User
from django.utils.timezone import now
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from ..models import Profile
from .base import (
    _log_error, _log_info, _log_warning,
    read_json, clean_email, user_payload, _safe_int,
    validation_error, role_for, VALID_AUTH_STATUSES, HasRole,
)

# Which authorization_status values a profile may move to, given its
# current value. Anything not listed here is rejected with a 400.
ALLOWED_AUTH_TRANSITIONS = {
    "pending": {"approved", "declined", "removed"},
    "approved": {"pending", "removed"},
    # declined -> pending lets an admin send a rejected trainer back for a
    # fresh review (e.g. they resubmitted documents) without having to
    # blind-approve them or remove the account outright.
    "declined": {"pending", "approved", "removed"},
    "removed": {"pending"},  # only reachable via restore
}


def apply_authorization_transition(user, profile, target_status):
    """
    Move `profile` to `target_status`, deriving `is_authorized` and
    `authorized_at` from it, and enforcing the allowed-transition map.

    Also owns the isActive side-effects that are part of the removal /
    restore lifecycle (forcing the account off on removal, back on when
    restored), so callers never have to remember to set isActive
    themselves for those two transitions.

    Raises ValueError with a human-readable message on an invalid
    status value or an invalid transition. Callers should catch this
    and return HTTP 400.
    """
    if target_status not in VALID_AUTH_STATUSES:
        raise ValueError(f"'{target_status}' is not a valid authorization status.")

    current_status = profile.authorization_status

    if current_status == target_status:
        return  # idempotent no-op, nothing to do

    allowed_next = ALLOWED_AUTH_TRANSITIONS.get(current_status, set())
    if target_status not in allowed_next:
        raise ValueError(
            f"Cannot move a trainer from '{current_status}' to '{target_status}' directly."
        )

    profile.authorization_status = target_status
    profile.is_authorized = target_status == "approved"
    profile.authorized_at = now() if profile.is_authorized else None

    if target_status == "removed":
        user.is_active = False
    elif current_status == "removed" and target_status == "pending":
        # This is a restore: reactivate the account, but require a fresh
        # review before it can be approved again.
        user.is_active = True


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
            return Response({"users": [user_payload(u, request) for u in users]})
        except Exception as exc:
            _log_error("User list error", exc=exc)
            return Response({"error": "Failed to load users."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        return Response(
            {"error": "Creating trainers via admin is disabled. Trainers must register through the public signup form."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


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

        # Role boundary, enforced here (not just hidden in the UI):
        # dunis_admin is a superset admin -- it can do everything saed_admin
        # can, plus account-lifecycle actions (remove/restore, raw isActive
        # toggling). saed_admin is restricted to authorization decisions
        # (approve/disapprove/decline/re-review) and must never be able to
        # remove, restore, or directly activate/deactivate an account, even
        # by calling this endpoint directly rather than clicking a button.
        actor_role = role_for(request.user)
        if actor_role == "saed_admin":
            if data.get("restore"):
                return Response(
                    {"error": "You do not have permission to restore trainers."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if data.get("authorizationStatus") == "removed":
                return Response(
                    {"error": "You do not have permission to remove trainers."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if "isActive" in data:
                return Response(
                    {"error": "You do not have permission to activate or deactivate accounts."},
                    status=status.HTTP_403_FORBIDDEN,
                )

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

                # --- Authorization workflow -----------------------------------
                # `restore` and `authorizationStatus` both go through the same
                # transition helper, which is the ONLY place that is allowed to
                # write authorization_status / is_authorized / authorized_at.
                # A bare `isAuthorized` in the payload is intentionally no
                # longer honored on its own -- it was previously possible to
                # send it without authorizationStatus and end up with an
                # authorized flag that disagreed with the workflow status.
                if data.get("restore"):
                    if profile.authorization_status != "removed":
                        return Response(
                            {"error": "Only a removed trainer can be restored."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    try:
                        apply_authorization_transition(user, profile, "pending")
                    except ValueError as exc:
                        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

                elif "authorizationStatus" in data:
                    try:
                        apply_authorization_transition(user, profile, data["authorizationStatus"])
                    except ValueError as exc:
                        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
                # -----------------------------------------------------------------

                if "isActive" in data:
                    if user.id == request.user.id and not bool(data["isActive"]):
                        return Response({"error": "You cannot deactivate your own account."},
                                        status=status.HTTP_400_BAD_REQUEST)
                    # A removed trainer can only be reactivated via Restore
                    # (which also forces a fresh review), never via the plain
                    # activate/deactivate toggle -- otherwise you can end up
                    # with isActive=True while authorizationStatus is still
                    # "removed", the same contradiction we closed off on the
                    # approve side. Deactivating a removed account is a no-op
                    # (it's already inactive) so that's left alone.
                    if bool(data["isActive"]) and profile.authorization_status == "removed":
                        return Response(
                            {"error": "A removed trainer must be restored, not directly activated."},
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    # Explicit isActive from the client always wins over the
                    # automatic remove/restore side-effects above -- this lets
                    # an admin combine actions in one request if needed.
                    user.is_active = bool(data["isActive"])

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

                if "specialization" in data:
                    profile.specialization = data["specialization"]
                if "yearsExperience" in data:
                    profile.years_experience = _safe_int(data.get("yearsExperience"), 0)
                if "companyName" in data:
                    profile.company_name = data["companyName"]
                if "bio" in data:
                    profile.bio = data["bio"]
                if "numberTrained" in data:
                    profile.number_trained = _safe_int(data.get("numberTrained"), 0)
                if "partnerLgas" in data:
                    try:
                        lgas = json.loads(data["partnerLgas"])
                        profile.partner_lgas = lgas if isinstance(lgas, list) else []
                    except (ValueError, TypeError):
                        pass
                if "partnershipLetter" in request.FILES:
                    profile.partnership_letter = request.FILES["partnershipLetter"]

                user.save()
                profile.save()
        except Exception as exc:
            _log_error(f"User update error for {user_id}", exc=exc)
            return Response({"error": "User update failed."},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response({"user": user_payload(user, request)})

