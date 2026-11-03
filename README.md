# PayGuard

A pre-payment counterparty check for AI agents that pay via PayPal.

PayGuard sits between an agent and the money-moving call. Before any
payment executes, the proposed payee is scored and the check returns
**allow / warn / block**, with a reason for every point. An agent-side
wrapper enforces the verdict: on `block` the payment call is never
made, on `warn` the payment pauses for a human decision, on `allow` it
proceeds.

Built for the PayPal AI Hackathon ("Build What's Next with PayPal and
AI"). Target category: **Best Use of Agentic Commerce**.

## The problem

An AI agent equipped with PayPal's Agent Toolkit, the PayPal MCP
server, or direct Payouts API access will pay whoever its context tells
it to pay. That context can be poisoned: a document, email, or tool
result the agent reads during a legitimate task can contain an injected
instruction that redirects a payment to an attacker's account and
asserts that verification has already been done. The model cannot
reliably distinguish an injected instruction from a genuine one, so the
payment decision cannot rest on the prompt — and nothing in the agent
stack independently answers the question *is this payee safe to pay,
right now, for this amount, in this context?*

PayGuard is that independent check. The executor is only reachable
through the wrapper, and the wrapper only calls it on `allow`. In the
injection demo below, the executor's invocation count for the blocked
payment stays at 0.

## How it works

```
proposed payment (payee identifiers, amount, currency, invoice ref)
        │
  agent wrapper ──► check service ──► verdict + reasons
        │           (scoring over: blocklist, payee directory,
        │            payment history, proposal context)
        └── block: refuse · warn: pause for human · allow: execute
```

| Component | Role |
|---|---|
| `payguard/paypal_api.py` | Verified PayPal API shapes: sandbox base URL, the Payouts request builder, endpoint inventory with sources. |
| `payguard/store.py` | Local JSON stores: shared blocklist, payee directory, per-agent payment history. |
| `payguard/signals.py` | Collects the signal set for one proposed payment. |
| `payguard/service.py` | Scoring rules → `{verdict, score, reasons, signals}`. |
| `payguard/wrapper.py` | Enforcement (`propose_payment`) and executors. |
| `payguard/cli.py` | `check` and `report` commands. |
| `demo_attack.py` | Prompt-injection demo on PayPal rails. |

### Signals

Every signal is computed from data that exists: the payment proposal
itself, or the operator's own records. Sources were verified against
official PayPal documentation on 2026-11-03; the full source table is
in [DESIGN.md](DESIGN.md).

| Signal | Data source |
|---|---|
| Blocklist membership | Local blocklist; match on any payee identifier. Entries require evidence. |
| Known payee + identifier binding | Local payee directory: the operator's own record binding a payee's email / phone / Payer ID, from past payments and past `userinfo` captures. |
| Identifier drift | Proposal vs directory: a known Payer ID presented with a new email, or a known email with a different Payer ID — the standard "vendor changed their PayPal email" redirection tell. |
| Prior interactions / relationship age | Local per-(agent, payee) history. |
| Amount anomaly | Proposal vs this payee's historical maximum. |
| Velocity | History event log: payments to this payee in 24 h, agent outflow in 1 h. |
| Lookalike identifier | Email domain within edit distance 1–2 of a known payee's domain (heuristic, labeled as such). |
| Invoice / order context | The document the payment claims to settle (invoicing / Orders API shapes); its recipient must match the proposed receiver. |
| Payee verification status | Directory only, when a past `userinfo` capture actually recorded it. Absence scores nothing. |

### Scoring

Hard overrides — verdict `block` regardless of score:

- The payee matches the blocklist on any identifier.
- The proposal references an invoice or order whose recipient does not
  match the proposed receiver.

Points (selected): identifier drift +40 · lookalike domain +35 ·
amount > 3× the payee's historical maximum +25 · first interaction
+20 · ≥3 payments to this payee in 24 h +20 · payee known and
`verified_account` is false +20 · relationship younger than 30 days
+15 · amount above the agent's soft cap ($500 default) +15 · payee
identity not verifiable (no directory binding) +10.

Thresholds: **≥50 block · 25–49 warn · <25 allow.** Every point is
listed in `reasons`, so a decision can be audited from the output alone.

## Setup

Python ≥ 3.11. Standard library only — there is nothing to install.

```sh
python3 -m venv .venv
.venv/bin/python -m payguard.cli check quick-settle@billing-example.net --amount 250.00
.venv/bin/python -m payguard.cli check sb-newshop9@personal.example.com --amount 75.00
.venv/bin/python -m payguard.cli check sb-vendor42@business.example.com --amount 120.00
.venv/bin/python demo_attack.py
```

This build evaluates against the fixture stores in `data/`
(sandbox-shaped payees, labeled as fixtures) and ships a dry-run
executor: it builds the exact Payouts API request body and sends
nothing. No PayPal credentials are used, and no network calls are made.
Recorded outputs of these commands are in `runs/` and `runs/phase2/`.

## Demo scenarios and expected outputs

1. **Blocklisted payee** — `check quick-settle@billing-example.net
   --amount 250.00` → `block`, score 100 (blocklist hard override; the
   entry is a labeled fixture).
2. **Brand-new payee** — `check sb-newshop9@personal.example.com
   --amount 75.00` → `warn`, score 30 (first interaction +20, identity
   not verifiable +10).
3. **Established vendor** — `check sb-vendor42@business.example.com
   --amount 120.00` → `allow`, score 0 (no signals fired).
4. **Prompt injection** — `demo_attack.py`: a poisoned "vendor changed
   their PayPal email" notice directs the agent to pay invoice
   INV-2026-1001 to the blocklisted address → **refused, executor
   invoked 0 times** (the invoice's real recipient also fails to
   match). The same agent then hits `warn` on a new payee, and `allow`
   on the payment the invoice actually names; the dry-run executor
   produces the `POST /v1/payments/payouts` body for it.

A 62-second terminal video of these runs is in
[demo-video.mp4](demo-video.mp4) (real captured output; playback
timing compressed, as captioned in the video).

## Limitations

- **PayPal exposes no trust lookup for an arbitrary payee.** The
  `userinfo` endpoint returns the profile of the user who authorized
  your app — not of a stranger you are about to pay. There is no
  official endpoint that returns another account's age, verification
  status, or history. PayGuard therefore checks the proposal's
  identifiers, the operator's own records, and the documents the
  payment claims to settle, and says so rather than pretending to
  verify a payee "at PayPal".
- Signals that exist on public-chain rails have no PayPal analogue
  (counterparty account age, code/contract state, balance). DESIGN.md
  maps each one to its PayGuard replacement or states that none
  exists.
- This build runs on fixtures with a dry-run executor. The sandbox
  executor is an interface stub: it raises `NotImplementedError` until
  it is wired with sandbox credentials. A payout to a nonexistent
  address can only be mitigated after the fact (it sits `UNCLAIMED`
  and can be cancelled) — documented in DESIGN.md, not hidden.
- History totals are USD-only in this build; the lookalike-domain
  signal is a string-distance heuristic.

## Repository layout

- `payguard/` — the package (see the component table above)
- `data/` — fixture stores (blocklist, directory, history, invoices)
- `runs/`, `runs/phase2/` — recorded smoke-run outputs
- `demo_attack.py` — the injection demo
- `DESIGN.md` — architecture, verified PayPal facts with sources,
  scoring tables, open TODO-VERIFY items

## License

MIT — see [LICENSE](LICENSE).

---

*AI disclosure: this project was built with AI assistance — Muse
(Meta AI assistant) — as required to be disclosed by the hackathon
rules.*
