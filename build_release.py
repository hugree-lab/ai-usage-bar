"""Build pipeline to produce standalone shareable Windows installer `dist/AIUsageBar-Setup.exe`."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
CSC_EXE = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")


def generate_app_icon(out_ico: Path) -> None:
    """Render a crisp 256x256 dark rounded icon with dual Antigravity/Claude quota bars."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Outer squircle badge
    draw.rounded_rectangle(
        [10, 10, size - 11, size - 11],
        radius=54,
        fill=(18, 22, 31, 255),
        outline=(56, 189, 248, 220),
        width=8,
    )

    # Subtle inner card
    draw.rounded_rectangle(
        [34, 42, size - 35, size - 43],
        radius=28,
        fill=(26, 32, 46, 255),
        outline=(48, 60, 84, 255),
        width=3,
    )

    # Top bar (Antigravity signature royal blue, ~82%)
    draw.rounded_rectangle([56, 76, 200, 114], radius=16, fill=(38, 46, 65, 255))
    draw.rounded_rectangle([56, 76, 174, 114], radius=16, fill=(79, 156, 249, 255))

    # Bottom bar (Claude signature terracotta coral, ~68%)
    draw.rounded_rectangle([56, 142, 200, 180], radius=16, fill=(38, 46, 65, 255))
    draw.rounded_rectangle([56, 142, 156, 180], radius=16, fill=(224, 122, 95, 255))

    out_ico.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        str(out_ico),
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"[OK] Generated icon: {out_ico}")


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(">>", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def main() -> int:
    wizard_only = "--wizard-only" in sys.argv
    ASSETS.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(parents=True, exist_ok=True)

    icon_path = ASSETS / "app_icon.ico"
    payload_zip = BUILD / "payload.zip"
    pyinstaller = shutil.which("pyinstaller") or str(Path(sys.executable).parent / "Scripts" / "pyinstaller.exe")

    excludes = [
        "--exclude-module", "numpy",
        "--exclude-module", "scipy",
        "--exclude-module", "pandas",
        "--exclude-module", "matplotlib",
        "--exclude-module", "setuptools",
        "--exclude-module", "pkg_resources",
        "--exclude-module", "pytest",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "doctest",
        "--exclude-module", "PyQt5",
        "--exclude-module", "PySide6",
    ]

    if not wizard_only or not payload_zip.exists() or not icon_path.exists():
        generate_app_icon(icon_path)

        # 1. Compile zero-dependency native .NET hook binary (quota_hook.exe, ~18KB)
        #    CRITICAL: Use /target:winexe (GUI subsystem) so invoking quota_hook.exe from
        #    GUI hosts (Claude Desktop, Antigravity, ConPTY children) NEVER flashes a console
        #    window while preserving 100% identical stdin/stdout pipe I/O.
        hook_exe = BUILD / "quota_hook.exe"
        run([
            str(CSC_EXE),
            "/nologo",
            "/optimize+",
            "/target:winexe",
            "/r:System.Web.Extensions.dll",
            f"/out:{hook_exe}",
            str(ROOT / "hooks" / "QuotaHook.cs"),
        ])
        print(f"[OK] Built native hook: {hook_exe} ({hook_exe.stat().st_size} bytes)")

        # 2. Build standalone HUD app (--onedir for instant startup)
        app_dist = BUILD / "dist_app"
        app_work = BUILD / "work_app"
        shutil.rmtree(app_dist, ignore_errors=True)
        shutil.rmtree(app_work, ignore_errors=True)

        run([
            pyinstaller,
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name", "AIUsageBar",
            "--icon", str(icon_path),
            "--hidden-import", "PIL.IcoImagePlugin",
            "--hidden-import", "PIL.PngImagePlugin",
            "--hidden-import", "PIL.BmpImagePlugin",
            *excludes,
            "--distpath", str(app_dist),
            "--workpath", str(app_work),
            "--specpath", str(BUILD),
            str(ROOT / "hud_app.py"),
        ])

        app_folder = app_dist / "AIUsageBar"
        shutil.copy2(hook_exe, app_folder / "quota_hook.exe")
        shutil.copy2(icon_path, app_folder / "app_icon.ico")

        # 3. Package app_folder into compressed payload.zip
        if payload_zip.exists():
            payload_zip.unlink()
        with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for file_path in sorted(app_folder.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(app_folder)
                    zf.write(file_path, arcname)
        print(f"[OK] Packed payload.zip: {payload_zip.stat().st_size / (1024 * 1024):.2f} MB")

    # 4. Build standalone single-EXE Setup Wizard (`dist/AIUsageBar-Setup.exe`)
    setup_work = BUILD / "work_setup"
    shutil.rmtree(setup_work, ignore_errors=True)
    run([
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "AIUsageBar-Setup",
        "--icon", str(icon_path),
        *excludes,
        "--distpath", str(DIST),
        "--workpath", str(setup_work),
        "--specpath", str(BUILD),
        "--add-data", f"{payload_zip};.",
        "--add-data", f"{icon_path};.",
        str(ROOT / "installer_wizard.py"),
    ])

    final_exe = DIST / "AIUsageBar-Setup.exe"
    print(f"\n=== BUILD SUCCESS ===")
    print(f"Shareable installer: {final_exe} ({final_exe.stat().st_size / (1024 * 1024):.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
