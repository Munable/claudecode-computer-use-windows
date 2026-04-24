# Click Fallback Ladder

When `pyautogui.click(x, y)` appears to do nothing (subsequent screenshot
identical to the pre-click one), do **not** retry the same call in a loop.
Walk the ladder below. Each rung is isolated so you can stop as soon as one
works, and every step must be bracketed by `pyautogui.screenshot()` before
and after — silent retries are banned.

---

## Ladder

### Rung 0 — Sanity

Before climbing the ladder, verify:

- The coordinates `(x, y)` lie inside the window bbox captured during P-3.
- DPI awareness was set in THIS process. If not, call
  `ctypes.windll.shcore.SetProcessDpiAwareness(2)` before any screenshot or
  click (or `from reference.dpi import ensure_dpi_aware; ensure_dpi_aware()`).
- Mouse is **not near `(0, 0)`** — FAILSAFE is ON. Do not move through the
  top-left corner as part of the click sequence.

### Rung 1 — Split move + click (WebView2 / Electron friendly)

```python
import pyautogui, time
pyautogui.moveTo(x, y, duration=0.05)
time.sleep(0.08)
pyautogui.click()        # click at current position, NOT pyautogui.click(x, y)
```

`pyautogui.click(x, y)` internally synthesizes move-and-click as one event;
some embedded-browser controls (WebView2, Electron, CEF) need a dwell period
between the move and the button-down event to register hover state.

### Rung 2 — Foreground the target window, then Rung 1

> On Windows 11, if another foreground application (like the terminal that
> launched this skill) covers the target window, Rung 1 `split-click` can
> silently no-op because embedded browser surfaces drop input events on
> unfocused windows. When the post-click screenshot shows no change, climb
> to Rung 2 (`ALT` unlock + `SetForegroundWindow`) and fold Rung 3's longer
> `sleep` into the same subprocess so focus doesn't leak back to the caller
> before the click lands.

**Typical tell**: Rung 1's post-click screenshot is byte-identical to the
pre-click one. If you see that pattern twice, Rung 2 is correct — do NOT
retry Rung 1 silently.

**Critical**: execute the whole focus-unlock + foreground + wait + click
chain **atomically in one subprocess**. If you split it into multiple
`python -c` calls, the launching terminal steals focus back between
calls and the click lands on the wrong window.

```python
# Rung 2 atomic pattern — ALL steps in ONE subprocess.
# Replace "<WINDOW_TITLE>" with the substring you used in --window-title.
import subprocess, sys, textwrap
WINDOW_TITLE = "<WINDOW_TITLE>"   # substring, not exact match
X, Y = 500, 300                   # target pixel coords
subprocess.run([sys.executable, "-c", textwrap.dedent(f"""
    import win32gui, pyautogui, time
    pyautogui.keyDown('alt'); pyautogui.keyUp('alt')    # unlock foreground lock
    # Walk top-level windows for a substring match (SetForegroundWindow
    # needs the exact HWND, FindWindow matches title exactly).
    hwnd = 0
    def cb(h, _):
        global hwnd
        if win32gui.IsWindowVisible(h) and {WINDOW_TITLE!r} in win32gui.GetWindowText(h):
            hwnd = h
        return True
    win32gui.EnumWindows(cb, 0)
    if hwnd:
        win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.3)                                      # let focus settle
    pyautogui.moveTo({X}, {Y}, duration=0.05); time.sleep(0.08)
    pyautogui.click()
    time.sleep(1.2)                                      # Rung 3 wait folded in
""")], check=True)
```

If no HWND matches, the window was closed mid-verification — do NOT
recurse into "relaunch the app"; return an error with the last screenshot
and let the caller decide.

### Rung 3 — Post-click wait tuned to the task

A click may be registered but the UI response (modal open, route change) is
slow. Before declaring failure, wait:

```python
time.sleep(0.8)   # baseline
# for heavier actions (page navigation, WS reconnect) try 2.0s
```

Only then compare the post-click screenshot to the pre-click one. Consider
the click successful if any of: bbox pixels changed, window title changed,
or a new top-level window appeared.

### Rung 4 — Visual retarget via template match (OPTIONAL)

If the target moved (layout shift, scroll) use `opencv-python`:

```python
import cv2, numpy as np, pyautogui
screen = np.array(pyautogui.screenshot())
target = cv2.imread("path/to/button_template.png")   # pre-captured crop
result = cv2.matchTemplate(screen, target, cv2.TM_CCOEFF_NORMED)
_, score, _, loc = cv2.minMaxLoc(result)
if score > 0.85:
    h, w = target.shape[:2]
    x, y = loc[0] + w // 2, loc[1] + h // 2
    # then Rung 1 or Rung 2
```

Template images live under a `templates/` subdirectory of the current
run's `run_dir` (returned by `preflight.build_run_dir()`; same path P-4
reports). Task-specific, never bundled in the skill.

### Rung 5 — ctypes low-level input (LAST RESORT)

Only if Rungs 1-4 all fail AND you have evidence (screenshots) that the
UI is reachable but pyautogui events are being dropped:

```python
import ctypes
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004
ctypes.windll.user32.SetCursorPos(x, y)
ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP,   0, 0, 0, 0)
```

`SendInput` is preferred on modern Windows but `mouse_event` stays
behind-the-scenes with pyautogui's own backend, so it is less surprising.

Record that you dropped to Rung 5 in the verification report — repeated
Rung-5 usage in a session usually points to an environment bug
(UAC prompt hidden behind, third-party overlay, wrong DPI mode).

---

## Stop condition

If all five rungs fail, **stop**. Collect:

- The pre- and post-click screenshots from every rung.
- `pyautogui.size()`, the window bbox from P-3, `pyautogui.position()`.
- Which rung each attempt reached, and the post-click wait used.

Return this bundle to the caller with status FAIL. Do NOT fabricate a
"click succeeded" result from a guess.

---

## Scroll fallback (separate from the click ladder)

Scrolling has its own failure modes. Two real ones seen in practice:

1. **`pyautogui.scroll(±N)` silently does nothing** — Windows routes wheel
   events to the window under the cursor, and the cursor may be on an
   unresponsive surface (overlay, gutter, fixed header). Moving the mouse
   into the scrollable content area before scrolling usually fixes it.
2. **Keyboard scroll keys (End / PageDown / Home / Space) do nothing after
   navigation** — after `start URL` or address-bar entry, DOM focus is in
   the address bar, not the page. The keys reach the omnibox caret, not
   the document. `SetForegroundWindow` does not fix this — it only affects
   *which window* has focus, not *which element* inside the window.

### Scroll recovery ladder

- **Rung S1 — Mouse wheel on content.** Move cursor to the middle of the
  scrollable region first, then `pyautogui.scroll(-N)`. Confirm via
  before/after screenshot diff.
- **Rung S2 — Transfer focus into the DOM, then keyboard.** Click a safe
  empty area in the page body (avoid links/buttons), wait briefly, then
  press `End` / `PageDown` / `Home`. Click is mandatory — `SetForeground`
  alone is not enough.
- **Rung S3 — Bypass the page mechanism.** Use a URL parameter
  (`?page=2`, `&offset=N`) if the target supports pagination, or type
  `javascript:window.scrollTo(0,document.body.scrollHeight)` in the
  address bar. Record in the report that you used this.

If all three fail, STOP and report with both screenshots and the document
layout observed. Do NOT blindly loop.

Note: zooming out (`Ctrl+-`) to fit more content on one screen is a valid
workaround when scrolling itself is intractable, but **it is not a
substitute for scrolling**. If you zoom out, report it under "workarounds
used" in the final report.
