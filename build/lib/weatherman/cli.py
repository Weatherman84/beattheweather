from __future__ import annotations

import argparse
from pathlib import Path

from .hourly_archive import archive_sqlite_history, rebuild_manifest
from .service import (
    backfill,
    backfill_market_history,
    collect,
    collect_live_decision_checkpoints,
    collect_research_checkpoints,
    sync_airport_universe,
)
from .maintenance import maintain_sqlite_database


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
    research_cmd = subs.add_parser("collect-research-checkpoints")
    research_cmd.add_argument("--airports", nargs="*")
    research_cmd.add_argument("--window-minutes", type=int, default=30)
    decision_cmd = subs.add_parser("collect-live-decisions")
    decision_cmd.add_argument("--airports", nargs="*")
    universe_cmd = subs.add_parser("sync-airport-universe")
    universe_cmd.add_argument("--include-closed", action="store_true")
    maintenance_cmd = subs.add_parser("maintain-database")
    maintenance_cmd.add_argument("--hourly-days", type=int, default=7)
    maintenance_cmd.add_argument("--archive-directory", type=Path)
    archive_cmd = subs.add_parser("archive-hourly-history")
    archive_cmd.add_argument("--database", type=Path, required=True)
    archive_cmd.add_argument("--archive-directory", type=Path, required=True)
    archive_cmd.add_argument("--before")
    audit_cmd = subs.add_parser("audit-hourly-archive")
    audit_cmd.add_argument("--archive-directory", type=Path, default=Path("data/hourly_archive"))
    args = parser.parse_args()
    if args.command == "collect":
        result = collect(args.airports, args.days)
    elif args.command == "backfill-market-history":
        result = backfill_market_history(args.days, args.airports)
    elif args.command == "collect-research-checkpoints":
        result = collect_research_checkpoints(args.airports, window_minutes=args.window_minutes)
    elif args.command == "collect-live-decisions":
        result = collect_live_decision_checkpoints(args.airports)
    elif args.command == "sync-airport-universe":
        result = sync_airport_universe(include_closed=args.include_closed)
    elif args.command == "maintain-database":
        result = maintain_sqlite_database(
            hourly_retention_days=args.hourly_days,
            archive_directory=args.archive_directory,
        )
    elif args.command == "archive-hourly-history":
        result = archive_sqlite_history(
            args.database,
            args.archive_directory,
            before=args.before,
        )
    elif args.command == "audit-hourly-archive":
        result = rebuild_manifest(args.archive_directory)
    else:
        result = backfill(args.days, args.airports)
    print(result)


if __name__ == "__main__":
    main()
