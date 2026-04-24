"""
Preflight checker for claudecode-computer-use-windows.

Runs a set of environment checks BEFORE any screenshot/click is attempted.
Every invocation re-senses the environment — nothing is baked at install
time — because the target application, screen resolution, DPI scale, and
installed packages can all differ between invocations on the same machine.

Usage:
    python reference/preflight.py --window-title "<substring>"
    python reference/preflight.py --window-title "Chrome" --health-url http://127.0.0.1:8000/health
    python reference/preflight.py --json --window-title "Notepad"
    python reference/preflight.py                 # no --window-title: P-3 WARN + hint to run scan_windows.py

Exit codes:
    0  = all PASS (or only WARN)
    1  = at least one FAIL
    2  = P-1 fast-fail (non-Windows)

Checks:
    P-1  OS is Windows                      (fast-fail on non-Windows)
    P-2  Required Python packages present
    P-3  Target window visible              (needs --window-title; WARN if omitted)
    P-4  Writable per-run tempdir
    P-5  Screen resolution + DPI awareness
    P-6  Writable path whitelist reachable  (tempdir, %APPDATA%, ~)
    P-7  Optional health probe              (only runs when --health-url is set)
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import platform
import socket
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

# Local import — preflight.py and dpi.py live in the same directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from dpi import ensure_dpi_aware, primary_scale_factor  # noqa: E402


REQUIRED_PACKAGES = [
    # (import_name, pip_name, purpose)
    ("pyautogui", "pyautogui", "screenshot + click + keyboard"),
    ("pyperclip", "pyperclip", "clipboard for non-ASCII input"),
    ("win32gui", "pywin32", "HWND enumeration + foreground activation"),
]
OPTIONAL_PACKAGES = [
    ("mss", "mss", "faster multi-monitor screenshots"),
    ("cv2", "opencv-python", "template matching for click fallback"),
    ("pynput", "pynput", "keyboard/mouse event inspection"),
]

# Per-run tempdir parent — chosen to not collide with other projects.
RUN_DIR_PARENT = "ccuw-verify"


@dataclass
class CheckResult:
    id: str
    name: str
    status: str = "PASS"   # "PASS" | "WARN" | "FAIL"
    detail: str = ""
    fix: str = ""
    data: dict = field(default_factory=dict)


class PreflightAbort(SystemExit):
    """Raised by P-1 on non-Windows so later checks don't emit noise."""


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_p1_os() -> CheckResult:
    r = CheckResult(id="P-1", name="Operating system is Windows")
    if sys.platform.startswith("win") or platform.system() == "Windows":
        r.status = "PASS"
        r.detail = f"{platform.system()} {platform.release()} ({sys.platform})"
        return r
    r.status = "FAIL"
    r.detail = f"Detected {platform.system()} ({sys.platform})"
    r.fix = ("This skill drives Windows-only APIs (pywin32, WebView2, "
             "SetProcessDpiAwareness). It cannot run on non-Windows hosts.")
    return r


def check_p2_packages() -> CheckResult:
    r = CheckResult(id="P-2", name="Required Python packages importable")
    missing_required: list[tuple[str, str, str]] = []
    missing_optional: list[tuple[str, str, str]] = []
    ok_required: list[str] = []
    ok_optional: list[str] = []

    for import_name, pip_name, purpose in REQUIRED_PACKAGES:
        try:
            importlib.import_module(import_name)
            ok_required.append(import_name)
        except ImportError:
            missing_required.append((import_name, pip_name, purpose))

    for import_name, pip_name, purpose in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(import_name)
            ok_optional.append(import_name)
        except ImportError:
            missing_optional.append((import_name, pip_name, purpose))

    r.data = {
        "required_ok": ok_required,
        "required_missing": [m[0] for m in missing_required],
        "optional_ok": ok_optional,
        "optional_missing": [m[0] for m in missing_optional],
    }

    if missing_required:
        r.status = "FAIL"
        r.detail = "missing: " + ", ".join(m[0] for m in missing_required)
        pip_args = " ".join(sorted({m[1] for m in missing_required}))
        r.fix = f"pip install {pip_args}"
    elif missing_optional:
        r.status = "WARN"
        r.detail = (f"required OK ({len(ok_required)}); optional missing: "
                    + ", ".join(m[0] for m in missing_optional))
        pip_args = " ".join(sorted({m[1] for m in missing_optional}))
        r.fix = f"(optional) pip install {pip_args}"
    else:
        r.status = "PASS"
        r.detail = f"{len(ok_required)} required + {len(ok_optional)} optional all importable"
    return r


def _pick_main_window(candidates: list[Any], title_needle: str) -> Any | None:
    """Pick the best matching window: substring in title + visible + largest area."""
    matching = [w for w in candidates if title_needle in (w.title or "")]
    visible: list[Any] = []
    for w in matching:
        try:
            if getattr(w, "isMinimized", False):
                continue
            if getattr(w, "visible", True) is False:
                continue
            if (w.width or 0) <= 0 or (w.height or 0) <= 0:
                continue
            visible.append(w)
        except Exception:
            continue
    if not visible:
        return None
    visible.sort(key=lambda w: (w.width or 0) * (w.height or 0), reverse=True)
    return visible[0]


def check_p3_window(window_title: str | None) -> CheckResult:
    r = CheckResult(id="P-3", name="Target window visible (substring + visible + largest)")

    if not window_title:
        r.status = "WARN"
        r.detail = "no --window-title provided"
        r.fix = ("Run `python reference/scan_windows.py` to list visible windows, "
                 "then re-run preflight with `--window-title \"<substring>\"`. "
                 "P-3 is skipped; P-4..P-7 still run.")
        r.data = {"skipped": True}
        return r

    try:
        import pyautogui
    except ImportError:
        r.status = "FAIL"
        r.detail = "pyautogui not importable (see P-2)"
        r.fix = "resolve P-2 first"
        return r

    try:
        candidates = pyautogui.getWindowsWithTitle(window_title) or []
    except Exception as exc:
        r.status = "WARN"
        r.detail = f"getWindowsWithTitle error: {exc!r}"
        candidates = []

    win = _pick_main_window(list(candidates), window_title)
    if win is not None:
        r.status = "PASS"
        r.detail = (f"matched {win.title!r} at left={win.left} top={win.top} "
                    f"size={win.width}x{win.height} (candidates={len(candidates)})")
        r.data = {
            "title": win.title, "left": win.left, "top": win.top,
            "width": win.width, "height": win.height,
            "candidate_count": len(candidates),
            "needle": window_title,
        }
        return r

    r.status = "FAIL"
    r.detail = (f"no visible window with title containing {window_title!r} "
                f"(candidates={len(candidates)})")
    r.fix = ("Launch the target application, or run "
             "`python reference/scan_windows.py` to see the exact titles "
             "currently visible and adjust --window-title accordingly. "
             "Matching is case-sensitive substring.")
    r.data = {"candidate_count": len(candidates), "needle": window_title}
    return r


def build_run_dir() -> str:
    """Resolve and create the per-run work directory.

    Layout: <tempfile.gettempdir()>/ccuw-verify/<YYYYMMDD-HHMMSS>/
    """
    parent = os.path.join(tempfile.gettempdir(), RUN_DIR_PARENT)
    os.makedirs(parent, exist_ok=True)
    run_dir = os.path.join(parent, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def _history_usage(parent: str) -> tuple[int, int]:
    """Return (run_dir_count, total_bytes) under the run_dir parent.
    Cheap best-effort walk; does not follow symlinks."""
    count = 0
    total = 0
    if not os.path.isdir(parent):
        return 0, 0
    try:
        entries = os.listdir(parent)
    except OSError:
        return 0, 0
    for name in entries:
        sub = os.path.join(parent, name)
        if not os.path.isdir(sub):
            continue
        count += 1
        for root, _, files in os.walk(sub):
            for fn in files:
                try:
                    total += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    return count, total


def _fmt_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


def check_p4_tempdir() -> CheckResult:
    r = CheckResult(id="P-4", name="Writable per-run tempdir (no hard-coded paths)")
    try:
        run_dir = build_run_dir()
    except OSError as exc:
        r.status = "FAIL"
        r.detail = f"cannot create run dir under {tempfile.gettempdir()}: {exc}"
        r.fix = "Check disk space / permissions on the temp volume, or set TEMP/TMP env var."
        return r

    try:
        probe = os.path.join(run_dir, ".probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as exc:
        r.status = "FAIL"
        r.detail = f"cannot write inside run_dir {run_dir}: {exc}"
        r.fix = "Check disk space / permissions on the temp volume."
        return r

    # History check: accumulated run_dirs are NOT auto-deleted. Report
    # them so the user can prune with cleanup.py when disk grows.
    # Exclude the just-created run_dir from the count/bytes.
    parent = os.path.dirname(run_dir)
    count, total_bytes = _history_usage(parent)
    if count > 0:
        count -= 1  # drop the one we just made
    history_hint = (f"; history: {count} previous run(s), "
                    f"{_fmt_mb(total_bytes)} total")

    r.data = {
        "base": tempfile.gettempdir(),
        "parent": parent,
        "run_dir": run_dir,
        "history_runs": count,
        "history_bytes": total_bytes,
    }

    # Degrade to WARN when storage grows. Advisory only — never auto-clean.
    if total_bytes > 500 * 1024 * 1024 or count > 50:
        r.status = "WARN"
        r.detail = f"run_dir={run_dir}{history_hint}"
        r.fix = ("Run `python reference/cleanup.py --list` to review, then "
                 "`python reference/cleanup.py --older-than 30` (or "
                 "`--keep-last 10`) to prune. Cleanup is never automatic.")
    else:
        r.status = "PASS"
        r.detail = f"run_dir={run_dir}{history_hint}"
    return r


def check_p5_screen() -> CheckResult:
    r = CheckResult(id="P-5", name="Screen resolution & DPI awareness")
    mode = ensure_dpi_aware()
    scale = primary_scale_factor()
    try:
        import pyautogui
        w, h = pyautogui.size()
    except Exception as exc:
        r.status = "FAIL"
        r.detail = f"pyautogui.size() failed: {exc}"
        r.fix = ("Re-check P-2 (pyautogui import) and ensure an interactive "
                 "desktop session (not headless/RDP-disconnected).")
        return r

    failsafe_on = getattr(pyautogui, "FAILSAFE", True)
    r.data = {"width": w, "height": h, "dpi_mode": mode,
              "scale_factor": scale, "failsafe": failsafe_on}

    if w < 1024 or h < 768:
        r.status = "WARN"
        r.detail = (f"{w}x{h} (low-res; some UIs may clip); "
                    f"DPI={mode} (scale={scale:g}); FAILSAFE={failsafe_on}")
        r.fix = "Prefer a session with >=1024x768 for reliable element positions."
    else:
        r.status = "PASS"
        r.detail = (f"{w}x{h}; DPI={mode} (scale={scale:g}); "
                    f"FAILSAFE={failsafe_on} (leave FAILSAFE on)")
    return r


def check_p6_path_whitelist() -> CheckResult:
    r = CheckResult(id="P-6", name="Writable path whitelist reachable")
    base = tempfile.gettempdir()
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    home = os.path.expanduser("~")
    missing = []
    if not (base and os.path.isdir(base)):
        missing.append("tempfile.gettempdir()")
    if not (appdata and os.path.isdir(appdata)):
        missing.append("%APPDATA%")
    if not (home and os.path.isdir(home)):
        missing.append("~ (home)")
    r.data = {"tempdir": base, "appdata": appdata, "home": home}
    if missing:
        r.status = "WARN"
        r.detail = "missing env-derived dirs: " + ", ".join(missing)
        r.fix = "Ensure APPDATA is set (Windows standard); otherwise rely on ~ only."
    else:
        r.status = "PASS"
        r.detail = "tempdir / %APPDATA% / ~ all present — skill must write ONLY under these"
    return r


def check_p8_integrity(window_title: str | None) -> CheckResult:
    """Warn if the target window's process runs at higher integrity than ours.

    Windows UIPI silently drops synthetic input (pyautogui.mouse_event) and
    rejects PostMessage when a lower-integrity process targets a higher one.
    Detect the condition cheaply by probing PROCESS_QUERY_INFORMATION access:
    if OpenProcess is denied, the target is at higher integrity and the skill
    cannot drive it without matching elevation.
    """
    r = CheckResult(id="P-8", name="Target process integrity match (UIPI)")
    if not window_title:
        r.status = "PASS"
        r.detail = "no --window-title; skipped"
        r.data = {"skipped": True}
        return r
    try:
        import ctypes
        import pyautogui
        import win32process
    except ImportError:
        r.status = "PASS"
        r.detail = "required modules missing (see P-2); skipped"
        return r

    try:
        candidates = pyautogui.getWindowsWithTitle(window_title) or []
    except Exception:
        candidates = []
    win = _pick_main_window(list(candidates), window_title)
    if win is None:
        r.status = "PASS"
        r.detail = "no matching window (P-3 did not match); skipped"
        r.data = {"skipped": True}
        return r

    try:
        hwnd = getattr(win, "_hWnd", None)
        if hwnd is None:
            raise AttributeError("pygetwindow object has no _hWnd")
        _, target_pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception as exc:
        r.status = "PASS"
        r.detail = f"could not resolve target PID: {exc}; skipped"
        return r

    # PROCESS_QUERY_INFORMATION = 0x0400. A medium-integrity caller will be
    # denied this right on a high-integrity target (UIPI). If open succeeds,
    # target is at same-or-lower integrity and input routing should work.
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x0400, False, int(target_pid))
    if not h:
        err = ctypes.GetLastError()
        r.status = "WARN"
        r.detail = (f"cannot query PID {target_pid} (Windows error {err}); "
                    f"target runs at higher integrity than this process. "
                    f"Synthetic input will be silently dropped and PostMessage "
                    f"will fail with ACCESS_DENIED.")
        r.fix = ("Restart Claude Code as Administrator (right-click → Run as "
                 "administrator) to match the target's integrity. Otherwise "
                 "this app cannot be driven by the skill; stop before wasting "
                 "cycles on doomed clicks.")
        r.data = {"target_pid": target_pid, "open_error": err,
                  "title_match": win.title}
        return r

    k32.CloseHandle(h)
    r.status = "PASS"
    r.detail = (f"target PID {target_pid} queryable; same-or-lower integrity "
                "(UIPI should not block input)")
    r.data = {"target_pid": target_pid, "title_match": win.title}
    return r


def check_p7_health_probe(health_url: str | None) -> CheckResult:
    """Optional: probe a user-supplied health URL (e.g. the app's backend)."""
    r = CheckResult(id="P-7", name="Optional health probe (only runs when --health-url set)")
    if not health_url:
        r.status = "PASS"
        r.detail = "no --health-url supplied; skipping"
        r.data = {"skipped": True}
        return r

    parsed = urlparse(health_url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        r.status = "FAIL"
        r.detail = f"invalid URL: {health_url!r}"
        r.fix = "Provide a full URL, e.g. http://127.0.0.1:8000/health"
        return r

    r.data = {"url": health_url, "host": host, "port": port}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        try:
            s.connect((host, port))
        except OSError as exc:
            r.status = "WARN"
            r.detail = f"TCP connect to {host}:{port} failed: {exc}"
            r.fix = (f"Ensure the target service is running and listening on "
                     f"{host}:{port}. P-7 is advisory — UI verification "
                     f"does not strictly require the backend to be up.")
            return r

    try:
        from urllib.request import urlopen
        with urlopen(health_url, timeout=1.5) as resp:
            r.data["http_status"] = resp.status
            if 200 <= resp.status < 400:
                r.status = "PASS"
                r.detail = f"HTTP {resp.status} from {health_url}"
            else:
                r.status = "WARN"
                r.detail = f"HTTP {resp.status} from {health_url} (non-2xx)"
                r.fix = "Verify the URL path is correct for a health endpoint."
    except Exception as exc:
        r.status = "WARN"
        r.detail = f"TCP open but HTTP probe failed: {exc}"
        r.fix = "The port is listening but the endpoint path may be wrong."
    return r


# ---------------------------------------------------------------------------
# Runner + report
# ---------------------------------------------------------------------------


def run_all(window_title: str | None = None,
            health_url: str | None = None) -> list[CheckResult]:
    """Run checks in dependency order. P-1 fast-fails on non-Windows."""
    p1 = check_p1_os()
    if p1.status == "FAIL":
        return [p1]
    return [
        p1,
        check_p2_packages(),
        # P-5 before P-3 so DPI awareness is set before querying window bbox.
        check_p5_screen(),
        check_p3_window(window_title),
        check_p4_tempdir(),
        check_p6_path_whitelist(),
        check_p7_health_probe(health_url),
        # P-8 after P-3 because it reuses the window match to find the PID.
        check_p8_integrity(window_title),
    ]


def _ensure_manifest(run_dir: str) -> str:
    """Return path to manifest.json, seeding a bare one if missing."""
    os.makedirs(run_dir, exist_ok=True)
    mp = os.path.join(run_dir, "manifest.json")
    if not os.path.isfile(mp):
        try:
            with open(mp, "w", encoding="utf-8") as f:
                json.dump(
                    {"schema": "ccuw-verify-manifest/v1",
                     "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "checks": [],
                     "screenshots": [],
                     "actions": [],
                     "evaluations": [],
                     "workarounds": [],
                     "note": "bare manifest; preflight was not run in this run_dir"},
                    f, ensure_ascii=False, indent=2,
                )
        except OSError:
            pass
    return mp


def record_event(run_dir: str, kind: str, data: dict) -> None:
    """Append an event entry to manifest.json.

    `kind` ∈ {"screenshot", "action", "evaluation", "workaround"}.
    Each kind appends to its corresponding plural array. Unknown kinds go
    to an `other` array so nothing is silently dropped.

    Callers should pass domain fields in `data` — e.g.:
        record_event(rd, "action", {"kind": "click", "x": 1820, "y": 940})
        record_event(rd, "evaluation", {"step": "page-1", "result": "pass",
                                        "expected": "...", "observed": "..."})
        record_event(rd, "workaround", {"tactic": "Ctrl+-", "reason": "scroll was inert"})

    Timestamp is added automatically. Returns silently on IO errors; this
    is a logging convenience, not a correctness primitive.
    """
    mp = _ensure_manifest(run_dir)
    entry = {**data, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    array_key = {
        "screenshot": "screenshots",
        "action": "actions",
        "evaluation": "evaluations",
        "workaround": "workarounds",
    }.get(kind, "other")
    try:
        with open(mp, "r+", encoding="utf-8") as f:
            m = json.load(f)
            m.setdefault(array_key, []).append(entry)
            f.seek(0); f.truncate()
            json.dump(m, f, ensure_ascii=False, indent=2)
    except (OSError, json.JSONDecodeError):
        pass


def record_screenshot(run_dir: str, path: str, step: str, phase: str) -> None:
    """Append a screenshot entry to manifest.json (kept for back-compat).

    New callers should prefer `record_event(run_dir, "screenshot", {...})`
    directly; this wrapper will continue to work indefinitely.
    """
    record_event(run_dir, "screenshot",
                 {"path": path, "step": step, "phase": phase})


def _write_manifest(results: list[CheckResult]) -> str | None:
    p4 = next((r for r in results if r.id == "P-4" and r.status == "PASS"), None)
    if not p4 or "run_dir" not in p4.data:
        return None
    manifest_path = os.path.join(p4.data["run_dir"], "manifest.json")
    payload = {
        "schema": "ccuw-verify-manifest/v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "checks": [asdict(r) for r in results],
        "screenshots": [],
        "actions": [],
        "evaluations": [],
        "workarounds": [],
    }
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return manifest_path
    except OSError:
        return None


def format_report(results: list[CheckResult]) -> str:
    lines = [
        "claudecode-computer-use-windows preflight report",
        "=" * 50,
    ]
    for r in results:
        marker = {"PASS": "[PASS]", "WARN": "[WARN]", "FAIL": "[FAIL]"}.get(r.status, "[??]")
        lines.append(f"{marker} {r.id}  {r.name}")
        if r.detail:
            lines.append(f"       {r.detail}")
        if r.fix and r.status != "PASS":
            lines.append(f"       fix: {r.fix}")
    statuses = [r.status for r in results]
    overall = "FAIL" if "FAIL" in statuses else ("WARN" if "WARN" in statuses else "PASS")
    lines.append("-" * 50)
    lines.append(f"OVERALL: {overall}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="claudecode-computer-use-windows preflight")
    parser.add_argument("--window-title", default=None,
                        help="substring of the target window title "
                             "(omit to let P-3 WARN + suggest scan_windows.py)")
    parser.add_argument("--health-url", default=None,
                        help="optional URL to probe as P-7 (e.g. http://127.0.0.1:8000/health)")
    parser.add_argument("--json", action="store_true",
                        help="print JSON report instead of text")
    args = parser.parse_args(argv)

    # Allow env-var fallback so callers can set it once per shell session.
    window_title = args.window_title or os.environ.get("CCUW_WINDOW_TITLE")
    health_url = args.health_url or os.environ.get("CCUW_HEALTH_URL")

    results = run_all(window_title=window_title, health_url=health_url)

    # P-1 fast-fail path
    if len(results) == 1 and results[0].id == "P-1" and results[0].status == "FAIL":
        if args.json:
            print(json.dumps(
                {"results": [asdict(results[0])], "overall": "FAIL",
                 "fast_fail": "P-1"},
                ensure_ascii=False, indent=2,
            ))
        else:
            print(format_report(results))
            print("P-1 fast-fail: non-Windows host, later checks skipped.")
        raise PreflightAbort(2)

    manifest_path = _write_manifest(results)

    if args.json:
        print(json.dumps(
            {"results": [asdict(r) for r in results],
             "overall": "FAIL" if any(r.status == "FAIL" for r in results) else
                        "WARN" if any(r.status == "WARN" for r in results) else "PASS",
             "manifest": manifest_path},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(format_report(results))
        if manifest_path:
            print(f"manifest: {manifest_path}")
        p4 = next((r for r in results if r.id == "P-4" and r.status == "PASS"), None)
        if p4 and "run_dir" in p4.data:
            rd = p4.data["run_dir"]
            print("\nTo re-use this run_dir in Step 1 without re-running preflight,")
            print("export it first:")
            print(f"  set CCUW_RUN_DIR={rd}          # cmd.exe")
            print(f"  $env:CCUW_RUN_DIR='{rd}'        # PowerShell")
            print(f"  export CCUW_RUN_DIR='{rd}'      # bash/git-bash")

    return 1 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PreflightAbort as e:
        sys.exit(int(e.code) if e.code is not None else 2)
