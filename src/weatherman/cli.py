from __future__ import annotations

import argparse

from .service import backfill, backfill_market_history, collect


def main() -> None:
    parser = argparse.ArgumentParser(prog="weatherman")
    subs = parser.add_subparsers(dest="command", required=True)
    collect_cmd = subs.add_parser("collect")
    collect_cmd.add_argument("--airports", nargs="*")
    collect_cmd.add_argument("--days", type=int, default=3)
    backfill_cmd = subs.add_parser("backfill")
    backfill_cmd.add_argument("--airports", nargs="*")
    backfill_cmd.add_argument("--days", type=int, default=365)
    market_cmd = subs.add_parser("backfill-market-history")
    market_cmd.add_argument("--airports", nargs="*")
    market_cmd.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    if args.command == "collect":
        result = collect(args.airports, args.days)
    elif args.command == "backfill-market-history":
        result = backfill_market_history(args.days, args.airports)
    else:
        result = backfill(args.days, args.airports)
    print(result)


if __name__ == "__main__":
    main()
