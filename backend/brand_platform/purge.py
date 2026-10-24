"""Manual audit purge: ``python -m brand_platform.purge [--older-than-days N] [--apply]`` (run from backend/).

Preview is the default and deletes nothing. ``--apply`` deletes the listed expired audits (with their reports and
findings) in one transaction. The period comes from ``BRAND_PLATFORM_RETENTION_DAYS`` unless ``--older-than-days``
is given; with neither, retention is disabled and the command does nothing. The database is the one the server uses
(``BRAND_PLATFORM_DATA_DIR``). Queued and running audits are never deleted.
"""

from __future__ import annotations

import argparse
import sys

from . import retention
from .config import Settings, parse_retention_days
from .db import Database


def _days(value: str) -> int:
    try:
        days = parse_retention_days(value, source="--older-than-days")
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if days is None:
        raise argparse.ArgumentTypeError("--older-than-days needs a whole number of days from 1 to 3650.")
    return days


def main(argv=None, out=sys.stdout) -> int:
    parser = argparse.ArgumentParser(prog="python -m brand_platform.purge", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--older-than-days", type=_days, metavar="N",
                        help="override the configured retention period for this run (1-3650)")
    parser.add_argument("--apply", action="store_true", help="actually delete; without it this is a preview")
    args = parser.parse_args(argv)

    try:
        settings = Settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    days = args.older_than_days or settings.retention_days
    if days is None:
        print("Retention is disabled (BRAND_PLATFORM_RETENTION_DAYS is not set) and no --older-than-days was given. "
              "Nothing to do; audits are kept indefinitely.", file=out)
        return 0
    if not settings.db_path.is_file():
        print(f"No platform database at {settings.db_path}. Nothing to purge.", file=out)
        return 0

    db = Database(settings.db_path)
    preview = retention.plan(db, days)
    print(f"Retention period: {days} day(s). Cutoff (UTC): {preview['cutoff']}. "
          f"Finished audits older than the cutoff: {len(preview['eligible'])}.", file=out)
    for audit in preview["eligible"]:
        print(f"  {audit['id'][:8]}  {audit['status']:<11} {audit['age_basis']}={audit['age_basis_at']}  {audit['host']}", file=out)
    if preview["undated"]:
        print(f"{len(preview['undated'])} finished audit(s) have an unreadable timestamp and are never deleted.", file=out)
    if not args.apply:
        print("Preview only: nothing was deleted. Re-run with --apply to delete the audits listed above.", file=out)
        return 0
    result = retention.apply(db, days, trigger="manual")
    print(f"Deleted {result['deleted_audits']} audit(s), {result['deleted_reports']} report(s) and "
          f"{result['deleted_findings']} finding(s). WAL checkpoint complete: {result['wal_checkpoint_complete']}.", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
