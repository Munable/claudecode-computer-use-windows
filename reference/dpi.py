"""
DPI awareness helper.

Every Python process that takes a screenshot or sends a click MUST set
Per-Monitor V2 DPI awareness FIRST — otherwise `pyautogui.size()` and
`pyautogui.screenshot()` return virtualized pixel counts, while
`pyautogui.click()` uses real pixels. The mismatch causes clicks to land
in the wrong place on any display with scale != 100%.

Import this module and call `ensure_dpi_aware()` as the first line after
imports in every helper script that touches screen/mouse.
"""
from __future__ import annotations

import ctypes


def ensure_dpi_aware() -> str:
    """Set Per-Monitor V2 DPI awareness for the current process.

    Returns a string describing which awareness level was successfully
    applied: "per-monitor-v2", "system", or a failure description.
    Safe to call multiple times; subsequent calls are no-ops.
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor-v2"
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return "system"
        except Exception as exc:  # pragma: no cover - exotic Windows SKUs
            return f"unavailable ({exc!r})"


def primary_scale_factor() -> float:
    """Return the DPI scale factor of the primary monitor as a float.

    Examples: 1.0 (100%), 1.25 (125%), 1.5 (150%), 2.0 (200%).
    After ensure_dpi_aware() is called, pyautogui returns REAL pixels, so
    this scale factor is informational only — coordinates do NOT need
    additional conversion as long as all processes call ensure_dpi_aware()
    before any screen/mouse operation.

    Mainly useful in preflight reports so the user can verify the value
    matches their Windows display settings.
    """
    try:
        # GetDpiForSystem returns raw DPI (96 = 100%, 120 = 125%, ...)
        dpi = ctypes.windll.user32.GetDpiForSystem()
        return dpi / 96.0
    except (AttributeError, OSError):
        return 1.0
