# Troubleshooting — rare or product-specific gotchas

> **This file is NOT read by default.** SKILL.md and `click-fallbacks.md`
> cover what Claude should always know. This file holds the long-tail
> failures — things that bit us once, for a specific app or Windows
> setting, unlikely to repeat often. Consult only when the standard
> fallbacks don't explain what you're seeing.
>
> **Placement rule** (from SKILL.md "Scope discipline"):
> - If a failure hits ≥3 invocations, promote it from here to
>   `click-fallbacks.md` or SKILL.md.
> - If it only bit once in a specific context, keep it here.
> - Every entry must include: *what failed*, *why* (root cause, not
>   speculation), *how it was resolved*, *date observed*.

---

## Template for new entries

```
### <short title>

- **Observed**: <date, e.g. 2026-04-24>
- **Context**: <target app / OS version / DPI setting / browser version>
- **Symptom**: <what Claude saw — screenshot matched pre/post identical, etc.>
- **Root cause**: <the actual Windows/app behavior that caused it>
- **Resolution**: <concrete code or steps that fixed it>
- **Invocations hit**: <how many times this has recurred; promote at 3+>
```

---

## Entries

*(none yet — this file is intentionally empty on first install. Populate
only with real, reproduced failures encountered during use.)*
