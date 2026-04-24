---
name: computer-use-windows
description: Verify any Windows desktop application UI through the "screenshot → Read → decide → act → screenshot" loop against the real running window. Generic — works for pywebview, Electron, native Win32/WPF, and browsers alike. Use when Claude is about to claim a UI/frontend/desktop-window fix is done, OR when the user asks to "verify / check / test" something in a real application window, OR any time Claude is tempted to substitute Playwright / localhost browser / code-reading for real desktop interaction. Windows-only (uses pywin32, SetProcessDpiAwareness, pyautogui). Each invocation self-senses the environment — there is nothing baked at install time. Covers preflight (7 environment checks), the 5-step verify loop, the click-fallback ladder, non-ASCII input via clipboard, and a hard-forbidden-substitution list. Mandatory before declaring any Windows desktop UI work complete.
---

# computer-use-windows

> **Generic** "screenshot → Read → act" loop for verifying Windows desktop UI.
> Nothing is pinned to a specific product: the user supplies the target
> window's title (as a substring) at invocation time, and every environment
> detail (resolution, DPI, installed packages, run_dir) is re-sensed on
> each run.

---

## When to use / NOT to use

**Use** before claiming any Windows desktop UI fix is done; when the user
asks to "verify X in <some window>"; whenever Claude is tempted to open a
browser at `localhost`, use Playwright/Selenium/CDP, or reason purely from
source code.

**Skip** for pure backend/API work with no user-visible surface (run the
project's tests instead). Also skip on non-Windows — this skill uses
pywin32 / Windows DPI APIs; P-1 will fast-fail.

---

## The input you always need

Before anything else, you need ONE piece of information from the user
(or the task) — **a substring of the target window's title**.

Examples:

- Verifying an Electron app titled "MyApp - Settings" → use `"MyApp"`
- Verifying Chrome at a specific page → use `"Chrome"` (or a more specific tab word)
- Verifying Notepad with "Untitled - Notepad" → use `"Notepad"`

If the user didn't give one, run the window scanner FIRST to let them pick:

```bash
python reference/scan_windows.py
```

This prints every visible top-level window with PID, size, class, and title.
Ask the user which one they want and extract a distinctive substring.

---

## The five-step verification loop (mandatory)

Every pass is five atomic steps. **Each act MUST be bracketed by a
screenshot before and a screenshot after** — blind sequential calls
without an intervening `Read` on a screenshot are banned.

1. **SCREENSHOT** — `pyautogui.screenshot()` saved under `run_dir`
2. **READ** — use the `Read` tool on the PNG (vision)
3. **DECIDE** — plan next action from what Read sees
4. **ACT** — click / type / hotkey (see Step 4 section below)
5. **SCREENSHOT** — again; Read; confirm the expected change

Repeat per user-journey step. If step 5 doesn't match expectations, STOP
— report or climb the click-fallback ladder (`./reference/click-fallbacks.md`).

**After each 5-step pass, explicitly state**:

> "I have evaluated step X. Expected: <what>. Observed: <what>. Pass/Fail."

Only move to the next step after an explicit pass. This is directly borrowed
from Anthropic's computer-use best practice — the explicit "I have evaluated"
sentence meaningfully reduces silent mis-validations.

---

## Step 0 — Preflight (always run first)

Skill MUST NOT take any action before preflight. From the skill directory
(the one containing `SKILL.md`):

```bash
# Minimum — P-3 will WARN and ask you to pick a window first.
python reference/preflight.py

# With target window.
python reference/preflight.py --window-title "<substring>"

# With an optional backend health probe.
python reference/preflight.py --window-title "<substring>" --health-url http://127.0.0.1:8000/health
```

The preflight runs **seven checks** (P-1 fast-fails on non-Windows with
exit code 2; P-2..P-7 full-scan so every remaining issue surfaces at once):

- **P-1** OS is Windows (fast-fails otherwise).
- **P-2** `pyautogui`, `pyperclip`, `pywin32` importable.
- **P-3** A window whose title *contains* `--window-title` is visible
         (substring + visible + largest). WARN if --window-title is omitted.
- **P-4** `<tempdir>/ccuw-verify/<timestamp>/` is writable.
- **P-5** Per-Monitor V2 DPI awareness set + resolution + scale factor captured.
- **P-6** `%APPDATA%`, `~`, tempdir are reachable.
- **P-7** Optional: health probe to a user-supplied URL. Skipped if not given.

**Decision rules:**

- `OVERALL: PASS` or `WARN` → proceed to Step 1. Capture:
  - the `run_dir` path (from P-4 `data.run_dir`) — all screenshots go here
  - the window bbox (from P-3 `data`) — use to constrain click coordinates
  - the `manifest.json` path — append each screenshot to its `screenshots` array
- `OVERALL: FAIL` → do NOT proceed. Relay each failing check's `fix:`
  line to the user verbatim. Common cases:
  - **P-1 fast-fail (exit code 2)** → non-Windows host, skill cannot run.
  - **P-2 FAIL** → relay the `pip install` command. Skill must NOT auto-install.
  - **P-3 FAIL** → the title substring matches no visible window. Run
    `scan_windows.py` to list what IS visible and ask the user to adjust.

**Window matching is substring + visible + largest**. Titles with suffixes
like `" - DevTools"` or `" *"` still match; preflight picks the visible,
non-minimized candidate with the largest area. **Do not require strict
equality** with the needle.

---

## Step 1 — Screenshot (first and between every action)

Reuse the `run_dir` from preflight's P-4 (`data.run_dir`). All screenshots
for one pass live in that one dir. Two helpers in `reference/preflight.py`:

- `build_run_dir()` — returns (creates) `<tempdir>/ccuw-verify/<ts>/`;
  fallback when you lost the variable in a fresh process.
- `record_screenshot(run_dir, path, step, phase)` — appends to
  `manifest.json`; auto-seeds a bare manifest if missing.
  `phase` ∈ {`before`, `after`}.

```python
import os, sys, time, pyautogui
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "reference"))
from dpi import ensure_dpi_aware
from preflight import build_run_dir, record_screenshot

# Re-apply DPI awareness in THIS process; pyautogui.size() and .screenshot()
# both read virtualized pixels without it.
ensure_dpi_aware()

# Prefer preflight's run_dir via CCUW_RUN_DIR env; else fall back.
# record_screenshot() auto-seeds a bare manifest so you don't orphan shots.
run_dir = os.environ.get("CCUW_RUN_DIR") or build_run_dir()
path = os.path.join(run_dir, f"step-{int(time.time()*1000)}.png")
pyautogui.screenshot().save(path)
record_screenshot(run_dir, path, step="initial", phase="before")
print(path)   # Step 2 reads from this path
```

Rules:

- **No hard-coded paths.** Use `tempfile.gettempdir()` at runtime — never
  embed any literal for a specific user home, a fixed tempdir, or a drive
  letter (P-4/P-6).
- **DPI awareness every process.** Every standalone Python process you
  launch must import and call `ensure_dpi_aware()` BEFORE any pyautogui
  call. Don't rely on "some earlier process set it".

## Step 2 — Read the screenshot (vision)

Use the `Read` tool on the PNG path. Identify UI elements, text (Chinese /
English / other), positions, current state. Prefer region-based reasoning
("button group near y=88, shows 3 items") over pixel-perfect assertions.
If `Read` shows unexpected content (blank screen, 404, error toast), stop
and report.

**Expected control absent.** If the control the task asked for is not
present on the expected page — report what **is** there, stop, and ask
the caller to clarify or re-scope. **Never** hunt for a "close-enough"
control or silently pick another field; that turns verification into
guessing.

## Step 3 — Decide

Translate what `Read` saw into the next action: button to click (approx
center), field to fill (ASCII vs non-ASCII — affects Step 4's input
method), or a page change to wait for.

## Step 4 — Act

> **Focus gotcha**: after `start URL` or any external browser navigation, Chrome's
> DOM focus is in the address bar, not the page. Any keyboard scroll (End /
> PageDown / Home / Space) **must be preceded by a click in the page body** to
> transfer focus into the DOM. `SetForegroundWindow` only brings the window to
> the top — it does not choose which element inside the window is focused.
> See `reference/click-fallbacks.md` § Scroll fallback.

### 4a. Click

Prefer the split form (Rung 1 of `./reference/click-fallbacks.md`):

```python
import pyautogui, time
pyautogui.moveTo(x, y, duration=0.05); time.sleep(0.08); pyautogui.click()
```

If Step 5's post-click screenshot is identical to pre-click, walk the
ladder (Rungs 2-5). Never loop on Rung 1 silently.

### 4b. Type ASCII text

```python
pyautogui.click(x, y); time.sleep(0.1)
pyautogui.typewrite("hello", interval=0.02)
```

### 4c. Type non-ASCII text (Chinese, emoji, symbols) — MUST use clipboard

`pyautogui.typewrite()` cannot emit non-ASCII. Always route through the
clipboard:

```python
import pyperclip, pyautogui, time
pyperclip.copy("你好,世界")
pyautogui.click(x, y); time.sleep(0.1)     # focus the input first
pyautogui.hotkey("ctrl", "v")
```

Forbidden: `pyautogui.typewrite("中文")`, `pyautogui.write("中文")`.

### 4d. Keyboard shortcuts

```python
pyautogui.hotkey("ctrl", "s")    # save
pyautogui.press("escape")        # close modal
```

### 4e. Do not move through `(0, 0)`

`pyautogui.FAILSAFE` is on by default and raises at any screen corner.
Never park the mouse at `(0, 0)`; move to the window's bottom-right if you
need to clear tooltips. Do NOT disable FAILSAFE.

## Step 5 — Screenshot again, Read, confirm

Repeat Step 1+2 with `phase="after"` in `record_screenshot(...)`, then
compare. Typical success signals: new modal/page, input shows pasted text,
toast confirms the action. If the expected change is absent or wrong,
report with all screenshots + the action attempted — do not silently
re-try. **State "I have evaluated step X — Pass" or "Fail" explicitly.**

---

## Hard forbidden list (automatic FAIL if violated)

1. **Opening a browser at `http://127.0.0.1:*` or `http://localhost:*`**
   as a substitute for verifying the real desktop window. If the target
   is a desktop app whose window the user named, VERIFY THAT WINDOW —
   don't pivot to a browser rendering.
2. **Playwright / Selenium / Puppeteer / CDP** in place of pyautogui.
3. **Reasoning from source code alone** in place of a real click loop.
   "I read the JSX and it looks right" does NOT count as verification.
4. **Blind action sequences.** Two `pyautogui` calls with no screenshot +
   `Read` between them = violation.
5. **`pyautogui.typewrite()` on non-ASCII input** (use clipboard, 4c).
6. **Hard-coded absolute paths, or writing outside the P-6 whitelist.**
   No literal user home, drive letter, tempdir path, resolution number,
   or port literal — derive from `tempfile`, env vars, or preflight
   output. All file writes must stay inside `run_dir` / `%APPDATA%` /
   `~`. Screenshots, manifests, and templates live in `run_dir`.
7. **Disabling `pyautogui.FAILSAFE`** or intentionally moving the cursor
   near `(0, 0)`.
8. **Auto-installing packages** when P-2 fails. Report the missing
   package(s) and the `pip install` command; let the user decide.
9. **Proceeding without a `--window-title`** (or env var `CCUW_WINDOW_TITLE`).
   P-3 must PASS before any click. If P-3 is WARN (title omitted) or FAIL
   (no match), either get the user to pick via `scan_windows.py` or stop.
10. **Matching on a different/inferred title string** than what the user
    provided. The substring must be exactly what was passed to
    `--window-title`; the extra filter is "visible, non-minimized,
    largest area". Do not silently relax or rewrite the substring.
11. **Substituting a "close-enough" target** when the expected control
    is absent on the expected page. Report what IS there and stop; do
    not silently pick another field.
Violating any item aborts the verification with status FAIL.

---

## Expected report shape

Report back to the caller with:

- Preflight overall status + any WARN/FAIL details.
- The `run_dir` path (P-4 `data.run_dir`) and its `manifest.json`; the
  manifest already lists every screenshot with step name and phase —
  point at the file, don't repaste.
- Per step: "before" path, action, "after" path, pass/fail, and the
  explicit "I have evaluated step X" sentence.
- Env metadata (from preflight JSON): `pyautogui.size()`, DPI mode +
  scale factor, window bbox, FAILSAFE state — so the caller can
  reproduce.
- If any click-fallback rung beyond Rung 1 was used, which and why.
- **All workarounds beyond the documented rungs.** If you used `Ctrl+-/+`
  to zoom, a `javascript:` URL, a custom delay longer than standard, or
  any other ad-hoc technique, list it and why it was needed. Silent
  workarounds compound across invocations and make the skill harder to
  improve.

---

## References

- `./reference/preflight.py` — 7-check environment scan; exits 0 on PASS/WARN,
  1 on FAIL, 2 on P-1 fast-fail. Supports `--json`, `--window-title`,
  `--health-url`. Reads `CCUW_WINDOW_TITLE` / `CCUW_HEALTH_URL` env vars.
- `./reference/scan_windows.py` — lists every visible top-level window
  (PID, class, size, title) so the user can pick one.
- `./reference/dpi.py` — `ensure_dpi_aware()` + `primary_scale_factor()`.
  Import this first in every helper script that touches screen or mouse.
- `./reference/click-fallbacks.md` — click + scroll recovery ladders,
  consulted only when the standard Rung 1 produces no visible effect.
- `./reference/troubleshooting.md` — rare / product-specific gotchas
  accumulated across real use. Not loaded by default; consult only when
  SKILL.md + click-fallbacks.md don't cover what you're seeing.
- `./reference/cleanup.py` — manual tool for pruning accumulated
  `run_dir` history when disk usage grows. Never invoked automatically.

Installation and first-run instructions live in `README.md`.

---

## Scope discipline (rules for editing this skill)

These govern how this skill evolves across repeated use. Respect them to
keep SKILL.md from bloating into a graveyard of every historical gotcha.

- **Don't add fallback ladders for failures you haven't actually seen.**
  Real failures go in; hypothetical ones stay out.
- **Optional > mandatory** for every new helper. If a tool is only useful
  sometimes, make it a `reference/` script invoked on demand, not a
  MUST-run step.
- **Three-tier placement for new learnings**:
  - Universal principle that applies every run → SKILL.md body (rare)
  - Common failure mode (≥3 invocations hit it) → `click-fallbacks.md`
  - Rare / product-specific gotcha → `reference/troubleshooting.md`
- **Cleanup stays manual.** The skill reports disk usage (P-4) and
  provides `cleanup.py`, but never deletes without explicit user action.
- **If a workaround worked once, document it under "Report workarounds"
  in the final report — don't ban it, and don't silently reuse it.**
