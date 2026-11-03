"""PayGuard -- pre-payment counterparty check for agents that pay via PayPal.

Phase 1: local stores (blocklist, payee directory, payment history) +
proposal-context signals, a transparent scoring service, and an enforcing
wrapper with a dry-run executor. No PayPal credentials, no network calls.
See DESIGN.md for the verified PayPal facts this is built on.
"""

__all__ = ["paypal_api", "store", "signals", "service", "wrapper", "cli"]
