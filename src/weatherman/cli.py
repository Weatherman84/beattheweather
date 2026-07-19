from __future__ import annotations

import argparse

from .service import backfill, collect


def main() -> None:
    parser = argparse.ArgumentParser(prog="weatherman")
    subs = parser.add_subparsers(dest="command", required=True)
    collect_cmd = subs.add_parser("collect")
    collect_cmd.add_argument("--airports", nargs="*")
    collect_cmd.add_argument("--days", type=int, default=3)
    backfill_cmd = subs.add_parser("backfill")
    backfill_cmd.add_argument("--airports", nargs="*")
    backfill_cmd.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    result = (
        collect(args.airports, args.days)
        if args.command == "collect"
        else backfill(args.days, args.airports)
    )
    print(result)


if __name__ == "__main__":
    main()
