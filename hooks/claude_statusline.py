"""Official Claude Code statusLine hook script.

Reads Claude Code's documented statusLine JSON payload from stdin, persists
5-hour and 7-day rate_limits into AI Usage Bar's local state file, and prints
a concise status line for Claude Code's terminal UI.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from state_store import (  # noqa: E402
    clamp_pct,
    format_countdown,
    parse_timestamp,
    update_provider_state,
)


def _extract_limit(obj: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    used = clamp_pct(obj.get("used_percentage"))
    rem = clamp_pct(obj.get("remaining_percentage"))
    if rem is None and used is not None:
        rem = clamp_pct(100.0 - used)
    if used is None and rem is not None:
        used = clamp_pct(100.0 - rem)
    if rem is None:
        return None
    resets_at = parse_timestamp(obj.get("resets_at"), now=now)
    return {
        "remaining_pct": rem,
        "used_pct": used,
        "resets_at": resets_at,
    }


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    raw = sys.stdin.read()
    if not raw.strip():
        return 0

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    if not isinstance(payload, dict):
        return 0

    now = time.time()

    model_info = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    model_name = model_info.get("display_name") or model_info.get("id") or ""

    ctx_info = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    ctx_used = clamp_pct(ctx_info.get("used_percentage"))

    cost_info = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
    total_cost = cost_info.get("total_cost_usd")

    rate_limits = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else {}
    session_5h = _extract_limit(rate_limits.get("five_hour"), now)
    weekly = _extract_limit(rate_limits.get("seven_day"), now)

    extra_buckets: Dict[str, Any] = {}
    for key, val in rate_limits.items():
        if key in ("five_hour", "seven_day"):
            continue
        parsed = _extract_limit(val, now)
        if parsed is not None:
            extra_buckets[key] = parsed

    patch: Dict[str, Any] = {
        "source": "claude_code_statusline",
        "updated_at": now,
        "model": model_name or None,
        "context_used_pct": ctx_used,
        "total_cost_usd": total_cost,
    }
    if weekly is not None:
        patch["weekly"] = weekly
    if session_5h is not None:
        patch["session_5h"] = session_5h
    if extra_buckets:
        patch["extra_buckets"] = extra_buckets

    try:
        update_provider_state("claude", patch)
    except Exception:
        pass

    # Render a clean 1-line status bar back to Claude Code
    parts = []
    if model_name:
        parts.append(str(model_name))
    if ctx_used is not None:
        parts.append(f"Ctx {ctx_used:.0f}%")
    if session_5h is not None:
        cd = format_countdown(session_5h.get("resets_at"), compact=True, now=now)
        suffix = f" ({cd})" if cd else ""
        parts.append(f"5h {session_5h['remaining_pct']:.0f}% left{suffix}")
    if weekly is not None:
        cd = format_countdown(weekly.get("resets_at"), compact=True, now=now)
        suffix = f" ({cd})" if cd else ""
        parts.append(f"7d {weekly['remaining_pct']:.0f}% left{suffix}")

    if parts:
        print(" | ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
