"""
List visible top-level windows so the user can pick one to verify against.

Called by preflight when the caller did not pass --window-title, and by
SKILL.md Step 0 when the user asks "what windows are open right now".
Output is stable, human-readable, and includes enough metadata (pid,
class, bbox, title) for the user to identify their target unambiguously.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict

from dpi import ensure_dpi_aware


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    class_name: str
    left: int
    top: int
    width: int
    height: int
    minimized: bool


def _enum_windows() -> list[WindowInfo]:
    import win32gui
    import win32process

    results: list[WindowInfo] = []

    def _callback(hwnd: int, _lparam: int) -> bool:
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return True
            class_name = win32gui.GetClassName(hwnd) or ""
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            try:
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
            except Exception:
                l = t = w = h = 0
            if w <= 0 or h <= 0:
                return True
            try:
                is_min = bool(win32gui.IsIconic(hwnd))
            except Exception:
                is_min = False
            results.append(WindowInfo(
                hwnd=hwnd, pid=pid, title=title, class_name=class_name,
                left=l, top=t, width=w, height=h, minimized=is_min,
            ))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(_callback, 0)
    return results


def scan(include_minimized: bool = False) -> list[WindowInfo]:
    ensure_dpi_aware()
    wins = _enum_windows()
    if not include_minimized:
        wins = [w for w in wins if not w.minimized]
    wins.sort(key=lambda w: w.width * w.height, reverse=True)
    return wins


def format_table(wins: list[WindowInfo]) -> str:
    if not wins:
        return "(no visible top-level windows found)"
    lines = [
        f"{'PID':>7}  {'SIZE':>11}  {'CLASS':<24}  TITLE",
        f"{'-' * 7}  {'-' * 11}  {'-' * 24}  {'-' * 40}",
    ]
    for w in wins:
        size = f"{w.width}x{w.height}"
        cls = (w.class_name or "")[:24]
        title = w.title if len(w.title) <= 60 else w.title[:57] + "..."
        lines.append(f"{w.pid:>7}  {size:>11}  {cls:<24}  {title}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List visible top-level windows on this desktop"
    )
    parser.add_argument("--json", action="store_true",
                        help="emit JSON array instead of text table")
    parser.add_argument("--include-minimized", action="store_true",
                        help="also list minimized windows")
    args = parser.parse_args(argv)

    wins = scan(include_minimized=args.include_minimized)

    if args.json:
        print(json.dumps([asdict(w) for w in wins],
                         ensure_ascii=False, indent=2))
    else:
        print(format_table(wins))
        print(f"\n{len(wins)} window(s) listed. "
              "Copy a distinctive substring from one title and pass it as "
              "--window-title to preflight.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
