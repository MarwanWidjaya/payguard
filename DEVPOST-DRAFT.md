# Devpost submission draft — PayGuard

DRAFT for Marwan's review and approval. Not submitted. Placeholders in
[brackets] are filled at submission time.

---

**Project name:** PayGuard

**Tagline:** A pre-payment counterparty check for AI agents that pay
via PayPal: allow, warn, or block — with reasons — before any money
moves.

**Target category:** Best Use of Agentic Commerce
(also eligible for Best Overall and Best Use of PayPal + AI)

**Team:** Marwan Widjaya (solo)

**Repository:** [REPO_URL]

**Demo video:** [YOUTUBE_URL] (62-second terminal capture of real
runs; also in the repository as `demo-video.mp4`)

---

## Description

### The problem

An AI agent equipped with PayPal's Agent Toolkit, the PayPal MCP
server, or direct Payouts API access will pay whoever its context
tells it to pay. That context can be poisoned: a document, email, or
tool result read during a legitimate task can contain an injected
instruction that redirects a payment to an attacker's account and
asserts that verification has already been done. The model cannot
reliably separate an injected instruction from a genuine one, so the
decision to pay cannot rest on the prompt — and no layer of the agent
stack independently checks whether the payee should be paid at all.

### What PayGuard does

PayGuard is a check service plus an enforcing wrapper that sits
between the agent and every money-moving call. For each proposed
payment it scores the payee and returns **allow / warn / block** with
a reason for every point:

- **block** — the payment is refused; the executor is never invoked.
- **warn** — the payment pauses for a human decision.
- **allow** — the payment proceeds to the executor.

The executor is only reachable through the wrapper, and the wrapper
only calls it on `allow`. In the recorded injection demo, a poisoned
"vendor changed their PayPal email" notice directs the agent to pay a
real invoice to a blocklisted address: the payment is refused and the
executor's invocation count stays at 0.

### How it works

Nine signals, each computed from data that actually exists on PayPal
rails — the proposal itself and the operator's own records:

- blocklist membership (any identifier; entries require evidence)
- known-payee identifier binding (email / phone / Payer ID) from the
  operator's own directory
- identifier drift — a known Payer ID presented with a new email, or a
  known email with a different Payer ID
- prior interactions and relationship age from payment history
- amount anomaly against the payee's historical maximum
- velocity (payments to this payee in 24 h; agent outflow in 1 h)
- lookalike email domains (edit distance 1–2, labeled heuristic)
- invoice / order context cross-check: the document the payment
  claims to settle must name the proposed receiver
- payee verification status, only when a past `userinfo` capture
  actually recorded it

Two hard overrides block regardless of score: a blocklist match, and
an invoice/order whose recipient does not match the proposed
receiver. Point scores map to verdicts at ≥50 block, 25–49 warn,
<25 allow. Every point is returned in the verdict's `reasons`, so a
decision can be audited from the log alone.

Recorded runs in the repository: blocklisted payee → block, score
100; brand-new payee → warn, score 30; established vendor → allow,
score 0; injection demo → refused before the executor ran.

### What is new here (meaningful advancement)

PayGuard was built in this hackathon window as a new project. It
reuses the check-service-plus-wrapper architecture of the author's
earlier NEAR Hackathon entry (NearGuard) and nothing else, because
the rails differ at the foundation: NEAR exposes public reads about
any account, and PayPal does not. Every signal was re-derived from
what PayPal actually offers — identifier binding and drift across a
payee's email / phone / Payer ID, invoice and order context
cross-checks, payment velocity, and amount-versus-history anomaly are
new. The executor is new: a builder for the verified Payouts API
request shape behind a dry-run executor. The attack demo is new and
PayPal-native (a redirected vendor payment against a real invoice,
not a wallet-address swap).

### The honest limit, stated in the design

PayPal offers no lookup of an arbitrary payee's trust attributes:
`userinfo` returns the profile of the user who authorized your app,
not of a stranger you are about to pay. PayGuard never claims to
verify a payee "at PayPal". It checks the proposal's identifiers, the
operator's own records, and the documents the payment claims to
settle — and where a signal would need data only PayPal holds, the
design documents that instead of inventing an endpoint. DESIGN.md in
the repository carries the full source table (every API fact verified
against developer.paypal.com on 2026-11-03) and the open
TODO-VERIFY items.

### Current state

The submitted build runs on sandbox-shaped fixtures with a dry-run
executor: it builds the exact `POST /v1/payments/payouts` body and
sends nothing, so the demo is fully reproducible from the repository
with no credentials. The sandbox executor is an interface stub behind
the same wrapper, ready to be wired with sandbox credentials.

## Built with

- Python 3 (standard library only — no third-party dependencies)
- PayPal Payouts API (request shapes), Orders API v2 and Identity /
  `userinfo` (data-source design), PayPal Agent Toolkit and MCP
  server (integration surface the wrapper is designed to sit in
  front of)

## AI disclosure

This project was built with AI assistance — Muse (Meta AI
assistant) — disclosed here and in the repository per the hackathon
rules.

## Try it

```sh
python3 -m venv .venv
.venv/bin/python -m payguard.cli check quick-settle@billing-example.net --amount 250.00   # block, 100
.venv/bin/python -m payguard.cli check sb-newshop9@personal.example.com --amount 75.00    # warn, 30
.venv/bin/python -m payguard.cli check sb-vendor42@business.example.com --amount 120.00   # allow, 0
.venv/bin/python demo_attack.py                                                          # injection refused
```
