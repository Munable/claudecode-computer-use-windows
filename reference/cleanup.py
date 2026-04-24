"""
Manual cleanup for accumulated ccuw-verify/ run directories.

Never invoked automatically — the user runs this when they decide to
reclaim disk space. The skill's preflight only reports history size; it
never deletes.

Usage:
    python reference/cleanup.py --list                       # show sizes only (default, safe)
    python reference/cleanup.py --older-than 7               # delete runs older than 7 days
    python reference/cleanup.py --older-than 30 --dry-run    # preview without deleting
    python reference/cleanup.py --keep-last 10               # keep newest 10, delete the rest

No destructive action happens without an explicit flag (--older-than or
--keep-last). --list is the default and is always read-only.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass

# Must match the parent dir name used by preflight.py.
RUN_DIR_PARENT = "ccuw-verify"
# Run subdirs look like YYYYMMDD-HHMMSS (preflight's time.strftime format).
RUN_DIR_PATTERN = re.compile(r"^\d{8}-\d{6}$")


@dataclass
class RunDir:
    path: str
    name: str
    mtime: float
    size_bytes: int
    file_count: int


def _dir_size(path: str) -> tuple[int, int]:
    """Return (bytes, file_count) under path. Silent on permission errors."""
    total_bytes = 0
    total_files = 0
    for root, _, files in os.walk(path):
        for fn in files:
            try:
                total_bytes += os.path.getsize(os.path.join(root, fn))
                total_files += 1
            except OSError:
                pass
    return total_bytes, total_files


def scan_runs(parent: str | None = None) -> list[RunDir]:
    base = parent or os.path.join(tempfile.gettempdir(), RUN_DIR_PARENT)
    if not os.path.isdir(base):
        return []
    runs: list[RunDir] = []
    for name in os.listdir(base):
        full = os.path.join(base, name)
        if not os.path.isdir(full):
            continue
        if not RUN_DIR_PATTERN.match(name):
            # Skip stray directories that don't match preflight's naming.
            continue
        try:
            mtime = os.path.getmtime(full)
        except OSError:
            continue
        size_bytes, file_count = _dir_size(full)
        runs.append(RunDir(path=full, name=name, mtime=mtime,
                           size_bytes=size_bytes, file_count=file_count))
    runs.sort(key=lambda r: r.mtime, reverse=True)
    return runs


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def format_list(runs: list[RunDir]) -> str:
    if not runs:
        return "(no run directories found)"
    lines = [
        f"{'WHEN':<20}  {'SIZE':>10}  {'FILES':>6}  NAME",
        f"{'-' * 20}  {'-' * 10}  {'-' * 6}  {'-' * 16}",
    ]
    now = time.time()
    total_bytes = 0
    for r in runs:
        age_days = (now - r.mtime) / 86400
        age_str = f"{age_days:.1f} days ago"
        lines.append(f"{age_str:<20}  {_fmt_size(r.size_bytes):>10}  "
                     f"{r.file_count:>6}  {r.name}")
        total_bytes += r.size_bytes
    lines.append(f"{'-' * 20}  {'-' * 10}  {'-' * 6}  {'-' * 16}")
    lines.append(f"{len(runs)} runs, {_fmt_size(total_bytes)} total")
    return "\n".join(lines)


def _delete(runs: list[RunDir], dry_run: bool) -> tuple[int, int]:
    """Delete each run. Returns (count_deleted, bytes_reclaimed)."""
    count, freed = 0, 0
    for r in runs:
        if dry_run:
            print(f"  would delete: {r.name} ({_fmt_size(r.size_bytes)})")
            count += 1; freed += r.size_bytes
            continue
        try:
            shutil.rmtree(r.path)
            print(f"  deleted: {r.name} ({_fmt_size(r.size_bytes)})")
            count += 1; freed += r.size_bytes
        except OSError as exc:
            print(f"  FAILED to delete {r.name}: {exc}", file=sys.stderr)
    return count, freed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List or prune accumulated ccuw-verify/ run directories")
    parser.add_argument("--list", action="store_true",
                        help="list runs with sizes and ages (read-only, default)")
    parser.add_argument("--older-than", type=int, metavar="DAYS",
                        help="delete runs older than DAYS days")
    parser.add_argument("--keep-last", type=int, metavar="N",
                        help="keep the newest N runs, delete the rest")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be deleted without deleting")
    args = parser.parse_args(argv)

    runs = scan_runs()

    if not runs:
        print(f"No run directories found under "
              f"{os.path.join(tempfile.gettempdir(), RUN_DIR_PARENT)}.")
        return 0

    # Default: --list mode.
    if not (args.older_than or args.keep_last):
        print(format_list(runs))
        return 0

    # Select deletion candidates.
    if args.older_than is not None:
        cutoff = time.time() - args.older_than * 86400
        victims = [r for r in runs if r.mtime < cutoff]
        reason = f"older than {args.older_than} days"
    else:
        victims = runs[args.keep_last:]  # runs is newest-first
        reason = f"beyond newest {args.keep_last}"

    if not victims:
        print(f"Nothing to delete ({reason}).")
        print(format_list(runs))
        return 0

    print(f"Deleting {len(victims)} run(s) {reason}"
          f"{' [DRY RUN]' if args.dry_run else ''}:")
    count, freed = _delete(victims, dry_run=args.dry_run)
    print(f"\n{'Would reclaim' if args.dry_run else 'Reclaimed'} "
          f"{_fmt_size(freed)} across {count} run(s).")

    if not args.dry_run:
        remaining = scan_runs()
        print(f"\nRemaining:")
        print(format_list(remaining))
    return 0


if __name__ == "__main__":
    sys.exit(main())
