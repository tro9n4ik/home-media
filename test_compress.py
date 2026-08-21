import tempfile, pathlib, subprocess

src = pathlib.Path(r'D:\new project\hm3-syn\plugins\home_assistant')
with tempfile.TemporaryDirectory() as tmpdir:
    tmp_src = pathlib.Path(tmpdir) / 'home_assistant'
    tmp_src.mkdir(parents=True)
    for file in sorted(src.rglob('*')):
        if file.is_dir(): continue
        rel = file.relative_to(src)
        dest = tmp_src / file.relative_to(src)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(file.read_bytes())
    
    out = pathlib.Path(r'D:\new project\hm3-syn\plugins\test3.zip')
    result = subprocess.run([
        'powershell', '-Command',
        f'Compress-Archive -Path "{tmp_src}\\*" -DestinationPath "{pathlib.Path(r"D:\new project\hm3-syn\plugins\test3.zip")}" -CompressionLevel Optimal'
    ], capture_output=True, timeout=60)
    print('returncode:', result.returncode)
    print('stdout:', result.stdout.decode('utf-8', errors='replace')[:200])
    print('stderr:', result.stderr.decode('utf-8', errors='replace')[:200])