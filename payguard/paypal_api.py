"""Verified PayPal API shapes. NO network code in phase 1.

Everything in this module was checked against official PayPal sources on
2026-11-03 (see DESIGN.md for the source table):

- Payouts API: POST {SANDBOX_BASE}/v1/payments/payouts creates a payout
  batch. Body: sender_batch_header{sender_batch_id, email_subject,
  recipient_type} + items[]{recipient_type EMAIL|PAYPAL_ID|PHONE,
  receiver, amount{value, currency}, note, sender_item_id,
  recipient_wallet PAYPAL|VENMO}. An UNCLAIMED item can be cancelled with
  POST /v1/payments/payouts-item/{payout_item_id}/cancel.
- Orders API v2: POST /v2/checkout/orders; purchase_units[].payee
  {email_address, merchant_id} is the merchant who receives the funds;
  capture = POST /v2/checkout/orders/{id}/capture.
- Identity: GET /v1/identity/openidconnect/userinfo returns claims for
  the user who authorized the app (scopes decide which) -- NOT a lookup
  for arbitrary payees.
- Agent Toolkit: tool list verified at developer.paypal.com/ai-tools/
  agent-tools -- it has order/invoice tools but NO payout tool, so
  disbursement executors call the Payouts REST API directly.
"""

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
LIVE_BASE = "https://api-m.paypal.com"

PAYOUTS_PATH = "/v1/payments/payouts"
PAYOUT_ITEM_PATH = "/v1/payments/payouts-item/{payout_item_id}"
PAYOUT_ITEM_CANCEL_PATH = "/v1/payments/payouts-item/{payout_item_id}/cancel"
ORDERS_PATH = "/v2/checkout/orders"
ORDER_CAPTURE_PATH = "/v2/checkout/orders/{order_id}/capture"
USERINFO_PATH = "/v1/identity/openidconnect/userinfo"

RECIPIENT_TYPES = ("EMAIL", "PAYPAL_ID", "PHONE")


def build_payout_request(intent, sender_batch_id):
    """Build the exact body POST /v1/payments/payouts would receive.

    `intent` is the wrapper's payment intent dict. This is a pure
    function: phase 1 uses it to show what WOULD be posted; phase 2's
    SandboxExecutor posts it to SANDBOX_BASE with an OAuth token.
    """
    if intent["recipient_type"] not in RECIPIENT_TYPES:
        raise ValueError(f"bad recipient_type: {intent['recipient_type']}")
    return {
        "sender_batch_header": {
            "sender_batch_id": sender_batch_id,
            "email_subject": "You have a payout",
            "recipient_type": intent["recipient_type"],
        },
        "items": [
            {
                "recipient_type": intent["recipient_type"],
                "receiver": intent["receiver"],
                "amount": {
                    "value": intent["amount"],
                    "currency": intent["currency"],
                },
                "note": intent.get("note", "Payment from an AI agent "
                                            "(checked by PayGuard)"),
                "sender_item_id": sender_batch_id + "-1",
                "recipient_wallet": "PAYPAL",
            }
        ],
    }
