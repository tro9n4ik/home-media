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
import struct
import zlib
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
    
    # Write ZIP manually with proper UTF-8 support
    import zlib
    import struct
    
    # DOS time format
    dos_date = (FIXED_TIME[0] - 1980) << 9 | FIXED_TIME[1] << 5 | FIXED_TIME[2]
    dos_time = FIXED_TIME[3] << 11 | FIXED_TIME[4] << 5 | (FIXED_TIME[5] // 2)
    
    local_headers = []
    central_dirs = []
    offset = 0
    
    for file, arcname in files:
        data = file.read_bytes()
        arcname_bytes = arcname.encode('utf-8')
        crc32 = zlib.crc32(data) & 0xffffffff
        file_size = len(data)
        
        # Local file header
        local_header = struct.pack(
            '<IHHHHHIIIHH',
            0x04034b50,  # Local file header signature
            20,          # Version needed
            0x0800,      # General purpose bit flag (UTF-8)
            0,           # Compression method (stored)
            dos_time,    # File time
            dos_date,    # File date
            zlib.crc32(data) & 0xffffffff,  # CRC-32
            len(data),   # Compressed size
            len(data),   # Uncompressed size
            len(arcname.encode('utf-8')),  # File name length
            0            # Extra field length
        )
        
        # Central directory entry (46 bytes)
        central_dir = struct.pack(
            '<IHHHHHIIIHHHHHII',
            0x02014b50,  # Central directory signature
            20,          # Version made by
            20,          # Version needed
            0x0800,      # General purpose bit flag (UTF-8)
            0,           # Compression method (stored)
            dos_time,    # File time
            dos_date,    # File date
            zlib.crc32(data) & 0xffffffff,  # CRC-32
            len(data),   # Compressed size
            len(data),   # Uncompressed size
            len(arcname.encode('utf-8')),  # File name length
            0,           # Extra field length
            0,           # File comment length
            0,           # Disk number start
            0,           # Internal file attributes
            0o644 << 16, # External file attributes
            0            # Relative offset of local header (placeholder)
        )
        
        local_files = (arcname, data, zlib.crc32(data) & 0xffffffff)
        # We'll build in memory
        local_files_data.append((arcname, data, zlib.crc32(data) & 0xffffffff))
        central_dir_data.append((arcname, data, zlib.crc32(data) & 0xffffffff))
    
    # Write ZIP
    out_path = PLUGINS_ROOT / f"{name}.hm"
    with open(out_path, 'wb') as f:
        # Write local file headers and file data
        offset = 0
        central_dirs = []
        for arcname, data, crc32 in local_files_data:
            arcname_bytes = arcname.encode('utf-8')
            local_header = struct.pack(
                '<IHHHHHIIIHH',
                0x04034b50,  # Local file header signature
                20,          # Version needed
                0x0800,      # General purpose bit flag (UTF-8)
                0,           # Compression method (stored)
                dos_time,    # File time
                dos_date,    # File date
                zlib.crc32(data) & 0xffffffff,
                len(data),
                len(data),
                len(arcname.encode('utf-8')),
                0
            )
            f.write(struct.pack('<IHHHHHIIIHH',
                0x04034b50, 20, 0x0800, 0, dos_time, dos_date,
                zlib.crc32(data) & 0xffffffff, len(data), len(data),
                len(arcname.encode('utf-8')), 0
            ))
            f.write(arcname.encode('utf-8'))
            f.write(data)
        
        # Central directory
        central_dir_start = f.tell()
        for arcname, data, crc32 in local_files_data:
            arcname_b = arcname.encode('utf-8')
            central_dir = struct.pack(
                '<IHHHHHIIIHHHHHII',
                0x02014b50, 20, 20, 0x0800, 0, dos_time, dos_date,
                zlib.crc32(data) & 0xffffffff, len(data), len(data),
                len(arcname.encode('utf-8')), 0, 0, 0, 0, 0o644 << 16, 0
            )
            f.write(central_dir)
            f.write(arcname.encode('utf-8'))
        
        central_dir_end = f.tell()
        central_dir_size = f.tell() - central_dir_start
        
        # End of central directory
        eocd = struct.pack(
            '<HHHHHHIIH',
            0x06054b50, 0, 0, len(files), len(files),
            f.tell() - central_dir_start,  # central dir size
            f.tell() - 4 - (f.tell() - central_dir_start),  # offset of central dir
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