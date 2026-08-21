"""
Сборка .hm пакетов плагинов Home.Media.

Ручной ZIP writer с поддержкой UTF-8 (исправляет коррупцию кириллицы на Windows):
  python build_packages.py            # собрать все плагины из plugins/
  python build_packages.py example    # собрать только example

Структура каждого пакета (в корне zip):
  manifest.json
  requirements.txt
  app/...
"""

from __future__ import annotations

import sys
import struct
import zlib
from pathlib import Path

PLUGINS_ROOT = Path(__file__).resolve().parent

IGNORED_DIRS = {".venv", "__pycache__", "data", "node_modules"}
IGNORED_SUFFIXES = {".pyc", ".log", ".db"}

FIXED_TIME = (2024, 1, 1, 0, 0, 0)


def build_plugin(name: str) -> Path | None:
    src = PLUGINS_ROOT / name
    if not src.is_dir():
        print(f"[ERROR] {name}: folder not found")
        return None
    manifest = src / "manifest.json"
    entry = src / "app" / "main.py"
    if not manifest.exists():
        print(f"[ERROR] {name}: missing manifest.json")
        return None
    if not entry.exists():
        print(f"[ERROR] {name}: missing app/main.py")
        return None

    out = PLUGINS_ROOT / f"{name}.hm"

    files = []
    for file in sorted(src.rglob("*")):
        if file.is_dir():
            continue
        rel = file.relative_to(src)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if file.suffix in IGNORED_SUFFIXES:
            continue
        files.append((file, rel.as_posix()))

    dos_date = (FIXED_TIME[0] - 1980) << 9 | FIXED_TIME[1] << 5 | FIXED_TIME[2]
    dos_time = FIXED_TIME[3] << 11 | FIXED_TIME[4] << 5 | (FIXED_TIME[5] // 2)

    file_records = []
    for file, arcname in files:
        data = file.read_bytes()
        arcname_bytes = arcname.encode('utf-8')
        crc32 = zlib.crc32(data) & 0xffffffff
        file_records.append({
            'arcname': arcname,
            'arcname_bytes': arcname_bytes,
            'data': data,
            'crc32': crc32,
            'size': len(data),
        })

    out_path = PLUGINS_ROOT / f"{name}.hm"
    local_headers = []

    with open(out_path, 'wb') as f:
        for rec in file_records:
            local_header = struct.pack(
                '<IHHHHHIIIHH',
                0x04034b50,
                20,
                0x0800,
                0,
                dos_time,
                dos_date,
                rec['crc32'],
                rec['size'],
                rec['size'],
                len(rec['arcname_bytes']),
                0
            )
            f.write(local_header)
            f.write(rec['arcname_bytes'])
            f.write(rec['data'])
            local_headers.append((f.tell() - len(local_header) - len(rec['arcname_bytes']) - rec['size'], rec))

        central_dir_start = f.tell()
        for offset, rec in local_headers:
            central_dir = struct.pack(
                '<IHHHHHHIIIHHHHHII',
                0x02014b50,
                20,
                20,
                0x0800,
                0,
                dos_time,
                dos_date,
                rec['crc32'],
                rec['size'],
                rec['size'],
                len(rec['arcname_bytes']),
                0,
                0,
                0,
                0,
                0o644 << 16,
                offset
            )
            f.write(central_dir)
            f.write(rec['arcname_bytes'])

        central_dir_end = f.tell()
        central_dir_size = central_dir_end - central_dir_start

        eocd = struct.pack(
            '<IHHHHIIH',
            0x06054b50,
            0,
            0,
            len(file_records),
            len(file_records),
            central_dir_size,
            central_dir_start,
            0
        )
        f.write(eocd)

    size = out_path.stat().st_size / 1024
    print(f"[OK] {name}.hm  ({size:.1f} KB)")
    return out_path


def main() -> None:
    targets = sys.argv[1:] or [
        d.name for d in PLUGINS_ROOT.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    ]
    for name in targets:
        build_plugin(name)
    print("Done.")


if __name__ == "__main__":
    main()