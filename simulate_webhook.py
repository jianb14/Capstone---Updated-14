"""
Simulates a PayMongo 'checkout_session.payment.paid' webhook against the
local Django server (http://127.0.0.1:8000) using the real webhook secret
from .env — exactly how PayMongo signs its deliveries (t=<ts>,te=<hmac>).

Usage:  python simulate_webhook.py
"""
import hashlib
import hmac
import json
import os
import sys
import time

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Project.settings")
django.setup()

import requests  # noqa: E402
from django.conf import settings  # noqa: E402

from app.models import Payment  # noqa: E402


def main():
    payment = (
        Payment.objects.filter(
            payment_method__startswith="paymongo_",
            payment_status="pending",
        )
        .order_by("-id")
        .first()
    )
    if not payment:
        print("No pending PayMongo payment found — nothing to simulate.")
        sys.exit(1)

    cs_id = payment.paymongo_checkout_session_id
    pay_ref = payment.paymongo_payment_id
    print(f"Simulating webhook for Payment id={payment.id} (cs={cs_id}, pay={pay_ref})")

    payload = {
        "data": {
            "id": "evt_simulation",
            "type": "event",
            "attributes": {
                "type": "checkout_session.payment.paid",
                "data": {
                    "id": cs_id,
                    "type": "checkout_session",
                    "attributes": {
                        "payments": [{"id": pay_ref}] if pay_ref else [],
                    },
                },
            },
        }
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    ts = str(int(time.time()))
    secret = (settings.PAYMONGO_WEBHOOK_SECRET or "").encode("utf-8")
    if not secret:
        print("PAYMONGO_WEBHOOK_SECRET is empty — check .env")
        sys.exit(1)
    sig = hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    signature_header = f"t={ts},te={sig},li={sig}"

    resp = requests.post(
        "http://127.0.0.1:8000/api/paymongo/webhook/",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Paymongo-Signature": signature_header,
        },
        timeout=15,
    )
    print(f"HTTP {resp.status_code} {resp.text}")

    payment.refresh_from_db()
    print(f"notes            : {payment.notes!r}")
    print(f"paymongo_payment : {payment.paymongo_payment_id!r}")
    print(f"sender_name      : {payment.gcash_sender_name!r}")
    if "webhook" in (payment.notes or "").lower():
        print("RESULT: PASS — webhook handler updated the payment.")
    else:
        print("RESULT: FAIL — notes were not updated by the webhook handler.")


if __name__ == "__main__":
    main()
