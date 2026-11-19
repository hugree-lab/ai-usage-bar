"""Official Antigravity CLI (agy) statusLine hook script.

Reads Antigravity CLI's documented statusLine JSON payload from stdin,
persists quota buckets (remaining_fraction, reset_time, reset_in_seconds)
into AI Usage Bar's local state file, and prints a concise status line.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from state_store import (  # noqa: E402
    clamp_pct,
    format_countdown,
    parse_timestamp,
    update_provider_state,
)


def _parse_bucket(bucket_id: str, obj: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    if obj.get("disabled"):
        return None

    rem_pct: Optional[float] = None
    raw_frac = obj.get("remaining_fraction")
    if raw_frac is not None:
        try:
            f = float(raw_frac)
            rem_pct = clamp_pct(f * 100.0 if f <= 1.0 else f)
        except (TypeError, ValueError):
            pass

    if rem_pct is None and obj.get("remaining_percentage") is not None:
        rem_pct = clamp_pct(obj.get("remaining_percentage"))

    if rem_pct is None:
        return None

    resets_at = parse_timestamp(
        obj.get("reset_time") or obj.get("resets_at"),
        fallback_in_seconds=obj.get("reset_in_seconds"),
        now=now,
    )
    return {
        "bucket_id": bucket_id,
        "remaining_pct": rem_pct,
        "used_pct": clamp_pct(100.0 - rem_pct),
        "remaining_amount": obj.get("remaining_amount"),
        "resets_at": resets_at,
    }


def _classify_buckets(
    all_buckets: Dict[str, Dict[str, Any]], now: float
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    weekly: Optional[Dict[str, Any]] = None
    session_5h: Optional[Dict[str, Any]] = None

    weekly_candidates = []
    short_candidates = []

    for bid, b in all_buckets.items():
        low = bid.lower()
        resets_at = b.get("resets_at")
        horizon = (resets_at - now) if resets_at else None

        is_weekly = any(tok in low for tok in ("week", "7d", "7-day"))
        is_short = any(tok in low for tok in ("5h", "5-hour", "session", "short", "hourly"))

        # Prefer gemini bucket if multiple pools exist, otherwise lowest remaining
        gemini_bonus = 0 if "gemini" in low else 1
        rem = b.get("remaining_pct") if b.get("remaining_pct") is not None else 100.0

        if is_weekly:
            weekly_candidates.append((gemini_bonus, rem, b))
        elif is_short:
            short_candidates.append((gemini_bonus, rem, b))
        elif horizon is not None and horizon > 24 * 3600:
            weekly_candidates.append((gemini_bonus + 2, rem, b))
        else:
            short_candidates.append((gemini_bonus + 2, rem, b))

    if weekly_candidates:
        weekly_candidates.sort(key=lambda x: (x[0], x[1]))
        weekly = weekly_candidates[0][2]
    if short_candidates:
        short_candidates.sort(key=lambda x: (x[0], x[1]))
        session_5h = short_candidates[0][2]

    # If only short/unlabeled buckets exist, still surface the primary one in weekly if weekly missing
    if weekly is None and len(all_buckets) == 1:
        weekly = next(iter(all_buckets.values()))

    return weekly, session_5h


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
    plan_tier = payload.get("plan_tier")

    raw_quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else {}
    all_buckets: Dict[str, Dict[str, Any]] = {}
    for bid, bval in raw_quota.items():
        parsed = _parse_bucket(str(bid), bval, now)
        if parsed is not None:
            all_buckets[str(bid)] = parsed

    weekly, session_5h = _classify_buckets(all_buckets, now)

    patch: Dict[str, Any] = {
        "source": "agy_cli_statusline",
        "updated_at": now,
        "model": model_name or None,
        "plan_tier": plan_tier,
    }
    if all_buckets:
        patch["all_buckets"] = all_buckets
    if weekly is not None:
        patch["weekly"] = weekly
    if session_5h is not None:
        patch["session_5h"] = session_5h

    try:
        update_provider_state("antigravity", patch)
    except Exception:
        pass

    parts = []
    if model_name:
        parts.append(str(model_name))
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
