"""CLI helper to configure or remove official statusLine hooks for Claude Code and Antigravity CLI."""

from __future__ import annotations

import argparse

from hooks_manager import (
    AGY_SETTINGS,
    CLAUDE_SETTINGS,
    get_hook_status,
    install_agy_hook,
    install_claude_hook,
    uninstall_agy_hook,
    uninstall_claude_hook,
)
from state_store import is_startup_enabled, set_startup_enabled


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure official statusLine hooks for AI Usage Bar")
    parser.add_argument("--install-claude", action="store_true", help="Configure Claude Code statusLine")
    parser.add_argument("--uninstall-claude", action="store_true", help="Remove Claude Code statusLine")
    parser.add_argument("--install-agy", action="store_true", help="Configure Antigravity CLI (agy) statusLine")
    parser.add_argument("--uninstall-agy", action="store_true", help="Remove Antigravity CLI (agy) statusLine")
    parser.add_argument("--enable-startup", action="store_true", help="Run AI Usage Bar at Windows login")
    parser.add_argument("--disable-startup", action="store_true", help="Disable auto-start at Windows login")
    parser.add_argument("--status", action="store_true", help="Show current hook & startup status")
    args = parser.parse_args()

    ran = False
    if args.install_claude:
        ok, msg = install_claude_hook()
        print(("[OK] " if ok else "[ERR] ") + msg)
        ran = True
    if args.uninstall_claude:
        ok, msg = uninstall_claude_hook()
        print(("[OK] " if ok else "[ERR] ") + msg)
        ran = True
    if args.install_agy:
        ok, msg = install_agy_hook()
        print(("[OK] " if ok else "[ERR] ") + msg)
        ran = True
    if args.uninstall_agy:
        ok, msg = uninstall_agy_hook()
        print(("[OK] " if ok else "[ERR] ") + msg)
        ran = True
    if args.enable_startup:
        set_startup_enabled(True)
        print("[OK] Windows login auto-start enabled")
        ran = True
    if args.disable_startup:
        set_startup_enabled(False)
        print("[OK] Windows login auto-start disabled")
        ran = True

    if args.status or not ran:
        st = get_hook_status()
        print(f"Claude Code CLI        : {'INSTALLED' if st['claude_cli'] else 'not found'}")
        print(f"Claude Code statusLine : {'CONNECTED' if st['claude_hook'] else 'not configured'} ({CLAUDE_SETTINGS})")
        print(f"Antigravity CLI (agy)  : {'INSTALLED' if st['agy_cli'] else 'not found'}")
        print(f"Antigravity statusLine : {'CONNECTED' if st['agy_hook'] else 'not configured'} ({AGY_SETTINGS})")
        print(f"Windows Auto-start     : {'ON' if is_startup_enabled() else 'OFF'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
