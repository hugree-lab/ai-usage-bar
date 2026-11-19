"""Build standalone macOS `AIUsageBar.app` & `.dmg` bundle on a macOS machine.

Run on macOS:
    python3 macos/build_macos.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build_macos"


def main() -> int:
    if sys.platform != "darwin":
        print("[안내] macOS .app / .dmg 빌드는 macOS 환경에서만 실행할 수 있습니다.")
        return 1

    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        print("[오류] pyinstaller가 설치되어 있지 않습니다: pip install pyinstaller pillow")
        return 1

    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    cmd = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "AIUsageBar",
        "--osx-bundle-identifier", "com.hugreelab.aiusagebar",
        "--add-data", f"{ROOT / 'macos' / 'quota_hook.py'}:macos",
        "--hidden-import", "PIL.PngImagePlugin",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
        str(ROOT / "hud_app.py"),
    ]
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    app_bundle = DIST / "AIUsageBar.app"
    dmg_path = DIST / "AIUsageBar-macOS.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    if app_bundle.exists() and shutil.which("hdiutil"):
        subprocess.run(
            [
                "hdiutil", "create",
                "-volname", "AI Usage Bar",
                "-srcfolder", str(app_bundle),
                "-ov", "-format", "UDZO",
                str(dmg_path),
            ],
            check=True,
        )
        print(f"[OK] Created macOS DMG: {dmg_path}")
    else:
        print(f"[OK] Created macOS App Bundle: {app_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
