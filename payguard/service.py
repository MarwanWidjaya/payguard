"""Scoring: turn a signal set into a verdict.

Verdicts: "allow" / "warn" / "block". Rules are deliberately transparent --
every point is returned in `reasons` so the decision can be audited from
the log alone. See DESIGN.md for the full rule table, the verified PayPal
facts behind each signal, and the NearGuard signals that have NO PayPal
analogue (and what replaced them).
"""

from .signals import collect_signals

BLOCK_THRESHOLD = 50
WARN_THRESHOLD = 25
AMOUNT_ANOMALY_RATIO = 3.0      # amount > 3x historical max for this payee
VELOCITY_24H_COUNT = 3          # >= 3 payments to this payee in 24 h
SOFT_CAP_USD = 500.0            # agent policy soft cap (phase-1 default)


def evaluate(signals):
    reasons = []
    score = 0

    # Hard overrides first.
    if signals.get("blocklisted"):
        entry = signals.get("blocklist_entry") or {}
        reasons.append(
            f"BLOCKLISTED via {signals.get('blocklist_identifier')}: "
            f"{entry.get('reason', 'reported')} "
            f"(evidence: {entry.get('evidence', 'n/a')}, "
            f"reported by {entry.get('reported_by', 'unknown')})")
        return {"verdict": "block", "score": 100, "reasons": reasons,
                "signals": signals}
    if signals.get("context_mismatch"):
        reasons.append(f"CONTEXT MISMATCH: {signals['context_mismatch']}")
        return {"verdict": "block", "score": 100, "reasons": reasons,
                "signals": signals}

    # Scored signals.
    if signals.get("identifier_drift"):
        score += 40
        reasons.append(
            f"identifier drift for a known payee: "
            f"{signals.get('drift_detail')} (+40)")
    if signals.get("lookalike_domain"):
        score += 35
        reasons.append(
            f"payee email domain is a lookalike of known payee domain "
            f"{signals['lookalike_domain']} (heuristic) (+35)")
    ratio = signals.get("amount_vs_max")
    if ratio is not None and ratio > AMOUNT_ANOMALY_RATIO:
        score += 25
        reasons.append(
            f"amount is {ratio:.1f}x this payee's historical max (+25)")
    if signals.get("first_interaction"):
        score += 20
        reasons.append("first interaction between this agent and payee (+20)")
    elif signals.get("relationship_days") is not None \
            and signals["relationship_days"] < 30:
        score += 15
        reasons.append("relationship with this payee is younger than "
                       "30 days (+15)")
    if signals.get("velocity_24h_count", 0) >= VELOCITY_24H_COUNT:
        score += 20
        reasons.append(
            f"{signals['velocity_24h_count']} payments to this payee in "
            f"the last 24 h (+20)")
    if signals.get("payee_verified") is False:
        score += 20
        reasons.append("payee is known and their PayPal account is NOT "
                       "verified (+20)")
    if not signals.get("known_payee"):
        score += 10
        reasons.append("payee identity not verifiable pre-payment: no "
                       "directory binding exists, and PayPal offers no "
                       "lookup for arbitrary payees (+10)")
    if signals.get("amount_usd", 0) > SOFT_CAP_USD:
        score += 15
        reasons.append(
            f"amount is above the agent's soft cap of "
            f"${SOFT_CAP_USD:.0f} (+15)")

    if score >= BLOCK_THRESHOLD:
        verdict = "block"
    elif score >= WARN_THRESHOLD:
        verdict = "warn"
    else:
        verdict = "allow"
    if not reasons:
        reasons.append("no risk signals fired")
    return {"verdict": verdict, "score": score, "reasons": reasons,
            "signals": signals}


def check(agent_id, payee, amount, context=None):
    """Full check: collect signals for one proposed payment and score."""
    return evaluate(collect_signals(agent_id, payee, amount, context))
