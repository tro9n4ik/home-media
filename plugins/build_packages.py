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

# Фиксированная дата записей: .hm стабилен между сборками (иначе каждая
# сборка меняет zip-таймстампы и рождает пустые диффы в git).
FIXED_TIME = (2024, 1, 1, 0, 0, 0)


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
            zi = zipfile.ZipInfo(rel.as_posix(), date_time=FIXED_TIME)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, file.read_bytes())

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
