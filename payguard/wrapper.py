"""Agent-side wrapper: the enforcement point between an agent and PayPal.

The agent (or a prompt-injected instruction inside it) proposes a payment;
the wrapper asks the check service first and enforces the verdict:

  block -> refused. The executor is never invoked.
  warn  -> paused. "NEEDS HUMAN" is printed with the reasons.
  allow -> handed to the executor.

Phase 1 ships only DryRunExecutor: it builds the exact Payouts API
request body (see payguard.paypal_api) and sends nothing -- there are no
credentials in phase 1 by design. SandboxExecutor is the phase-2 seam:
it will POST that body to the PayPal sandbox with Marwan's sandbox app
credentials, supplied via the secure vault, never via this repo.
"""

import itertools
import json

from . import paypal_api, service, store

_batch_counter = itertools.count(1)


class DryRunExecutor:
    """Stands in for the Payouts API call; builds the request, sends 0."""

    def __init__(self):
        self.calls = 0

    def execute(self, intent):
        self.calls += 1
        batch_id = f"PAYGUARD-DRYRUN-{next(_batch_counter):04d}"
        body = paypal_api.build_payout_request(intent, batch_id)
        return {"status": "dry_run_ready",
                "would_post": {"method": "POST",
                               "url": paypal_api.SANDBOX_BASE
                                      + paypal_api.PAYOUTS_PATH,
                               "body": body},
                "note": "phase 1: no credentials, nothing was sent"}


class SandboxExecutor:
    """Phase-2 placeholder. Will POST to the PayPal sandbox.

    Deliberately unimplemented: it needs Marwan's sandbox app credentials
    (client ID + secret) from the PayPal Developer Dashboard, handed over
    via the secure vault -- a human step outside phase 1's scope.
    """

    def execute(self, intent):
        raise NotImplementedError(
            "phase 2: POST the payout to api-m.sandbox.paypal.com with "
            "sandbox app credentials from the secure vault")


def receiver_of(payee, recipient_type):
    """The `receiver` string a Payouts item would carry for this payee."""
    if recipient_type == "EMAIL":
        return payee.get("email")
    if recipient_type == "PAYPAL_ID":
        return payee.get("payer_id")
    if recipient_type == "PHONE":
        return payee.get("phone")
    return None


def propose_payment(agent_id, payee, amount, currency="USD",
                    recipient_type="EMAIL", context=None, executor=None,
                    log=print):
    """Run one proposed payment through the guard. Returns a result dict.

    payee: dict with any of {email, payer_id, phone}.
    """
    executor = executor or DryRunExecutor()
    receiver = receiver_of(payee, recipient_type)
    intent = {"agent": agent_id, "payee": payee, "receiver": receiver,
              "amount": str(amount), "currency": currency,
              "recipient_type": recipient_type, "context": context or {}}
    log(f"[wrapper] proposed payment: {json.dumps(intent)}")
    if receiver is None:
        log("[wrapper] REFUSED -- no receiver identifier for "
            f"recipient_type {recipient_type}")
        return {"status": "refused", "intent": intent,
                "check": {"verdict": "block", "score": 100,
                          "reasons": ["no receiver identifier for the "
                                      "requested recipient_type"]}}

    result = service.check(agent_id, payee, amount, context)
    log(f"[guard] verdict={result['verdict']} score={result['score']} "
        f"reasons={result['reasons']}")

    if result["verdict"] == "block":
        log("[wrapper] REFUSED -- executor never invoked")
        return {"status": "refused", "intent": intent, "check": result}
    if result["verdict"] == "warn":
        log("[wrapper] NEEDS HUMAN -- paused, nothing executed")
        return {"status": "needs_human", "intent": intent, "check": result}

    executed = executor.execute(intent)
    canonical = result["signals"]["canonical_id"]
    store.record_interaction(agent_id, canonical, amount)
    log(f"[wrapper] allowed -> executor: {executed['status']}")
    return {"status": executed["status"], "intent": intent,
            "check": result, "executor_result": executed}
