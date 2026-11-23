"""Build standalone macOS `AIUsageBar.app` & `.dmg` bundle on a macOS machine.

Run on macOS:
    python3 macos/build_macos.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build_macos"


def generate_macos_icns(out_icns: Path) -> bool:
    """Render a crisp 512x512 rounded squircle icon and save as macOS .icns."""
    try:
        size = 512
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle(
            [24, 24, size - 25, size - 25],
            radius=110,
            fill=(18, 22, 31, 255),
            outline=(56, 189, 248, 220),
            width=14,
        )
        draw.rounded_rectangle(
            [72, 88, size - 73, size - 89],
            radius=56,
            fill=(26, 32, 46, 255),
            outline=(48, 60, 84, 255),
            width=6,
        )
        # Top bar (Antigravity blue)
        draw.rounded_rectangle([114, 154, 398, 228], radius=32, fill=(38, 46, 65, 255))
        draw.rounded_rectangle([114, 154, 346, 228], radius=32, fill=(79, 156, 249, 255))
        # Bottom bar (Claude coral)
        draw.rounded_rectangle([114, 284, 398, 358], radius=32, fill=(38, 46, 65, 255))
        draw.rounded_rectangle([114, 284, 310, 358], radius=32, fill=(224, 122, 95, 255))

        out_icns.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_icns), format="ICNS")
        print(f"[OK] Generated macOS icon: {out_icns}")
        return True
    except Exception as exc:
        print(f"[Warn] Could not generate .icns icon: {exc}")
        return False


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

    icns_path = BUILD / "app_icon.icns"
    has_icns = generate_macos_icns(icns_path)

    cmd = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "AIUsageBar",
        "--osx-bundle-identifier", "com.hugreelab.aiusagebar",
        "--add-data", f"{ROOT / 'macos' / 'quota_hook.py'}:macos",
        "--hidden-import", "PIL.PngImagePlugin",
        "--hidden-import", "PIL.IcoImagePlugin",
        "--hidden-import", "PIL.ImageTk",
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "work"),
        "--specpath", str(BUILD),
    ]
    if has_icns and icns_path.exists():
        cmd.extend(["--icon", str(icns_path)])
    cmd.append(str(ROOT / "hud_app.py"))

    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    app_bundle = DIST / "AIUsageBar.app"
    dmg_path = DIST / "AIUsageBar-macOS.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    if app_bundle.exists():
        # Ensure ad-hoc signature is valid across the entire bundle
        if shutil.which("codesign"):
            subprocess.run(
                ["codesign", "--force", "--deep", "--sign", "-", str(app_bundle)],
                check=False,
            )

    if app_bundle.exists() and shutil.which("hdiutil"):
        # Stage AIUsageBar.app inside a parent folder so hdiutil places the .app bundle
        # itself (NOT its inner Contents/ folder) at the root of the DMG volume.
        staging = BUILD / "dmg_staging"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        shutil.copytree(app_bundle, staging / "AIUsageBar.app", symlinks=True)
        os.symlink("/Applications", staging / "Applications")

        install_note = staging / "Install Guide (macOS).txt"
        install_note.write_text(
            "AI Usage Bar — macOS Installation Guide\n"
            "=======================================\n\n"
            "1. Drag 'AIUsageBar.app' into the 'Applications' folder.\n"
            "2. This is an open-source build without paid Apple Notarization.\n"
            "   If macOS Gatekeeper blocks opening it, run this once in Terminal:\n\n"
            "     xattr -cr /Applications/AIUsageBar.app\n\n"
            "   Then open AIUsageBar from Applications.\n\n"
            "[한국어 안내]\n"
            "1. 'AIUsageBar.app'을 'Applications(응용 프로그램)' 폴더로 드래그하세요.\n"
            "2. 무료 오픈소스 빌드(Apple 유료 공증 미적용)이므로 최초 실행 시 보안 경고가\n"
            "   뜨면 터미널에서 아래 명령을 한 번 실행한 뒤 다시 열어주세요:\n\n"
            "     xattr -cr /Applications/AIUsageBar.app\n",
            encoding="utf-8",
        )

        subprocess.run(
            [
                "hdiutil", "create",
                "-volname", "AI Usage Bar",
                "-srcfolder", str(staging),
                "-ov", "-format", "UDZO",
                str(dmg_path),
            ],
            check=True,
        )
        shutil.rmtree(staging, ignore_errors=True)
        print(f"[OK] Created macOS DMG: {dmg_path}")
    else:
        print(f"[OK] Created macOS App Bundle: {app_bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
