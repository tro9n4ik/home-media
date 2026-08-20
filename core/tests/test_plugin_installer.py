"""Тесты plugin_installer.py — приоритет №1 из TODO_TESTS.md."""
import json
import sys
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import plugin_installer as inst
from app.services.plugin_installer import (
    PackageError,
    InstallError,
    validate_manifest,
    unpack,
    setup_venv,
    install_deps,
    verify_deps,
    venv_bin_dir,
    venv_python,
    venv_dir,
)
from conftest import make_manifest


# ── validate_manifest ─────────────────────────────────────────────────────────

def test_validate_ok():
    validate_manifest(make_manifest())
    validate_manifest(make_manifest(id="my-plugin", version="2.0.0"))
    validate_manifest(make_manifest(id="my_plugin"))
    validate_manifest(make_manifest(id="a1b2c3"))


@pytest.mark.parametrize("missing", [
    ["id"], ["name"], ["version"], ["id", "name"],
])
def test_validate_missing_fields(missing):
    m = make_manifest()
    for k in missing:
        m.pop(k)
    with pytest.raises(PackageError):
        validate_manifest(m)


@pytest.mark.parametrize("bad_id", ["../x", "a b", "a/b", "a$b", "..", ".hidden", "май id"])
def test_validate_bad_id(bad_id):
    with pytest.raises(PackageError):
        validate_manifest(make_manifest(id=bad_id))


def test_validate_unicode_id_allowed():
    # контракт кода: кириллица/дефисы допускаются (isalnum после удаления - и _)
    validate_manifest(make_manifest(id='дом-в'))
    validate_manifest(make_manifest(id='--x'))


def test_validate_port_forbidden():
    with pytest.raises(PackageError):
        validate_manifest(make_manifest(port=8100))


@pytest.mark.parametrize("bad_hint", [1023, 70000, 65536, "8100", None, 0, -5])
def test_validate_bad_port_hint(bad_hint):
    with pytest.raises(PackageError):
        validate_manifest(make_manifest(port_hint=bad_hint))


@pytest.mark.parametrize("hint", [1024, 65535, 8100, 8123])
def test_validate_ok_port_hint(hint):
    validate_manifest(make_manifest(port_hint=hint))


# ── unpack ────────────────────────────────────────────────────────────────────

def test_unpack_minimal(tmp_path, build_hm):
    hm = build_hm({
        "manifest.json": json.dumps(make_manifest()),
        "app/main.py": "print('hi')",
        "app/__init__.py": "",
        "requirements.txt": "fastapi\n",
    })
    manifest = unpack(hm, tmp_path)
    assert manifest["id"] == "demo"

    dest = tmp_path / "demo"
    assert (dest / "app" / "main.py").read_text() == "print('hi')"
    assert (dest / "requirements.txt").exists()


def test_unpack_path_traversal(tmp_path, build_hm, monkeypatch):
    hm = build_hm({
        "manifest.json": json.dumps(make_manifest()),
        "../evil.txt": "boom",
    })
    with pytest.raises(PackageError):
        unpack(hm, tmp_path)
    assert not (tmp_path.parent / "evil.txt").exists()
    assert not (tmp_path / "demo").exists()


def test_unpack_path_traversal_nested(tmp_path, build_hm):
    # цитируемый в TODO случай: manifest в подпапке + ../ в имени файла
    hm = build_hm({
        "pkg/manifest.json": json.dumps(make_manifest()),
        "pkg/../../evil.txt": "boom",
    })
    with pytest.raises(PackageError):
        unpack(hm, tmp_path)
    assert not (tmp_path.parent / "evil.txt").exists()


def test_unpack_without_manifest(tmp_path, build_hm):
    hm = build_hm({"app/main.py": "x"})
    with pytest.raises(PackageError, match="manifest"):
        unpack(hm, tmp_path)


def test_unpack_broken_manifest_json(tmp_path, build_hm):
    hm = build_hm({"manifest.json": "{not json"})
    with pytest.raises(PackageError, match="JSON"):
        unpack(hm, tmp_path)


def test_unpack_not_a_zip(tmp_path):
    p = tmp_path / "bad.hm"
    p.write_text("hello")
    with pytest.raises(PackageError, match="zip"):
        unpack(p, tmp_path)


def test_unpack_nested_manifest_prefix(tmp_path, build_hm):
    # manifest лежит в подпапке — prefix считается верно, файлы ложатся в корень плагина
    hm = build_hm({
        "demo/manifest.json": json.dumps(make_manifest()),
        "demo/app/main.py": "print('nested')",
        "demo/data/seed.txt": "seed",
    })
    manifest = unpack(hm, tmp_path)
    assert manifest["id"] == "demo"

    dest = tmp_path / "demo"
    assert (dest / "app" / "main.py").read_text() == "print('nested')"
    assert (dest / "data" / "seed.txt").read_text() == "seed"
    # вложенная папка demo/ не должна задвоиться
    assert not (dest / "demo").exists()


def test_unpack_reinstall_keeps_data(tmp_path, build_hm):
    v1 = build_hm({
        "manifest.json": json.dumps(make_manifest(version="1.0.0")),
        "data/settings.json": '{"token":"secret"}',
        "app/main.py": "old",
    }, name="demo-1.0.0.hm")
    unpack(v1, tmp_path)

    dest = tmp_path / "demo"
    (dest / "data" / "settings.json").write_text('{"token":"changed"}')

    v2 = build_hm({
        "manifest.json": json.dumps(make_manifest(version="1.0.1")),
        "app/main.py": "new",
    }, name="demo-1.0.1.hm")
    manifest = unpack(v2, tmp_path)

    assert manifest["version"] == "1.0.1"
    assert (dest / "app" / "main.py").read_text() == "new"
    # data/ сохранилась через переустановку
    assert (dest / "data" / "settings.json").read_text() == '{"token":"changed"}'
    # временный бэкап убран
    assert not (tmp_path / ".demo_data_backup").exists()


def test_unpack_reinstall_without_data(tmp_path, build_hm):
    v1 = build_hm({
        "manifest.json": json.dumps(make_manifest()),
        "app/main.py": "old",
    }, name="demo-1.hm")
    unpack(v1, tmp_path)

    v2 = build_hm({
        "manifest.json": json.dumps(make_manifest(version="1.1.0")),
        "app/main.py": "new",
    }, name="demo-2.hm")
    manifest = unpack(v2, tmp_path)

    assert manifest["version"] == "1.1.0"
    assert (tmp_path / "demo" / "app" / "main.py").read_text() == "new"


# ── setup_venv / install_deps / verify_deps ──────────────────────────────────

def _fake_venv(plugin_dir: Path):
    """Создаёт структуру venv с бинарями, не вызывая python -m venv."""
    bin_dir = venv_bin_dir(plugin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("pip", "python"):
        full = fname + (".exe" if inst.IS_WINDOWS else "")
        (bin_dir / full).write_text("# fake", encoding="utf-8")
    return bin_dir


def test_setup_venv_skips_existing(tmp_plugin_dir, mocker):
    venv_dir(tmp_plugin_dir).mkdir(parents=True)
    run = mocker.patch("app.services.plugin_installer.subprocess.run")
    setup_venv(tmp_plugin_dir)
    run.assert_not_called()


def test_setup_venv_creates(tmp_plugin_dir, mocker):
    run = mocker.patch("app.services.plugin_installer.subprocess.run")
    setup_venv(tmp_plugin_dir)
    run.assert_called_once()
    cmd = run.call_args[0][0]
    assert cmd[0:3] == [sys.executable, "-m", "venv"]
    assert cmd[3].endswith(".venv")


def test_install_deps_no_requirements(tmp_plugin_dir, mocker):
    (tmp_plugin_dir / "requirements.txt").unlink()
    run = mocker.patch("app.services.plugin_installer.subprocess.run")
    install_deps(tmp_plugin_dir)
    run.assert_not_called()


def test_install_deps_pip_missing(tmp_plugin_dir, mocker):
    # pip не найден в venv → InstallError
    mocker.patch("app.services.plugin_installer.subprocess.run")
    with pytest.raises(InstallError, match="pip"):
        install_deps(tmp_plugin_dir)


def test_install_deps_pip_failure(tmp_plugin_dir, mocker):
    _fake_venv(tmp_plugin_dir)
    mocker.patch(
        "app.services.plugin_installer.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom: no such package\n"),
    )
    with pytest.raises(InstallError) as exc:
        install_deps(tmp_plugin_dir)
    assert "boom: no such package" in str(exc.value)
    assert "pip install failed" in str(exc.value)


def test_install_deps_ok(tmp_plugin_dir, mocker):
    _fake_venv(tmp_plugin_dir)
    mocker.patch(
        "app.services.plugin_installer.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    # не должно бросить исключение
    install_deps(tmp_plugin_dir)


def test_verify_deps_no_requirements(tmp_plugin_dir, mocker):
    (tmp_plugin_dir / "requirements.txt").unlink()
    run = mocker.patch("app.services.plugin_installer.subprocess.run")
    verify_deps(tmp_plugin_dir)
    run.assert_not_called()


def test_verify_deps_missing_python(tmp_plugin_dir, mocker):
    mocker.patch("app.services.plugin_installer.subprocess.run")
    with pytest.raises(InstallError, match="python"):
        verify_deps(tmp_plugin_dir)


def test_verify_deps_failure(tmp_plugin_dir, mocker):
    _fake_venv(tmp_plugin_dir)
    mocker.patch(
        "app.services.plugin_installer.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b""),
    )
    with pytest.raises(InstallError) as exc:
        verify_deps(tmp_plugin_dir)
    assert "не импортируется" in str(exc.value)


def test_verify_deps_ok(tmp_plugin_dir, mocker):
    _fake_venv(tmp_plugin_dir)
    mocker.patch(
        "app.services.plugin_installer.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=b"", stderr=b""),
    )
    verify_deps(tmp_plugin_dir)


# ── Кроссплатформенные пути (TODO: Windows-ветка) ────────────────────────────

def test_windows_path_selection(monkeypatch, tmp_plugin_dir):
    monkeypatch.setattr(inst, "IS_WINDOWS", True)
    assert venv_dir(tmp_plugin_dir).name == ".venv"
    assert venv_bin_dir(tmp_plugin_dir).name == "Scripts"
    assert venv_python(tmp_plugin_dir).name == "python.exe"
    assert venv_python(tmp_plugin_dir).parent.name == "Scripts"


def test_posix_path_selection(monkeypatch, tmp_plugin_dir):
    monkeypatch.setattr(inst, "IS_WINDOWS", False)
    assert venv_bin_dir(tmp_plugin_dir).name == "bin"
    assert venv_python(tmp_plugin_dir).name == "python"