# PayGuard — Pre-Payment Counterparty Check for PayPal-Paying Agents

**PayPal AI Hackathon "Build What's Next with PayPal and AI" (Devpost) —
target category: Best Use of Agentic Commerce ($5,000).**
Deadline: 2026-11-12 20:00 UTC. Phase 1 design + build. Local only:
no accounts, no credentials, no network calls to PayPal, nothing published.

## Problem

An AI agent that can move money through PayPal — via PayPal's own Agent
Toolkit / MCP server, or by calling the Payouts API — will pay whoever its
prompt tells it to pay, including a prompt-injected instruction buried in a
document, email, or tool result that redirects a payment to an attacker's
account and says "skip verification." PayPal's own agent tooling executes
what the model decides; nothing in the stack independently answers the
question: *is this payee safe to pay, right now, for this amount, in this
context?*

PayGuard is that second opinion. An agent-side wrapper intercepts every
proposed PayPal payment **before** any money-moving call, the check service
scores the payee from data that actually exists on PayPal rails, and the
wrapper enforces the verdict: `allow` / `warn` / `block`, with a reason for
every point.

## Why this is not just "NearGuard with a new logo"

PayGuard is a new build in this hackathon window. It reuses NearGuard's
*architecture* (check service + enforcing wrapper + transparent scoring) —
and nothing else, because the rails are fundamentally different:

- **New rails.** NEAR exposed public, permissionless reads about any
  account. PayPal does not (see the no-analogue table below). Every signal
  had to be re-derived from what PayPal actually offers: the payment
  request itself, the operator's own records, and document context
  (invoices / orders).
- **New signal family.** Identifier binding & drift (a PayPal payee can be
  addressed by email, phone, or Payer ID — redirection attacks live in the
  gaps between those), invoice/order context cross-checks, payment
  velocity, and amount-vs-history anomaly. None of these existed in
  NearGuard.
- **New executor design.** A Payouts API request builder producing the
  exact verified request shape, behind a dry-run executor (phase 1) and a
  sandbox executor interface (phase 2).
- **New fixtures and demo.** A PayPal-native attack story (a poisoned
  "vendor changed their PayPal email" notice referencing a real invoice)
  instead of a wallet-address swap.

AI assistance (Muse, Meta AI assistant) was used in development and is
disclosed here per the hackathon rules.

## Verified PayPal facts this design stands on

All verified 2026-11-03 against official PayPal sources (developer.paypal.com,
PayPal's official API references). Nothing below is assumed.

| Fact | Source |
|---|---|
| **Agent Toolkit exists**, Python package `paypal-agent-toolkit` (+ TS `@paypal/agent-toolkit`), frameworks: MCP, LangChain, CrewAI, OpenAI Agents SDK, Bedrock, Vercel AI SDK. Config pattern: `PayPalToolkit(client_id, secret, Configuration(actions={...}, Context(sandbox=True)))`. | developer.paypal.com/ai-tools/toolkit |
| **Toolkit tool list** (orders `create_order`/`get_order`/`pay_order` = capture, invoices `create_invoice`/`get_invoice`/`send_invoice`/…, products, disputes, subscriptions, `list_transaction`, `get_merchant_insights`, shipment tracking). **There is NO payout tool in the toolkit** as of 2026-11-03 — agents disburse via the Payouts REST API directly, and pay for commerce via order capture. | developer.paypal.com/ai-tools/agent-tools |
| **MCP server exists**: local `npx -y @paypal/mcp --tools=all` (env `PAYPAL_ACCESS_TOKEN`, `PAYPAL_ENVIRONMENT`), and remote hosted endpoints `https://mcp.sandbox.paypal.com` / `https://mcp.paypal.com`. | developer.paypal.com/ai-tools/mcp-server |
| **Payouts API**: `POST https://api-m.sandbox.paypal.com/v1/payments/payouts`. Body: `sender_batch_header{sender_batch_id, email_subject, recipient_type}`, `items[]{recipient_type: EMAIL\|PAYPAL_ID\|PHONE, receiver, amount{value, currency}, note, sender_item_id, recipient_wallet: PAYPAL\|VENMO}`. Also `GET /v1/payments/payouts/{id}`, `GET /v1/payments/payouts-item/{id}`, `POST /v1/payments/payouts-item/{id}/cancel` (cancels an UNCLAIMED item). `PayPal-Request-Id` header gives idempotency; documented rate limit 400 POST/min. | developer.paypal.com/api/payouts and the Payouts integration guide |
| **Orders API v2**: `POST /v2/checkout/orders` (sandbox base `api-m.sandbox.paypal.com`); each `purchase_units[]` carries a `payee` — "the merchant who receives the funds" — identified by `email_address` and/or `merchant_id`; capture is `POST /v2/checkout/orders/{id}/capture`; order details expose the `payer` object with `payer_id` + `email_address`. | developer.paypal.com/api/orders/v2 (+ Orders server-SDK model docs) |
| **Identity / userinfo**: `GET /v1/identity/openidconnect/userinfo` returns claims that depend on the scopes the user granted: `profile` → name, `email` → email, `https://uri.paypal.com/services/paypalattributes` → `payer_id` + account verification status; response fields include `verified_account`, `email_verified`, `account_type`. | developer.paypal.com/api/identity/v1, Log in with PayPal reference |
| **Sandbox accounts**: the Developer Dashboard auto-creates a default personal + business account; more can be created under Testing Tools → Sandbox Accounts. Emails follow `sb-[random]@personal.example.com` / `sb-[random]@business.example.com`; every sandbox account has a Payer ID; balance/cards are configurable. | developer.paypal.com/sandbox-testing/accounts |

### The hard limit that shapes the whole design

**PayPal offers no lookup of an arbitrary payee's trust attributes.**
`userinfo` returns the profile of *the user who authorized your app* via
Log in with PayPal — not of a stranger you are about to pay. There is no
official endpoint that takes an email or Payer ID and returns that account's
age, verification status, or history. PayGuard therefore never pretends to
"check the payee at PayPal": it checks (a) the payment request's own
identifiers, (b) the operator's own records about that payee, and (c) the
documents the payment claims to settle. Where a signal needs data only
PayPal holds, the design says so (TODO-VERIFY) instead of inventing it.

## Architecture

```
        proposed payment (payee identifiers, amount, currency,
                          recipient_type, optional invoice/order ref)
                            │
                ┌───────────▼───────────┐
                │   agent wrapper       │  refuses on block, pauses on warn
                │   (payguard.wrapper)  │
                └───────────┬───────────┘
                            │ check(agent, payee, amount, context)
                ┌───────────▼───────────┐
                │   check service       │  scoring -> verdict + reasons
                │   (payguard.service)  │
                └─────┬───────────┬─────┘
                      │           │
        ┌─────────────▼──┐   ┌────▼──────────────────────┐
        │ local stores   │   │ proposal context          │
        │ (payguard.     │   │ (payguard.signals)        │
        │  store)        │   │ - identifiers presented   │
        │ - blocklist    │   │ - invoice fixture/API doc │
        │ - payee        │   │ - amount & velocity math  │
        │   directory    │   └───────────────────────────┘
        │ - history      │
        └────────────────┘
        allow only ──► executor (payguard.wrapper):
                       phase 1 DryRunExecutor (builds the exact
                       Payouts API request body, sends nothing);
                       phase 2 SandboxExecutor (real sandbox POST).
```

Components (all in `payguard/`):

| File | Role |
|---|---|
| `paypal_api.py` | Verified PayPal API shapes: sandbox base URL, the Payouts request builder, endpoint inventory with sources. No network code in phase 1. |
| `store.py` | Local JSON stores: shared blocklist, payee directory (identifier bindings from our own records), per-agent payment history + event log. Dir override: `PAYGUARD_DATA`. |
| `signals.py` | Collects the signal set for one proposed payment. |
| `service.py` | Scoring rules -> verdict dict `{verdict, score, reasons, signals}`. |
| `wrapper.py` | Agent-side enforcement: `propose_payment(...)` + executors. |
| `cli.py` | `check <payee>` and `report <payee>` commands. |

## Signals and their data sources

Every signal below is computed from data that exists: the proposal itself,
or local stores whose contents come from the operator's own PayPal activity
(sandbox fixtures in phase 1, shaped exactly like the real records).

| # | Signal | Source | How it is read |
|---|---|---|---|
| P1 | Blocklist membership | Local `data/blocklist.json` | Match on **any** identifier of the payee (email / phone / Payer ID, presented or known). Entries require evidence. |
| P2 | Known payee + identifier binding | Local `data/directory.json` | Our own record of a payee: `{payer_id, emails[], phones[], account_type, verified_account, email_verified, first_seen, display_name}` — populated from past payments and, when a payee has authenticated to us, from `userinfo` claims (verified fields above). |
| P3 | Identifier drift | Proposal vs P2 | Payee resolved by one identifier, but a second presented identifier contradicts the binding: known Payer ID with a **new email**, or known email with a **different Payer ID**. The classic "vendor changed their email" redirection tell. |
| P4 | Prior interactions / relationship age | Local `data/history.json` | Per (agent, payee): `{count, total_usd, max_usd, first, last, events[]}`. No entry = first interaction. Age = days since `first`. In phase 2 this store is seeded from the operator's own transaction list (toolkit `list_transaction` — own-account data, which PayPal does expose). |
| P5 | Amount anomaly | Proposal vs P4 | Amount compared to this payee's historical max/typical amounts. |
| P6 | Velocity | P4 event log | Payments to this payee (count + total) in the last 24 h; agent-wide outflow in the last 1 h. |
| P7 | Lookalike identifier | Proposal vs P2 domains | Payee email domain within edit distance 1–2 of a known payee's domain, but not equal to it (local string math, labeled heuristic). |
| P8 | Invoice / order context cross-check | Proposal context vs document | If the proposal claims to settle invoice `INV-…`, the document's recipient (invoicing `create_invoice` takes `recipient_email`; orders carry `purchase_units[].payee`) must match the proposed receiver. Fixture documents in phase 1 (`data/invoices.json`, shaped like the API objects); real `get_invoice` / `get_order` calls in phase 2. |
| P9 | Payee verification status | P2 (only when actually known) | `verified_account` from a past `userinfo` capture. **Unknown for strangers — absence scores nothing.** |

### NearGuard signals with NO PayPal analogue (honest mapping)

| NearGuard signal | PayPal analogue | Replacement in PayGuard |
|---|---|---|
| Receiver account exists (`view_account`) | **None.** No pre-payment existence lookup for an arbitrary identifier. (Post-send, a payout to a nonexistent email sits `UNCLAIMED` and can be cancelled via `POST /v1/payments/payouts-item/{id}/cancel` — mitigation, not a pre-check.) | Unverifiable-identity handling: a payee with no directory binding scores points (P2-absent) instead of a hard block; first-interaction and context signals carry the risk. |
| Receiver is a contract (`view_code`) | **None** — PayPal accounts are not code-bearing. | Payee `account_type` (PERSONAL vs BUSINESS) when known via P2; scores nothing when unknown. |
| Contract code changed recently | **None.** | **Identifier drift (P3)** — the PayPal-native "the counterparty's payment identity just changed" risk. |
| Account age (archival ladder) | **None** — no public account-age data. | **Relationship age (P4)**: how long *we* have known and paid this payee — the only age an operator can actually verify. |
| Receiver balance / storage | **None** — a payee's balance is never visible. | **Amount-based signals (P5/P6)**: the risk lives in the amount pattern, not the payee's wallet. |

## Scoring → verdict

Hard overrides (verdict `block` regardless of score):

- P1: payee matches the blocklist on any identifier → **block**.
- P8: proposal references an invoice/order whose payee does **not** match
  the proposed receiver → **block** (the payment is not settling the
  document it claims to settle).

Points (only when the hard overrides don't fire):

| Signal | Condition | Points |
|---|---|---|
| P3 | Identifier drift for a known payee | +40 |
| P7 | Lookalike email domain of a known payee | +35 |
| P5 | Amount > 3× this payee's historical max | +25 |
| P4 | First interaction between this agent and payee | +20 |
| P6 | ≥3 payments to this payee in the last 24 h | +20 |
| P2/P9 | Payee identity not verifiable (no directory binding exists) | +10 |
| P4 | Relationship younger than 30 days (but not first interaction) | +15 |
| P9 | Payee known and `verified_account` is false | +20 |
| P5/P6 | Amount above the agent's soft cap ($500 default, policy config) | +15 |

Verdict thresholds: **score ≥ 50 → block · 25–49 → warn · < 25 → allow.**
Every point is returned in `reasons`, so the decision can be audited from
the log alone. Worked examples (all reproduced in `runs/`):

- Blocklisted drainer fixture → hard block, score 100.
- Brand-new payee, first interaction: 20 (first) + 10 (unverifiable) = 30 → `warn`.
- Established vendor from history, normal amount: 0 → `allow`.

## Wrapper flow (`wrapper.propose_payment`)

1. Build the intent `{agent, payee, identifiers, amount, currency,
   recipient_type, context}`.
2. Call the check service. Log the full verdict.
3. `block` → **refused**: return `{"status": "refused", ...}`. The executor
   is never invoked — this is what stops the injected payment. (Verified by
   a spy executor in `demo_attack.py`: invocation count stays 0.)
4. `warn` → **paused**: print `NEEDS HUMAN` with the reasons, return
   `{"status": "needs_human", ...}`. Nothing is executed until a human
   approves out-of-band (phase 2: approval callback).
5. `allow` → hand the intent to the executor. Phase 1 ships only
   `DryRunExecutor`: it builds the exact Payouts API request body
   (`paypal_api.build_payout_request`) and returns it as `would_post` —
   sends nothing, needs no credentials. `SandboxExecutor` is an interface
   stub that raises `NotImplementedError` until phase 2 wires it with
   sandbox credentials supplied by Marwan via the secure vault.

Safety property, stated plainly: the executor is only reachable through
the wrapper, and the wrapper only calls it on `allow`. A prompt — injected
or not — cannot reach the Payouts API without passing the check.

## Attack demo (`demo_attack.py`)

PayPal-native version of the injection scenario:

1. The agent processes vendor paperwork. A poisoned notice claims the
   vendor "changed their PayPal email" to a drainer address, demands
   payment of a real invoice amount, and says verification was already
   done. The wrapper is asked to pay the drainer *for that invoice* →
   blocklist fires **and** the invoice's real recipient doesn't match →
   refused, executor never invoked.
2. Same agent, brand-new payee (sandbox-shaped personal account) →
   `warn`, NEEDS HUMAN.
3. Same agent pays the established vendor the invoice actually names,
   normal amount → `allow`, dry-run executor produces the exact Payouts
   request body that phase 2 would POST.

## What runs where

| Piece | Runs |
|---|---|
| Check service, wrapper, CLI, demo | Local (this repo, Python ≥3.11, **stdlib only**) |
| All signals | Local stores + proposal context (fixtures in phase 1) |
| Any PayPal API call / credential | **Nowhere in phase 1** (dry-run executor only) |
| Phase-2 sandbox run | PayPal Sandbox (`api-m.sandbox.paypal.com`) with Marwan's sandbox app credentials |

## Endgame — human steps (Marwan only, in order)

1. **Devpost**: join "Build What's Next with PayPal and AI" and submit the
   project under his own account before **2026-11-12 20:00 UTC** (repo URL,
   demo video link, category: Best Use of Agentic Commerce; disclose AI
   assistance — Muse — in the submission form).
2. **PayPal Developer Dashboard**: create a REST app (sandbox), note the
   client ID + secret, and hand them over **via the secure vault** — never
   in chat, never in the repo. Sandbox accounts: the dashboard's default
   business + personal accounts are enough for phase 2; a fresh sandbox
   business account can play the "vendor", a personal one the "new payee".
3. **Phase 2 (Zaro, after step 2)**: wire `SandboxExecutor`, re-run the
   demo against real sandbox payouts, confirm the UNCLAIMED/cancel
   behavior, seed history from `list_transaction`.
4. **YouTube**: upload the demo video (<3 min, recorded from the real
   phase-2 runs — real captures only) on his channel; the link goes into
   the Devpost submission.
5. **Repo**: publish this project as a public repo with the MIT LICENSE
   included here, after his explicit go.

## Phase-2 TODOs / TODO-VERIFY (explicit, not silently dropped)

- TODO-VERIFY: exact filter fields of the Transaction Search API
  (`GET /v1/reporting/transactions`) for counterparty identifiers — the
  toolkit's `list_transaction` tool is verified to exist; the raw API's
  payee-filter semantics were not read in phase 1.
- TODO-VERIFY: payout webhook event names for post-send monitoring
  (item claimed/unclaimed/blocked) before relying on them.
- TODO-VERIFY: whether Payouts has any pre-flight receiver validation
  beyond what the payouts docs read in phase 1 show (none found there;
  UNCLAIMED + cancel is the documented mitigation).
- TODO: re-check the agent tools reference at phase 2 — the toolkit is
  actively extended (Jun 2025 added refund/subscription tools); a payout
  tool may appear, which would add a second executor path.
- TODO: `warn` approval callback (human approves → one-time release token).
- TODO: orders-path executor (guard in front of toolkit `pay_order` /
  capture) alongside the payouts path.
- TODO: multi-currency amount history (phase 1 fixtures are USD-only;
  history totals are tracked per payee in USD).
