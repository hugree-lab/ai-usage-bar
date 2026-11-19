#!/usr/bin/env python3
"""Zero-dependency Python 3 official statusLine hook for macOS / POSIX.

Mirrors hooks/QuotaHook.cs: parses stdin JSON from `agy` (--agy) or `claude` (--claude),
merges into ~/Library/Application Support/AIUsageBar/quota_state.json with fcntl.flock,
and prints a concise statusLine summary.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AIUsageBar"
    return Path.home() / ".ai-usage-bar"


def _clamp_pct(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(100.0, x)), 1)


def _parse_ts(val: Any, fallback_sec: Any = None, now: float = 0.0) -> Optional[float]:
    if not now:
        now = time.time()
    if val is not None and val != "":
        if isinstance(val, (int, float)):
            ts = float(val)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 0:
                return ts
        elif isinstance(val, str):
            raw = val.strip()
            if raw:
                try:
                    num = float(raw)
                    if num > 1e12:
                        num /= 1000.0
                    if num > 0:
                        return num
                except ValueError:
                    pass
                try:
                    iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    pass
    if fallback_sec is not None:
        try:
            sec = float(fallback_sec)
            if sec >= 0:
                return now + sec
        except (TypeError, ValueError):
            pass
    return None


def _update_state(provider: str, patch: Dict[str, Any]) -> None:
    ddir = _data_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    state_path = ddir / "quota_state.json"
    lock_path = ddir / ".state.lock"

    with open(lock_path, "w", encoding="utf-8") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            state: Dict[str, Any] = {"claude": {}, "antigravity": {}, "codex": {}}
            if state_path.exists():
                try:
                    loaded = json.loads(state_path.read_text(encoding="utf-8-sig"))
                    if isinstance(loaded, dict):
                        state.update(loaded)
                except Exception:
                    pass

            prev = state.get(provider)
            if not isinstance(prev, dict):
                prev = {}
            merged = dict(prev)
            for k, v in patch.items():
                if k in ("weekly", "weekly_argon", "weekly_fable", "session_5h") and isinstance(v, dict):
                    if v.get("remaining_pct") is None and isinstance(prev.get(k), dict):
                        continue
                    merged[k] = v
                elif v is not None:
                    merged[k] = v
            state[provider] = merged

            fd, tmp_name = tempfile.mkstemp(prefix="quota_state_", suffix=".tmp", dir=str(ddir))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as tf:
                    json.dump(state, tf, ensure_ascii=False, indent=2)
                    tf.flush()
                    os.fsync(tf.fileno())
                os.replace(tmp_name, str(state_path))
            finally:
                if os.path.exists(tmp_name):
                    try:
                        os.unlink(tmp_name)
                    except OSError:
                        pass
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _handle_agy(payload: Dict[str, Any], now: float) -> str:
    patch: Dict[str, Any] = {"source": "agy_statusline", "updated_at": now}
    model = payload.get("model")
    if isinstance(model, dict):
        patch["model"] = model.get("display_name") or model.get("id")
    elif isinstance(model, str):
        patch["model"] = model

    quota = payload.get("quota")
    all_buckets: Dict[str, Any] = {}
    if isinstance(quota, dict):
        for k, v in quota.items():
            if not isinstance(v, dict):
                continue
            rem = _clamp_pct(v.get("remaining_percentage") if "remaining_percentage" in v else v.get("remaining_pct"))
            used = _clamp_pct(v.get("used_percentage") if "used_percentage" in v else v.get("used_pct"))
            if rem is None and used is not None:
                rem = _clamp_pct(100.0 - used)
            if used is None and rem is not None:
                used = _clamp_pct(100.0 - rem)
            if rem is None:
                continue
            resets = _parse_ts(v.get("resets_at"), v.get("resets_in_seconds"), now)
            all_buckets[k] = {
                "bucket_id": k,
                "remaining_pct": rem,
                "used_pct": used,
                "resets_at": resets,
            }

    if all_buckets:
        patch["all_buckets"] = all_buckets
        patch["quota_updated_at"] = now
        if "gemini-weekly" in all_buckets:
            patch["weekly"] = all_buckets["gemini-weekly"]
        if "gemini-argon-wtu-weekly" in all_buckets:
            patch["weekly_argon"] = all_buckets["gemini-argon-wtu-weekly"]
        if "gemini-5h" in all_buckets:
            patch["session_5h"] = all_buckets["gemini-5h"]

    _update_state("antigravity", patch)
    wk = patch.get("weekly") or patch.get("weekly_argon")
    if isinstance(wk, dict) and wk.get("used_pct") is not None:
        return f"AGY {wk['used_pct']:.0f}% used"
    return "AGY HUD"


def _handle_claude(payload: Dict[str, Any], now: float) -> str:
    patch: Dict[str, Any] = {"source": "claude_statusline", "updated_at": now}
    model = payload.get("model")
    if isinstance(model, dict):
        patch["model"] = model.get("display_name") or model.get("id")
    elif isinstance(model, str):
        patch["model"] = model

    ctx = payload.get("context_window")
    if isinstance(ctx, dict) and ctx.get("used_percentage") is not None:
        patch["context_used_pct"] = _clamp_pct(ctx.get("used_percentage"))

    rl = payload.get("rate_limits")
    if isinstance(rl, dict):
        def _parse_rl(obj: Any) -> Optional[Dict[str, Any]]:
            if not isinstance(obj, dict):
                return None
            used = _clamp_pct(obj.get("used_percentage") if "used_percentage" in obj else obj.get("used_pct"))
            rem = _clamp_pct(obj.get("remaining_percentage") if "remaining_percentage" in obj else obj.get("remaining_pct"))
            if rem is None and used is not None:
                rem = _clamp_pct(100.0 - used)
            if used is None and rem is not None:
                used = _clamp_pct(100.0 - rem)
            if rem is None:
                return None
            resets = _parse_ts(obj.get("resets_at"), obj.get("resets_in_seconds"), now)
            return {"remaining_pct": rem, "used_pct": used, "resets_at": resets}

        w = _parse_rl(rl.get("seven_day"))
        if w:
            patch["weekly"] = w
        fb = _parse_rl(rl.get("seven_day_fable"))
        if fb:
            patch["weekly_fable"] = fb
        s5 = _parse_rl(rl.get("five_hour"))
        if s5:
            patch["session_5h"] = s5

    _update_state("claude", patch)
    wk = patch.get("weekly")
    if isinstance(wk, dict) and wk.get("used_pct") is not None:
        return f"Claude {wk['used_pct']:.0f}% used"
    return "Claude HUD"


def main() -> int:
    is_agy = "--agy" in sys.argv
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    now = time.time()
    out = _handle_agy(payload, now) if is_agy else _handle_claude(payload, now)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
