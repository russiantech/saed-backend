"""Trainer payout account: bank list, Paystack name resolution, verified save + subaccount."""
import re

from django.utils.timezone import now
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..services import config, paystack
from ..services.notify import notify
from .base import HasRole, IsAuthenticatedAPI, _log_error

ACCOUNT_RE = re.compile(r"^\d{10}$")


def _banks():
    body = paystack.list_banks()
    return [{"name": b.get("name"), "code": b.get("code"), "slug": b.get("slug")} for b in (body.get("data") or [])]


class ListPaystackBanksView(APIView):
    permission_classes = [IsAuthenticatedAPI]

    def get(self, request):
        try:
            return Response({"banks": _banks()})
        except paystack.PaystackNotConfigured:
            return Response({"banks": [], "error": "Payment is not configured."})
        except paystack.PaystackError as exc:
            _log_error("Paystack list banks error", exc=exc)
            return Response({"banks": [], "error": "Could not load banks."})


class ResolveBankAccountView(APIView):
    """POST {accountNumber, bankCode} → account holder name from Paystack."""
    permission_classes = [HasRole("trainer", "saed_admin", "dunis_admin")]

    def post(self, request):
        number = (request.data.get("accountNumber") or "").strip()
        code = (request.data.get("bankCode") or "").strip()
        if not ACCOUNT_RE.match(number) or not code:
            return Response({"error": "Enter a 10-digit account number and choose a bank.",
                             "fields": {"accountNumber": "Account number must be 10 digits."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            body = paystack.resolve_account(number, code)
        except paystack.PaystackNotConfigured:
            return Response({"error": "Payment is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except paystack.PaystackError as exc:
            _log_error("Paystack bank resolve error", exc=exc)
            return Response({"error": "Unable to verify account with Paystack."}, status=status.HTTP_502_BAD_GATEWAY)
        if not body.get("status"):
            return Response({"error": body.get("message") or "Could not resolve account."},
                            status=status.HTTP_400_BAD_REQUEST)
        data = body.get("data") or {}
        return Response({"ok": True, "accountNumber": data.get("account_number") or number,
                         "accountName": data.get("account_name") or ""})


class TrainerBankAccountView(APIView):
    """The trainer's payout account. Saving ALWAYS resolves the name through Paystack."""
    permission_classes = [HasRole("trainer")]

    def get(self, request):
        p = request.user.profile
        return Response({
            "bankName": p.bank_name, "bankCode": p.bank_code, "accountNumber": p.account_number,
            "accountName": p.account_name, "verified": p.bank_verified,
            "verifiedAt": p.bank_verified_at.isoformat() if p.bank_verified_at else None,
            "hasSubaccount": bool(p.paystack_subaccount_code),
            "platformFeePercent": float(config.lesson_platform_fee_percent()),
        })

    def put(self, request):
        number = (request.data.get("accountNumber") or "").strip()
        code = (request.data.get("bankCode") or "").strip()
        if not ACCOUNT_RE.match(number) or not code:
            return Response({"error": "Enter a 10-digit account number and choose a bank.",
                             "fields": {"accountNumber": "Account number must be 10 digits."}},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            body = paystack.resolve_account(number, code)
            if not body.get("status"):
                return Response({"error": body.get("message") or "Could not verify this account.",
                                 "fields": {"accountNumber": "Account could not be verified."}},
                                status=status.HTTP_400_BAD_REQUEST)
            account_name = (body.get("data") or {}).get("account_name") or ""
            bank_name = (request.data.get("bankName") or "").strip()
            try:
                bank_name = next((b["name"] for b in _banks() if b["code"] == code), bank_name)
            except paystack.PaystackError:
                pass
        except paystack.PaystackNotConfigured:
            return Response({"error": "Payment is not configured."}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except paystack.PaystackError as exc:
            _log_error("Trainer bank verify error", exc=exc)
            return Response({"error": "Unable to verify account with Paystack. Please retry."},
                            status=status.HTTP_502_BAD_GATEWAY)

        p = request.user.profile
        business = (p.company_name or request.user.get_full_name() or request.user.email)[:100]
        pct = config.lesson_platform_fee_percent()
        warning = ""
        sub_code = p.paystack_subaccount_code
        try:
            args = dict(business_name=business, bank_code=code, account_number=number, percentage_charge=pct)
            res = paystack.update_subaccount(sub_code, **args) if sub_code else paystack.create_subaccount(**args)
            if res.get("status"):
                sub_code = (res.get("data") or {}).get("subaccount_code") or sub_code
            else:
                warning = res.get("message") or "Payout split could not be set up yet."
        except paystack.PaystackError:
            warning = "Account verified, but the automatic payout split could not be set up yet."

        p.bank_name, p.bank_code, p.account_number, p.account_name = bank_name, code, number, account_name
        p.paystack_subaccount_code = sub_code or ""
        p.bank_verified, p.bank_verified_at = True, now()
        p.save()
        notify(request.user, "Payout account verified",
               f"{account_name} · {bank_name} ••••{number[-4:]} is verified for earnings.",
               reason="bank_verified", link="/app/earnings", email=False)
        return Response({"ok": True, "accountName": account_name, "bankName": bank_name, "verified": True,
                         "hasSubaccount": bool(p.paystack_subaccount_code), "warning": warning})
