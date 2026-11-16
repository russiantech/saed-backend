"""Thin, verified-TLS Paystack client + amount/signature helpers."""
import hashlib
import hmac
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class PaystackError(Exception):
    """Gateway unreachable / returned something we cannot interpret."""


class PaystackNotConfigured(PaystackError):
    pass


def secret_key() -> str:
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key:
        raise PaystackNotConfigured("Payment is not configured.")
    return key


def public_key() -> str:
    return getattr(settings, "PAYSTACK_PUBLIC_KEY", "") or ""


def request(method, path, *, json=None, params=None, timeout=30, retries=3):
    url = getattr(settings, "PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/") + path
    headers = {"Authorization": f"Bearer {secret_key()}", "Content-Type": "application/json"}
    last = None
    for attempt in range(retries):
        try:
            resp = requests.request(method, url, json=json, params=params, headers=headers, timeout=timeout)
            try:
                body = resp.json()
            except ValueError:
                raise PaystackError(f"Paystack returned non-JSON (HTTP {resp.status_code}).")
            if resp.status_code >= 500:
                raise PaystackError(f"Paystack HTTP {resp.status_code}")
            return body
        except (requests.ConnectionError, requests.Timeout, PaystackError) as exc:
            last = exc
            logger.warning("Paystack %s %s attempt %s failed: %s", method, path, attempt + 1, exc)
            if attempt < retries - 1:
                time.sleep(0.4 * (attempt + 1))
    raise PaystackError(f"Unable to reach Paystack: {last}")


# ── Transactions ─────────────────────────────────────────────────────────────
def initialize_transaction(*, email, amount_kobo, reference, callback_url, metadata,
                           subaccount="", transaction_charge_kobo=None):
    payload = {
        "email": email, "amount": int(amount_kobo), "currency": "NGN",
        "reference": reference, "callback_url": callback_url, "metadata": metadata,
    }
    if subaccount:
        payload["subaccount"] = subaccount
        if transaction_charge_kobo is not None:
            payload["transaction_charge"] = int(transaction_charge_kobo)
    return request("POST", "/transaction/initialize", json=payload)


def verify_transaction(reference):
    return request("GET", f"/transaction/verify/{reference}")


def refund_transaction(reference, amount_kobo=None, note=None):
    payload = {"transaction": reference}
    if amount_kobo:
        payload["amount"] = int(amount_kobo)
    if note:
        payload["customer_note"] = note
    return request("POST", "/refund", json=payload)


# ── Banks / subaccounts ──────────────────────────────────────────────────────
def list_banks():
    return request("GET", "/bank", params={"country": "nigeria", "perPage": 100, "currency": "NGN"})


def resolve_account(account_number, bank_code):
    return request("GET", "/bank/resolve", params={"account_number": account_number, "bank_code": bank_code})


def create_subaccount(*, business_name, bank_code, account_number, percentage_charge):
    return request("POST", "/subaccount", json={
        "business_name": business_name, "settlement_bank": bank_code,
        "account_number": account_number, "percentage_charge": float(percentage_charge),
    })


def update_subaccount(code, *, business_name, bank_code, account_number, percentage_charge):
    return request("PUT", f"/subaccount/{code}", json={
        "business_name": business_name, "settlement_bank": bank_code,
        "account_number": account_number, "percentage_charge": float(percentage_charge),
    })


# ── Verification helpers ─────────────────────────────────────────────────────
def check_amount(data: dict, expected_kobo: int):
    """Compare what the customer was *meant* to pay with what Paystack reports.

    Paystack's ``amount`` is the total charged in kobo and INCLUDES the processing
    fee when the merchant has "customer bears charges" enabled (that is how an
    expected 2,500,000 kobo shows up as 2,548,224). The merchant-requested value is
    ``requested_amount``. We therefore compare the requested amount EXACTLY.
    No percentage tolerance: a genuinely wrong amount must still be rejected.

    Returns (ok: bool, detail: dict).
    """
    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    paid = _int(data.get("amount")) or 0
    fees = _int(data.get("fees")) or 0
    requested = _int(data.get("requested_amount"))
    expected = int(expected_kobo)

    if requested:                       # authoritative when Paystack provides it
        ok = requested == expected and paid >= expected
    else:                               # older payloads: charged amount, optionally less fees
        ok = paid == expected or (fees > 0 and paid - fees == expected)
    detail = {"paidKobo": paid, "requestedKobo": requested, "feesKobo": fees, "expectedKobo": expected}
    return ok, detail


def verify_signature(body: bytes, signature: str) -> bool:
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key or not signature:
        return False
    computed = hmac.new(key.encode(), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)
