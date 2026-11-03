"""Command-line interface.

Usage (from the project directory):
  python -m payguard.cli check <payee> [--type EMAIL|PAYPAL_ID|PHONE]
                                       [--amount 120.00]
                                       [--agent <agent_id>]
                                       [--invoice <invoice_id>]
  python -m payguard.cli report <payee> --reason "..." \
          --evidence "..." --by <reporter_id>

<payee> is one identifier: an email address, a Payer ID, or a phone
number, interpreted per --type (default EMAIL). `check` prints the
verdict as JSON on stdout. Phase 1 evaluates against the local fixture
stores in data/ -- no PayPal calls are made.
"""

import argparse
import json
import sys

from . import service, store

DEFAULT_AGENT = "sb-agentops@business.example.com"


def _payee(identifier, recipient_type):
    if recipient_type == "EMAIL":
        return {"email": identifier}
    if recipient_type == "PAYPAL_ID":
        return {"payer_id": identifier}
    return {"phone": identifier}


def main(argv=None):
    parser = argparse.ArgumentParser(prog="payguard")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="check a payee before paying")
    p_check.add_argument("payee")
    p_check.add_argument("--type", default="EMAIL", dest="recipient_type",
                         choices=["EMAIL", "PAYPAL_ID", "PHONE"])
    p_check.add_argument("--amount", default="100.00")
    p_check.add_argument("--agent", default=DEFAULT_AGENT)
    p_check.add_argument("--invoice", default=None,
                         help="invoice id this payment claims to settle")

    p_report = sub.add_parser("report", help="add a payee to the blocklist")
    p_report.add_argument("payee")
    p_report.add_argument("--reason", required=True)
    p_report.add_argument("--evidence", required=True,
                          help="required: link or note backing the report")
    p_report.add_argument("--by", required=True, dest="reported_by")

    args = parser.parse_args(argv)

    if args.command == "check":
        context = {"invoice_id": args.invoice} if args.invoice else None
        result = service.check(args.agent,
                               _payee(args.payee, args.recipient_type),
                               args.amount, context)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "report":
        entry = store.report_to_blocklist(
            args.payee, args.reason, args.evidence, args.reported_by)
        print(json.dumps({args.payee: entry}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
