#!/usr/bin/env python3
"""Zero-dependency Python 3 official statusLine hook for macOS / POSIX.

Full feature parity with hooks/QuotaHook.cs:
- Parses stdin JSON from `agy` (--agy / --antigravity) or `claude` (--claude)
- Supports remaining_fraction, remaining_percentage, used_percentage, utilization,
  reset_time, resets_at, reset_in_seconds, resets_in_seconds, disabled, model_scoped,
  camelCase & snake_case payloads, and fuzzy Antigravity bucket classification
- Merges atomically into ~/Library/Application Support/AIUsageBar/quota_state.json
  using fcntl.flock, and prints a concise statusLine summary.
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
from typing import Any, Dict, List, Optional, Tuple


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


def _get_float(d: Optional[Dict[str, Any]], *keys: str) -> Optional[float]:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (TypeError, ValueError):
                continue
    return None


def _get_first(d: Optional[Dict[str, Any]], *keys: str) -> Any:
    if not isinstance(d, dict):
        return None
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


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


def _format_countdown_compact(resets_at: Optional[float], now: float) -> str:
    if resets_at is None:
        return ""
    diff = int(resets_at - now)
    if diff <= 0:
        return "reset"
    days, rem = divmod(diff, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{max(1, mins)}m"


def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.stem + "_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            tf.flush()
            os.fsync(tf.fileno())
        os.replace(tmp_name, str(path))
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def _update_state(state_path: Path, provider: str, patch: Dict[str, Any]) -> None:
    ddir = state_path.parent
    ddir.mkdir(parents=True, exist_ok=True)
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
            _write_json_atomic(state_path, state)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


def _write_safe_debug_schema(state_path: Path, mode: str, payload: Dict[str, Any], now: float) -> None:
    try:
        dbg_path = state_path.parent / "hook_debug.json"
        dbg: Dict[str, Any] = {}
        if dbg_path.exists():
            try:
                loaded = json.loads(dbg_path.read_text(encoding="utf-8-sig"))
                if isinstance(loaded, dict):
                    dbg = loaded
            except Exception:
                pass
        entry: Dict[str, Any] = {"updated_at": now, "keys": list(payload.keys())}
        for k in ("rate_limits", "rateLimits", "quota", "cost", "context_window"):
            if k in payload:
                entry[k] = payload[k]
        dbg[mode] = entry
        _write_json_atomic(dbg_path, dbg)
    except Exception:
        pass


def _parse_agy_bucket(bucket_id: str, obj: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    if obj.get("disabled") is True:
        return None

    rem: Optional[float] = None
    raw_frac = _get_float(obj, "remaining_fraction", "remainingFraction")
    if raw_frac is not None:
        rem = _clamp_pct(raw_frac * 100.0 if raw_frac <= 1.0 else raw_frac)

    if rem is None:
        rem = _clamp_pct(_get_float(obj, "remaining_percentage", "remainingPercentage", "remaining_pct"))

    used = _clamp_pct(_get_float(obj, "used_percentage", "usedPercentage", "used_pct", "utilization"))
    if rem is None and used is not None:
        rem = _clamp_pct(100.0 - used)
    if used is None and rem is not None:
        used = _clamp_pct(100.0 - rem)
    if rem is None:
        return None

    resets = _parse_ts(
        _get_first(obj, "reset_time", "resets_at", "resetsAt"),
        _get_first(obj, "reset_in_seconds", "resets_in_seconds", "resetInSeconds"),
        now,
    )
    return {
        "bucket_id": bucket_id,
        "remaining_pct": rem,
        "used_pct": used,
        "remaining_amount": obj.get("remaining_amount"),
        "resets_at": resets,
    }


def _classify_agy_buckets(
    all_buckets: Dict[str, Dict[str, Any]], now: float
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    weekly: Optional[Dict[str, Any]] = None
    weekly_argon: Optional[Dict[str, Any]] = None
    session_5h: Optional[Dict[str, Any]] = None

    weekly_cands: List[Tuple[int, float, Dict[str, Any]]] = []
    argon_cands: List[Tuple[int, float, Dict[str, Any]]] = []
    short_cands: List[Tuple[int, float, Dict[str, Any]]] = []

    for bid, b in all_buckets.items():
        low = bid.lower()
        resets_at = b.get("resets_at")
        horizon = (float(resets_at) - now) if resets_at is not None else None
        is_argon = "argon" in low
        is_3p = low.startswith("3p") or "3p-" in low
        is_weekly = any(tok in low for tok in ("week", "7d", "7-day"))
        is_short = any(tok in low for tok in ("5h", "5-hour", "session", "short", "hourly"))
        prio = 2 if is_3p else (0 if "gemini" in low else 1)
        rem = float(b["remaining_pct"]) if b.get("remaining_pct") is not None else 100.0

        if is_argon:
            argon_cands.append((prio, rem, b))
        elif is_weekly:
            weekly_cands.append((prio, rem, b))
        elif is_short:
            short_cands.append((prio, rem, b))
        elif horizon is not None and horizon > 86400.0:
            weekly_cands.append((prio + 3, rem, b))
        else:
            short_cands.append((prio + 3, rem, b))

    if weekly_cands:
        weekly_cands.sort(key=lambda x: (x[0], x[1]))
        weekly = weekly_cands[0][2]
    if argon_cands:
        argon_cands.sort(key=lambda x: (x[0], x[1]))
        weekly_argon = argon_cands[0][2]
    if short_cands:
        short_cands.sort(key=lambda x: (x[0], x[1]))
        session_5h = short_cands[0][2]

    if weekly is None and weekly_argon is None and len(all_buckets) == 1:
        weekly = next(iter(all_buckets.values()))

    return weekly, weekly_argon, session_5h


def _handle_agy(payload: Dict[str, Any], state_path: Path, now: float) -> str:
    model = payload.get("model")
    if isinstance(model, dict):
        model_name = str(model.get("display_name") or model.get("id") or "")
    elif isinstance(model, str):
        model_name = model
    else:
        model_name = ""
    plan_tier = payload.get("plan_tier")

    quota = payload.get("quota")
    all_buckets: Dict[str, Dict[str, Any]] = {}
    if isinstance(quota, dict):
        for k, v in quota.items():
            parsed = _parse_agy_bucket(str(k), v, now)
            if parsed is not None:
                all_buckets[str(k)] = parsed

    weekly, weekly_argon, session_5h = _classify_agy_buckets(all_buckets, now)

    patch: Dict[str, Any] = {"source": "agy_cli_statusline"}
    if model_name:
        patch["model"] = model_name
    if plan_tier:
        patch["plan_tier"] = str(plan_tier)
    if all_buckets:
        patch["updated_at"] = now
        patch["quota_updated_at"] = now
        patch["all_buckets"] = all_buckets
    if weekly is not None:
        patch["weekly"] = weekly
    if weekly_argon is not None:
        patch["weekly_argon"] = weekly_argon
    if session_5h is not None:
        patch["session_5h"] = session_5h

    _update_state(state_path, "antigravity", patch)

    parts: List[str] = []
    if model_name:
        parts.append(model_name)
    if session_5h is not None:
        cd = _format_countdown_compact(session_5h.get("resets_at"), now)
        parts.append(f"5h {session_5h['remaining_pct']:.0f}%" + (f" ({cd})" if cd else ""))
    if weekly is not None:
        cd = _format_countdown_compact(weekly.get("resets_at"), now)
        parts.append(f"7d {weekly['remaining_pct']:.0f}%" + (f" ({cd})" if cd else ""))
    if weekly_argon is not None:
        parts.append(f"Argon {weekly_argon['remaining_pct']:.0f}%")
    return " | ".join(parts)


def _extract_claude_limit(obj: Any, now: float) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    used = _clamp_pct(_get_float(obj, "used_percentage", "usedPercentage", "used_pct", "utilization"))
    rem = _clamp_pct(_get_float(obj, "remaining_percentage", "remainingPercentage", "remaining_pct"))
    if rem is None:
        frac = _get_float(obj, "remaining_fraction", "remainingFraction")
        if frac is not None:
            rem = _clamp_pct(frac * 100.0 if frac <= 1.0 else frac)
    if rem is None and used is not None:
        rem = _clamp_pct(100.0 - used)
    if used is None and rem is not None:
        used = _clamp_pct(100.0 - rem)
    if rem is None:
        return None
    resets = _parse_ts(
        _get_first(obj, "resets_at", "resetsAt", "reset_time"),
        _get_first(obj, "reset_in_seconds", "resets_in_seconds"),
        now,
    )
    return {"remaining_pct": rem, "used_pct": used, "resets_at": resets}


def _extract_fable_from_model_scoped(scoped_obj: Any, now: float) -> Optional[Dict[str, Any]]:
    if isinstance(scoped_obj, dict):
        for k, v in scoped_obj.items():
            if "fable" in str(k).lower():
                parsed = _extract_claude_limit(v, now)
                if parsed is not None:
                    return parsed
        return None
    if isinstance(scoped_obj, list):
        for item in scoped_obj:
            if not isinstance(item, dict):
                continue
            ident = str(
                item.get("model") or item.get("name") or item.get("id") or item.get("bucket") or ""
            ).lower()
            if "fable" in ident:
                parsed = _extract_claude_limit(item, now)
                if parsed is not None:
                    return parsed
    return None


def _handle_claude(payload: Dict[str, Any], state_path: Path, now: float) -> str:
    model = payload.get("model")
    if isinstance(model, dict):
        model_name = str(model.get("display_name") or model.get("id") or "")
    elif isinstance(model, str):
        model_name = model
    else:
        model_name = ""

    ctx = payload.get("context_window")
    ctx_used = _clamp_pct(_get_float(ctx, "used_percentage")) if isinstance(ctx, dict) else None

    cost = payload.get("cost")
    total_cost = _get_float(cost, "total_cost_usd") if isinstance(cost, dict) else None

    rl = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else None
    if rl is None and isinstance(payload.get("rateLimits"), dict):
        rl = payload.get("rateLimits")

    session_5h: Optional[Dict[str, Any]] = None
    weekly: Optional[Dict[str, Any]] = None
    weekly_fable: Optional[Dict[str, Any]] = None
    extra_buckets: Dict[str, Any] = {}

    if isinstance(rl, dict):
        session_5h = _extract_claude_limit(rl.get("five_hour") or rl.get("fiveHour"), now)
        weekly = _extract_claude_limit(rl.get("seven_day") or rl.get("sevenDay"), now)
        weekly_fable = _extract_claude_limit(
            rl.get("seven_day_fable") or rl.get("sevenDayFable") or rl.get("fable"), now
        )
        for k, v in rl.items():
            lk = str(k).lower()
            if lk in ("five_hour", "fivehour", "seven_day", "sevenday"):
                continue
            if lk in ("model_scoped", "modelscoped"):
                scoped_fb = _extract_fable_from_model_scoped(v, now)
                if scoped_fb is not None and weekly_fable is None:
                    weekly_fable = scoped_fb
                continue
            parsed = _extract_claude_limit(v, now)
            if parsed is not None:
                if "fable" in lk and weekly_fable is None:
                    weekly_fable = parsed
                elif "fable" not in lk:
                    extra_buckets[str(k)] = parsed

    has_quota = any(x is not None for x in (weekly, weekly_fable, session_5h)) or bool(extra_buckets)
    patch: Dict[str, Any] = {"updated_at": now}
    if has_quota:
        patch["source"] = "claude_code_statusline"
        patch["quota_updated_at"] = now
    if model_name:
        patch["model"] = model_name
    if ctx_used is not None:
        patch["context_used_pct"] = ctx_used
    if total_cost is not None:
        patch["total_cost_usd"] = total_cost
    if weekly is not None:
        patch["weekly"] = weekly
    if weekly_fable is not None:
        patch["weekly_fable"] = weekly_fable
    if session_5h is not None:
        patch["session_5h"] = session_5h
    if extra_buckets:
        patch["extra_buckets"] = extra_buckets

    _update_state(state_path, "claude", patch)

    parts: List[str] = []
    if model_name:
        parts.append(model_name)
    if ctx_used is not None:
        parts.append(f"Ctx {ctx_used:.0f}%")
    if session_5h is not None:
        cd = _format_countdown_compact(session_5h.get("resets_at"), now)
        parts.append(f"5h {session_5h['remaining_pct']:.0f}%" + (f" ({cd})" if cd else ""))
    if weekly is not None:
        cd = _format_countdown_compact(weekly.get("resets_at"), now)
        parts.append(f"7d {weekly['remaining_pct']:.0f}%" + (f" ({cd})" if cd else ""))
    if weekly_fable is not None:
        parts.append(f"Fable {weekly_fable['remaining_pct']:.0f}%")
    return " | ".join(parts)


def main() -> int:
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    mode: Optional[str] = None
    custom_state_path: Optional[str] = None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        a = argv[i].strip().lower()
        if a == "--claude":
            mode = "claude"
        elif a in ("--agy", "--antigravity"):
            mode = "antigravity"
        elif a == "--state-path" and i + 1 < len(argv):
            custom_state_path = argv[i + 1]
            i += 1
        i += 1

    if not mode:
        return 0

    try:
        raw = sys.stdin.read()
    except Exception:
        return 0
    if not raw or not raw.strip():
        return 0

    try:
        payload = json.loads(raw)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    state_path = Path(custom_state_path) if custom_state_path else (_data_dir() / "quota_state.json")
    now = time.time()

    try:
        if os.environ.get("AIUSAGEBAR_DEBUG") == "1":
            _write_safe_debug_schema(state_path, mode, payload, now)
        if mode == "antigravity":
            out = _handle_agy(payload, state_path, now)
        else:
            out = _handle_claude(payload, state_path, now)
        if out:
            print(out)
    except Exception as exc:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path.parent / "hook_error.log", "a", encoding="utf-8") as ef:
                ef.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ({mode}) {exc}\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
