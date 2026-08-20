"""
Сборка .hm пакетов плагинов Home.Media.

Надёжный вариант (python zipfile), совместимый с Linux:
  python build_packages.py            # собрать все плагины из plugins/
  python build_packages.py example    # собрать только example

Структура каждого пакета (в корне zip):
  manifest.json
  requirements.txt
  app/...
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

PLUGINS_ROOT = Path(__file__).resolve().parent

IGNORED_DIRS = {".venv", "__pycache__", "data", "node_modules"}
IGNORED_SUFFIXES = {".pyc", ".log", ".db"}


def build_plugin(name: str) -> Path | None:
    src = PLUGINS_ROOT / name
    if not src.is_dir():
        print(f"✗ {name}: папка не найдена")
        return None
    manifest = src / "manifest.json"
    entry = src / "app" / "main.py"
    if not manifest.exists():
        print(f"✗ {name}: нет manifest.json")
        return None
    if not entry.exists():
        print(f"✗ {name}: нет app/main.py")
        return None

    out = PLUGINS_ROOT / f"{name}.hm"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(src.rglob("*")):
            if file.is_dir():
                continue
            rel = file.relative_to(src)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            if file.suffix in IGNORED_SUFFIXES:
                continue
            zf.write(file, rel.as_posix())

    size = out.stat().st_size / 1024
    print(f"OK {name}.hm  ({size:.1f} KB)")
    return out


def main() -> None:
    targets = sys.argv[1:] or [
        d.name for d in PLUGINS_ROOT.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    ]
    for name in targets:
        build_plugin(name)
    print("Готово.")


if __name__ == "__main__":
    main()
