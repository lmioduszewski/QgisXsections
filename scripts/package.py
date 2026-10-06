"""Build the installable plugin zip: dist/xsections-<version>.zip, with one top folder, xsections/.

Standard library only; any Python 3.9 or newer (QGIS is not needed):

    python scripts/package.py              -> dist/xsections-<version>.zip
    python scripts/package.py --out DIR    -> DIR/xsections-<version>.zip

The version comes from xsections/metadata.txt. QGIS installs the zip with Plugins > Manage and
Install Plugins > Install from ZIP; the folder name inside it (xsections) is the plugin id.
The repository's LICENSE (GPL-2.0) is copied in as xsections/LICENSE, where plugins.qgis.org
expects it. After writing, the zip is checked: metadata.txt, __init__.py and LICENSE present, no
bytecode or tests,
and no absolute or user-specific paths in any file. A zip that fails is deleted (exit status 1).
"""
from __future__ import annotations

import argparse
import configparser
import fnmatch
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = "xsections"
LICENSE = ROOT / "LICENSE"

# Not needed at runtime: never shipped.
SKIP_DIRS = {"__pycache__", "tests", "test", ".git", ".idea", ".vscode", ".pytest_cache", ".mypy_cache"}
SKIP_FILES = ["*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", "desktop.ini", "*.aux.xml", "*.bak", "*.orig",
              "*.tmp", "*.swp", "*~", ".gitignore"]

# Text no shipped file may contain: absolute paths, user folders and this machine's scratch areas.
FORBIDDEN = {
    "an absolute Windows path": r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]",     # C:/..., C:\...
    "a user folder": r"(?<![\w.])/(?:Users|home)/",                # /Users/..., /home/... (not in URLs)
    "'lukem'": r"lukem",
    "'AppData'": r"AppData[\\/]",
    "'scratchpad'": r"scratchpad",
}


def read_version(plugin_dir: Path = ROOT / PLUGIN) -> str:
    cp = configparser.ConfigParser()
    with open(plugin_dir / "metadata.txt", encoding="utf-8") as fh:
        cp.read_file(fh)
    version = cp.get("general", "version", fallback="").strip()
    if not re.fullmatch(r"[0-9A-Za-z.+-]+", version):
        raise SystemExit(f"metadata.txt: bad or missing version '{version}'")
    return version


def plugin_files(plugin_dir: Path = ROOT / PLUGIN):
    """(files to ship, files skipped), both sorted, as paths relative to plugin_dir."""
    ship, skipped = [], []
    for path in sorted(plugin_dir.rglob("*")):
        rel = path.relative_to(plugin_dir)
        if not path.is_file() or "__pycache__" in rel.parts:
            continue
        if SKIP_DIRS.intersection(rel.parts[:-1]) or any(fnmatch.fnmatch(path.name, p) for p in SKIP_FILES):
            skipped.append(rel)
        else:
            ship.append(rel)
    return ship, skipped


def build(out_dir: Path = ROOT / "dist", plugin_dir: Path = ROOT / PLUGIN) -> Path:
    """Write <out_dir>/xsections-<version>.zip and return its path (not yet checked)."""
    ship, _ = plugin_files(plugin_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{PLUGIN}-{read_version(plugin_dir)}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ship:
            zf.write(plugin_dir / rel, f"{PLUGIN}/{rel.as_posix()}")
        if LICENSE.is_file() and f"{PLUGIN}/LICENSE" not in zf.namelist():
            zf.write(LICENSE, f"{PLUGIN}/LICENSE")
    return zip_path


def check(zip_path: Path) -> list:
    """Problems with the zip, as sentences; [] when it is fit to install."""
    problems = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for required in (f"{PLUGIN}/metadata.txt", f"{PLUGIN}/__init__.py", f"{PLUGIN}/LICENSE"):
            if required not in names:
                problems.append(f"missing {required}")
        # QGIS takes the first name ending in metadata.txt as <plugin id>/metadata.txt
        if [n for n in names if n.endswith("metadata.txt")] != [f"{PLUGIN}/metadata.txt"]:
            problems.append("there must be exactly one metadata.txt, at xsections/metadata.txt")
        for name in names:
            parts = name.split("/")
            if parts[0] != PLUGIN or ".." in parts or ":" in name or "\\" in name:
                problems.append(f"{name}: not a relative path inside {PLUGIN}/")
            if name.endswith((".pyc", ".pyo")) or "__pycache__" in parts:
                problems.append(f"{name}: bytecode")
            if SKIP_DIRS.intersection(parts[1:-1]):
                problems.append(f"{name}: not needed at runtime")
            text = zf.read(name).decode("latin-1")
            for what, pattern in FORBIDDEN.items():
                m = re.search(pattern, text, re.IGNORECASE)
                if m:
                    line = text.count("\n", 0, m.start()) + 1
                    problems.append(f"{name}, line {line}: contains {what} ({m.group(0)!r})")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the XSections plugin zip for Install from ZIP.")
    ap.add_argument("--out", type=Path, default=ROOT / "dist", help="output folder (default: dist)")
    args = ap.parse_args(argv)

    zip_path = build(args.out)
    problems = check(zip_path)
    if problems:
        zip_path.unlink()
        print(f"Not built: {zip_path.name} failed its checks:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    _, skipped = plugin_files()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
    print(f"Built {zip_path} ({zip_path.stat().st_size / 1024:.1f} KB, {len(infos)} files):")
    for info in infos:
        print(f"  {info.file_size:>9,}  {info.filename}")
    if skipped:
        print("Left out:", *(f"{PLUGIN}/{p.as_posix()}" for p in skipped), sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
