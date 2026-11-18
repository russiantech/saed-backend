"""Stream life-cycle: who is In-Camp, which stream they belong to, and when their account switches off.

In-Camp and Post-Camp are separate tracks (``Profile.account_mode``). An In-Camp corps member or trainer lives
inside one or more *streams* (``StreamMembership``); their account is usable until the stream's deactivation date.
Everything here is computed from dates at request time, so expiry is immediate and does not depend on a cron job;
``expire_memberships`` only persists the state (and tells people) so reports and the admin UI stay accurate.
"""
from datetime import timedelta

from django.utils.timezone import now

from ..models import Profile, Stream, StreamMembership

IN_CAMP, POST_CAMP = "in_camp", "post_camp"
TRACK_ROLES = ("corps_member", "trainer")
# Endpoints an expired In-Camp user may still call (sign out, read notices, see the expiry state).
EXPIRED_ALLOWED_PREFIXES = ("/api/auth/", "/api/notifications/", "/api/dashboard/", "/api/incamp/dashboard/",
                            "/api/submit-complaint/", "/api/csrf/", "/api/health")


def today():
    return now().date()


def track_of(user) -> str | None:
    """in_camp / post_camp for corps members and trainers; None for admins and anonymous users."""
    profile = getattr(user, "profile", None) if getattr(user, "is_authenticated", False) else None
    if profile is None or profile.role not in TRACK_ROLES:
        return None
    return IN_CAMP if profile.account_mode == IN_CAMP else POST_CAMP


def stream_payload(stream, camps=False):
    if stream is None:
        return None
    d = {
        "id": stream.id, "year": stream.year, "number": stream.number, "label": stream.label, "name": stream.name,
        "startDate": stream.start_date.isoformat(), "endDate": stream.end_date.isoformat(),
        "deactivationGraceDays": stream.deactivation_grace_days,
        "deactivationDate": stream.deactivation_date.isoformat(),
        "isActive": stream.is_active, "status": stream.status(), "notes": stream.notes,
    }
    if camps:
        d["camps"] = [{"id": c.id, "name": c.name, "state": c.state} for c in stream.camps.filter(is_active=True)]
    return d


def _window(stream, on):
    """Days left before the stream's accounts switch off (0 on the last day, None once over)."""
    left = (stream.deactivation_date - on).days
    return left if left >= 0 else None


def lifecycle(user) -> dict:
    """The account's life-cycle. ``isActive`` is what access checks use; the rest is for the portal banner.

    Memoised on the user object, which lives for one request (DRF re-loads the user every request), so permission
    checks, payloads and per-row access checks share a single computation.
    """
    cached = getattr(user, "_stream_lifecycle", None)
    if cached is None:
        cached = user._stream_lifecycle = _compute_lifecycle(user)
    return cached


def _compute_lifecycle(user) -> dict:
    track = track_of(user)
    if track != IN_CAMP:
        return {"track": track, "state": "not_applicable" if track else None, "isActive": True, "stream": None}
    on = today()
    rows = list(StreamMembership.objects.filter(user=user).select_related("stream")
                .order_by("-stream__year", "-stream__number"))
    live = [m for m in rows if m.status == "active" and m.stream.is_active and not m.stream.is_past_deactivation(on)]
    if live:
        # the running stream first, then the soonest upcoming one
        live.sort(key=lambda m: (m.stream.start_date > on, m.stream.start_date))
        m = live[0]
        st = m.stream
        return {"track": track, "state": "upcoming" if on < st.start_date else "active", "isActive": True,
                "stream": stream_payload(st), "streamId": st.id, "membershipStatus": m.status,
                "daysRemaining": _window(st, on), "streamIds": [x.stream_id for x in live],
                "daysToStart": (st.start_date - on).days if on < st.start_date else 0}
    if rows:
        m = rows[0]
        st = m.stream
        return {"track": track, "state": "expired", "isActive": False, "stream": stream_payload(st), "streamId": st.id,
                "membershipStatus": m.status if m.status != "active" else "expired", "daysRemaining": None,
                "streamIds": [],
                "reason": "deactivated" if m.status == "deactivated" else "stream_ended"}
    return {"track": track, "state": "none", "isActive": False, "stream": None, "streamIds": [], "daysRemaining": None,
            "reason": "no_stream"}


def is_in_camp_active(user) -> bool:
    return lifecycle(user)["isActive"]


def lifecycle_blocked(request) -> str | None:
    """A message when an In-Camp user's stream has ended and the endpoint is not on the allow-list."""
    user = request.user
    if track_of(user) != IN_CAMP:
        return None
    path = request.path
    if any(path.startswith(p) for p in EXPIRED_ALLOWED_PREFIXES):
        return None
    lc = lifecycle(user)
    if lc["isActive"]:
        return None
    if lc["state"] == "none":
        return "Your In-Camp account is not attached to a stream yet. Please contact SAED admin."
    who = "trainer" if user.profile.role == "trainer" else "corps member"
    return (f"Your In-Camp stream ({lc['stream']['name']}) has ended, so this {who} account is deactivated. "
            "SAED admin can re-activate you for a new stream.")


def current_stream(user):
    """The stream a live In-Camp account is working in (Stream instance) or None."""
    lc = lifecycle(user)
    return Stream.objects.filter(pk=lc["streamId"]).first() if lc.get("isActive") and lc.get("streamId") else None


def open_streams():
    """Streams people can still join: active and not past their deactivation date."""
    on = today()
    return [s for s in Stream.objects.filter(is_active=True).order_by("start_date")
            if not s.is_past_deactivation(on)]


def join_stream(user, stream, role, invited_by=None):
    """Create or re-activate the membership of ``user`` in ``stream`` and keep the profile flags in sync."""
    m, _ = StreamMembership.objects.get_or_create(
        user=user, stream=stream, defaults={"role": role, "invited_by": invited_by})
    if m.status != "active" or m.role != role:
        m.status, m.role, m.deactivated_at = "active", role, None
        m.save(update_fields=["status", "role", "deactivated_at"])
    Profile.objects.filter(user=user).update(
        account_mode=IN_CAMP, in_camp_access_active=True, in_camp_deactivated_at=None)
    return m


def expire_memberships(on=None) -> dict:
    """Persist expiry for every membership whose stream is over; returns counts per role. Safe to run repeatedly."""
    from .notify import notify
    on = on or today()
    counts = {"corps_member": 0, "trainer": 0}
    due = (StreamMembership.objects.filter(status="active").select_related("stream", "user"))
    for m in due:
        if not m.stream.is_past_deactivation(on):
            continue
        m.status, m.deactivated_at = "expired", now()
        m.save(update_fields=["status", "deactivated_at"])
        counts[m.role] = counts.get(m.role, 0) + 1
        # If nothing else keeps this person active, switch the legacy profile flag off too.
        still_live = StreamMembership.objects.filter(user=m.user, status="active").exists()
        if not still_live:
            Profile.objects.filter(user=m.user).update(in_camp_access_active=False, in_camp_deactivated_at=now())
        notify(m.user, "Your In-Camp stream has ended",
               f"{m.stream.name} ended on {m.stream.end_date:%d %b %Y}, so your In-Camp account is now deactivated."
               + (" SAED admin can re-activate you for another stream." if m.role == "trainer" else ""),
               reason="stream_expired", email=False)
    return counts


def deactivation_label(stream):
    return (stream.end_date + timedelta(days=stream.deactivation_grace_days)).strftime("%d %b %Y")
