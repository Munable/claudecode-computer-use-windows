# claudecode-computer-use-windows

A [Claude Code](https://claude.com/claude-code) skill that verifies **any
Windows desktop application UI** through a real **screenshot → Read → act
→ screenshot** loop. No browser, no Playwright, no CDP, no "reasoning from
code instead of clicking".

> Inspired by Anthropic's [computer use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/computer-use-tool)
> architecture, adapted for native Windows desktops (where `xdotool` and
> `scrot` don't exist). The official Anthropic reference implementation runs
> inside a Linux Docker container against a virtual Xvfb display; this
> skill runs against your **real** Windows desktop.

## What this skill gives Claude Code

- **Per-invocation environment self-sensing.** Nothing is baked at install
  time — every run re-checks OS, installed packages, DPI, resolution,
  tempdir, and the target window.
- **A five-step verification loop** (screenshot, Read, decide, act,
  screenshot) that Claude MUST follow before claiming a UI fix is done.
- **A seven-check preflight** (`reference/preflight.py`) that fails loudly
  if the environment can't support real-world verification.
- **A five-rung click-fallback ladder** (`reference/click-fallbacks.md`)
  for when `pyautogui.click()` silently no-ops because focus was stolen.
- **A hard forbidden list** (12 items): browser at `localhost`,
  Playwright/Selenium, blind action sequences, `pyautogui.typewrite()`
  on non-ASCII, hardcoded absolute paths, disabling FAILSAFE, etc.
- **Non-ASCII input via clipboard** (required for Chinese / emoji /
  symbols — `pyautogui.typewrite()` can't emit them).
- **Windows-specific tricks** — Per-Monitor V2 DPI awareness, `ALT` key
  unlock before `SetForegroundWindow`, substring window-title matching.

## Installation

```bash
# 1. Clone into your Claude Code skills directory
git clone https://github.com/Munable/claudecode-computer-use-windows.git \
    ~/.claude/skills/claudecode-computer-use-windows

# 2. Install required Python packages (the skill NEVER auto-installs)
pip install pyautogui pyperclip pywin32

# 3. (Optional, for advanced click recovery and multi-monitor captures)
pip install mss opencv-python pynput
```

Claude Code picks up the skill automatically the next time you start a
session. Invoke with `/computer-use-windows` or trigger it implicitly by
asking Claude to "verify X in the <window title> window".

## Quick sanity run

```bash
cd ~/.claude/skills/claudecode-computer-use-windows

# Dry-run preflight — P-3 will WARN (no target yet); the rest should PASS.
python reference/preflight.py

# See every visible window so you can pick a target.
python reference/scan_windows.py

# Real run against a named window.
python reference/preflight.py --window-title "Notepad"
```

## Scope and limitations

- **Windows-only.** This skill uses pywin32, `SetProcessDpiAwareness`, and
  substring-match on Win32 window titles. `P-1` fast-fails on non-Windows
  with exit code 2.
- **Target supplied per invocation.** There is no baked-in product name.
  The user gives a substring of the target window's title at run time
  (via `--window-title`, env var `CCUW_WINDOW_TITLE`, or
  `scan_windows.py` discovery).
- **Not for headless web apps.** If your target is only served to a real
  browser (no desktop window), use Playwright/Cypress/Selenium instead.
  This skill exists precisely because WebView2/Electron/native apps
  behave differently than Chromium does for those tools.
- **No auto-install.** Preflight prints the `pip install` command for
  missing packages but the user decides whether to run it.
- **Launch is only on explicit request.** The skill will never silently
  start an app the user didn't name, but when the user says "open X" or
  "check Y at https://..." it can invoke the system's default handler
  (`start URL`, `start <app>`) as part of serving that request.

## How this relates to Anthropic's official computer use

| Dimension | Anthropic computer use | This skill |
|---|---|---|
| Target | Xvfb virtual display inside Docker (Linux) | Real Windows desktop |
| Action tool | Model-returned `computer_20251124` tool_use JSON | SKILL.md rules + pyautogui snippets |
| Screenshot | `scrot` / `gnome-screenshot` → base64 | `pyautogui.screenshot()` → PNG file |
| Click | `xdotool click` | `pyautogui.click()` (+ fallback ladder) |
| Non-ASCII input | `xdotool type` (unreliable) | Clipboard + `Ctrl+V` (mandatory) |
| DPI handling | N/A (single virtual display) | Per-Monitor V2 awareness required |
| Termination | "no tool_use in response" + iteration cap | "step 5 matches expectation" + explicit "I have evaluated step X" |
| Safety | VM/Docker sandbox required | Runs on user's real desktop (verifies self-written UIs only) |

This skill borrows the **"after each step, screenshot and explicitly
state 'I have evaluated step X'"** pattern from the official docs — that
one sentence meaningfully reduces silent mis-validations.

## Directory layout

```
claudecode-computer-use-windows/
├── SKILL.md                # What Claude Code reads to activate the skill
├── README.md               # This file
├── LICENSE                 # MIT
├── .gitignore
└── reference/
    ├── preflight.py        # 7-check environment scan + manifest helpers
    ├── scan_windows.py     # Lists every visible top-level window
    ├── dpi.py              # Per-Monitor V2 DPI awareness helper
    ├── cleanup.py          # Manual pruning of accumulated run_dir history
    ├── click-fallbacks.md  # Click + scroll recovery ladders
    └── troubleshooting.md  # Rare / product-specific gotchas (not loaded by default)
```

## Keeping the run directory tidy

Each invocation of the skill creates a new `run_dir` under
`%TEMP%\ccuw-verify\<timestamp>\` containing screenshots, a `manifest.json`
audit log, and any templates. These are never auto-deleted. After many
runs they accumulate.

```bash
# See how much disk the history is using
python reference/cleanup.py --list

# Keep the newest 10, delete the rest
python reference/cleanup.py --keep-last 10

# Delete runs older than 30 days
python reference/cleanup.py --older-than 30

# Preview first without deleting
python reference/cleanup.py --older-than 30 --dry-run
```

Preflight's P-4 also reports the current history size and will degrade
to WARN (with a fix line pointing at `cleanup.py`) when the total exceeds
500 MB or 50 runs. Actual deletion is always user-triggered.

## License

MIT - see [LICENSE](./LICENSE).
