"""Admin-configurable platform money settings (never hard-coded in business logic).

All values live in PlatformSetting so Dunis Admin can change them from the UI.
The constants below are only *first-run defaults* used when no row exists yet.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings

from ..models import PlatformSetting

DEFAULT_VIDEO_UPLOAD_FEE_NGN = 2000
DEFAULT_LESSON_PLATFORM_FEE_PERCENT = 10
KEY_VIDEO_FEE = "video_lesson_upload_fee"
KEY_LESSON_PCT = "lesson_platform_fee_percent"
KEY_ACTIVATION = "trainer_activation_fee"


def naira_to_kobo(value) -> int:
    """Decimal-safe NGN → kobo. Never goes through binary floats."""
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def kobo_to_naira(kobo) -> Decimal:
    return (Decimal(int(kobo or 0)) / 100).quantize(Decimal("0.01"))


def video_upload_fee() -> dict:
    cfg = PlatformSetting.get(KEY_VIDEO_FEE, None) or {}
    amount = cfg.get("amount", DEFAULT_VIDEO_UPLOAD_FEE_NGN)
    try:
        amount = Decimal(str(amount))
    except Exception:
        amount = Decimal(DEFAULT_VIDEO_UPLOAD_FEE_NGN)
    enabled = bool(cfg.get("enabled", True))
    kobo = naira_to_kobo(amount)
    return {
        "amount": amount, "amountKobo": kobo, "currency": "NGN", "enabled": enabled,
        # fee only applies when enabled AND positive
        "applies": enabled and kobo > 0,
    }


def lesson_platform_fee_percent() -> Decimal:
    raw = PlatformSetting.get(KEY_LESSON_PCT, DEFAULT_LESSON_PLATFORM_FEE_PERCENT)
    try:
        pct = Decimal(str(raw))
    except Exception:
        pct = Decimal(DEFAULT_LESSON_PLATFORM_FEE_PERCENT)
    return min(max(pct, Decimal(0)), Decimal(100))


def trainer_activation_fee_kobo() -> int:
    cfg = PlatformSetting.get(KEY_ACTIVATION, None)
    if isinstance(cfg, dict) and "amount" in cfg:
        return naira_to_kobo(cfg["amount"])
    return int(getattr(settings, "PAYSTACK_DEFAULT_AMOUNT", 50000))


def split_lesson_amount(amount_kobo: int):
    """→ (platform_fee_kobo, trainer_share_kobo); platform fee rounded half-up."""
    pct = lesson_platform_fee_percent()
    platform = int((Decimal(amount_kobo) * pct / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return platform, amount_kobo - platform
