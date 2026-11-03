"""Local JSON stores: blocklist, payee directory, payment history.

The PayPal analogue of NearGuard's stores -- with one extra store NEAR
never needed: the payee directory. PayPal gives payees several identifiers
(email, phone, Payer ID) and offers no lookup that binds them together for
an arbitrary payee, so the binding has to come from the operator's own
records: past payments, and userinfo claims captured when a payee
authenticated to the operator's app.

All files live in the project's data/ directory (override with the
PAYGUARD_DATA environment variable). Blocklist reports must carry
evidence -- an entry without it is not accepted.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get(
    "PAYGUARD_DATA", Path(__file__).resolve().parent.parent / "data"))


def _load(name):
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / name).write_text(json.dumps(data, indent=2, sort_keys=True)
                                 + "\n")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(identifier):
    """Emails compare lowercase; Payer IDs are case-sensitive in PayPal's
    docs, but our directory keys store them uppercased for matching."""
    identifier = identifier.strip()
    return identifier.lower() if "@" in identifier else identifier.upper()


# --- blocklist --------------------------------------------------------------

def load_blocklist():
    return _load("blocklist.json")


def blocklist_match(identifiers):
    """Return (identifier, entry) if any identifier is blocklisted."""
    blocklist = load_blocklist()
    for identifier in identifiers:
        entry = blocklist.get(normalize(identifier))
        if entry is not None:
            return identifier, entry
    return None, None


def report_to_blocklist(identifier, reason, evidence, reported_by):
    """Append a report to the shared blocklist. Evidence is required."""
    if not evidence:
        raise ValueError("blocklist reports must attach evidence")
    entry = {
        "reason": reason,
        "evidence": evidence,
        "reported_by": reported_by,
        "reported_at": _now_iso(),
    }
    data = load_blocklist()
    data[normalize(identifier)] = entry
    _save("blocklist.json", data)
    return entry


# --- payee directory ----------------------------------------------------------

def load_directory():
    return _load("directory.json")


def all_directory_identifiers():
    """Map every known identifier (normalized) -> canonical payer_id."""
    mapping = {}
    for payer_id, entry in load_directory().items():
        mapping[normalize(payer_id)] = payer_id
        for email in entry.get("emails", []):
            mapping[normalize(email)] = payer_id
        for phone in entry.get("phones", []):
            mapping[normalize(phone)] = payer_id
    return mapping


def resolve_payee(identifiers):
    """Resolve presented identifiers to a directory entry, if known.

    Returns (canonical_id, entry, matched_identifier) or
    (None, None, None). The canonical id is the Payer ID when a binding
    exists, else None -- an unbound payee's canonical id is simply its
    presented identifier (handled by callers).
    """
    mapping = all_directory_identifiers()
    directory = load_directory()
    for identifier in identifiers:
        canonical = mapping.get(normalize(identifier))
        if canonical is not None:
            return canonical, directory[canonical], identifier
    return None, None, None


def directory_identifiers(canonical_id):
    """All identifiers bound to a canonical payee id, as a set."""
    entry = load_directory().get(canonical_id)
    if entry is None:
        return set()
    ids = {canonical_id}
    ids.update(entry.get("emails", []))
    ids.update(entry.get("phones", []))
    return ids


def known_domains():
    """Email domains of all directory payees (for lookalike checks)."""
    domains = set()
    for entry in load_directory().values():
        for email in entry.get("emails", []):
            if "@" in email:
                domains.add(email.rsplit("@", 1)[1].lower())
    return domains


# --- payment history ----------------------------------------------------------

def load_history():
    return _load("history.json")


def get_interaction(agent_id, canonical_id):
    """Return the history entry for agent->payee, or None."""
    return load_history().get(agent_id, {}).get(canonical_id)


def record_interaction(agent_id, canonical_id, amount_usd):
    data = load_history()
    entry = data.setdefault(agent_id, {}).setdefault(
        canonical_id,
        {"count": 0, "total_usd": "0", "max_usd": "0",
         "first": None, "last": None, "events": []})
    amount = float(amount_usd)
    entry["count"] += 1
    entry["total_usd"] = f"{float(entry['total_usd']) + amount:.2f}"
    entry["max_usd"] = f"{max(float(entry['max_usd']), amount):.2f}"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry["first"] = entry["first"] or today
    entry["last"] = today
    entry["events"].append({"ts": _now_iso(), "amount_usd": f"{amount:.2f}"})
    _save("history.json", data)
    return entry


# --- documents ----------------------------------------------------------------

def load_invoice(invoice_id):
    return _load("invoices.json").get(invoice_id)
