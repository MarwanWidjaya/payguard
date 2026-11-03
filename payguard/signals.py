"""Signal collection for one proposed payment.

Every signal comes from data that verifiably exists on PayPal rails: the
proposal itself (payee identifiers, amount, recipient_type, the invoice or
order it claims to settle) and the operator's own local records
(blocklist, payee directory, payment history). PayPal exposes no trust
attributes for an arbitrary payee -- see DESIGN.md -- so no signal here
pretends otherwise; what cannot be known is reported as unknown.
"""

from datetime import datetime, timezone

from . import store


def levenshtein(a, b):
    """Small edit-distance helper for the lookalike-domain heuristic."""
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[len(b)]


def _days_since(date_str):
    if not date_str:
        return None
    then = datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - then).days


def _parse_ts(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


def collect_signals(agent_id, payee, amount, context=None):
    """payee: dict with any of {email, payer_id, phone} (+ recipient_type).

    context: optional dict, e.g. {"invoice_id": "INV-2026-1001"} for the
    document the payment claims to settle.
    """
    context = context or {}
    presented = [v for k in ("email", "payer_id", "phone")
                 if (v := payee.get(k))]
    signals = {"payee": payee, "presented_identifiers": presented}

    # Canonical payee: directory binding if known, else the receiver
    # identifier itself (email preferred, then payer_id, then phone).
    canonical, entry, matched = store.resolve_payee(presented)
    signals["known_payee"] = entry is not None
    signals["directory_entry"] = entry
    signals["canonical_id"] = canonical or (presented[0] if presented
                                             else None)

    # P1: blocklist -- match on presented OR directory-bound identifiers.
    all_ids = list(presented)
    if entry is not None:
        all_ids += list(store.directory_identifiers(canonical))
    hit_id, hit_entry = store.blocklist_match(all_ids)
    signals["blocklisted"] = hit_entry is not None
    signals["blocklist_identifier"] = hit_id
    signals["blocklist_entry"] = hit_entry

    # P3: identifier drift -- payee resolved by one identifier while a
    # presented identifier contradicts the binding.
    signals["identifier_drift"] = False
    signals["drift_detail"] = None
    if entry is not None:
        bound = store.directory_identifiers(canonical)
        bound_norm = {store.normalize(i) for i in bound}
        for identifier in presented:
            if store.normalize(identifier) not in bound_norm:
                signals["identifier_drift"] = True
                signals["drift_detail"] = (
                    f"{identifier} is not bound to known payee "
                    f"{canonical} (bound: {sorted(bound)})")
                break

    # P9: verification status -- only when genuinely known.
    signals["payee_verified"] = (entry.get("verified_account")
                                 if entry else None)

    # P7: lookalike email domain (heuristic, local string math only).
    signals["lookalike_domain"] = None
    email = payee.get("email")
    if email and "@" in email:
        domain = email.rsplit("@", 1)[1].lower()
        for known in store.known_domains():
            if domain != known and levenshtein(domain, known) <= 2:
                signals["lookalike_domain"] = known
                break

    # P4/P5/P6: history, amount, velocity.
    interaction = store.get_interaction(agent_id, signals["canonical_id"])
    signals["first_interaction"] = interaction is None
    signals["prior_interactions"] = interaction["count"] if interaction else 0
    signals["relationship_days"] = (
        _days_since(interaction["first"]) if interaction else None)
    signals["amount_usd"] = float(amount)
    signals["amount_vs_max"] = None
    signals["velocity_24h_count"] = 0
    signals["velocity_24h_total_usd"] = 0.0
    if interaction:
        max_usd = float(interaction["max_usd"])
        if max_usd > 0:
            signals["amount_vs_max"] = float(amount) / max_usd
        now = datetime.now(timezone.utc)
        for event in interaction.get("events", []):
            age_hours = (now - _parse_ts(event["ts"])).total_seconds() / 3600
            if age_hours <= 24:
                signals["velocity_24h_count"] += 1
                signals["velocity_24h_total_usd"] += float(
                    event["amount_usd"])

    # P8: invoice context cross-check.
    signals["context_mismatch"] = None
    invoice_id = context.get("invoice_id")
    if invoice_id:
        invoice = store.load_invoice(invoice_id)
        if invoice is None:
            signals["context_mismatch"] = (
                f"referenced invoice {invoice_id} not found")
        else:
            expected = {invoice.get("recipient_email"),
                        invoice.get("recipient_payer_id")} - {None}
            expected_norm = {store.normalize(e) for e in expected}
            presented_norm = {store.normalize(p) for p in presented}
            if entry is not None:
                presented_norm |= {store.normalize(i) for i in
                                   store.directory_identifiers(canonical)}
            if not (expected_norm & presented_norm):
                signals["context_mismatch"] = (
                    f"invoice {invoice_id} is addressed to "
                    f"{sorted(expected)}, not to the proposed receiver "
                    f"{presented}")
    return signals
