"""System-dependent parts: Windows is simulated here on Linux too, and vice versa."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from anyfile.core import system


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(system, "IS_WINDOWS", True)


def test_windows_never_mistakes_the_system_convert_for_imagemagick(windows, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: rf"C:\Windows\System32\{name}.exe")
    assert system.which("convert") is None
    assert system.which("magick") == r"C:\Windows\System32\magick.exe"


def test_windows_finds_engines_outside_the_path(windows, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    for version in ("gs9.56.1", "gs10.04.0"):
        exe = tmp_path / "gs" / version / "bin" / "gswin64c.exe"
        exe.parent.mkdir(parents=True)
        exe.touch()
    office = tmp_path / "LibreOffice" / "program" / "soffice.exe"
    office.parent.mkdir(parents=True)
    office.touch()
    assert system.which("gswin64c").endswith(os.path.join("gs10.04.0", "bin", "gswin64c.exe"))
    assert system.which("soffice") == str(office)
    assert system.which("pandoc") is None


def test_windows_folders(windows, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert system.data_dir() == tmp_path / "Roaming" / "anyfile"
    assert system.cache_dir() == tmp_path / "Local" / "anyfile"


@pytest.mark.skipif(system.IS_WINDOWS, reason="XDG folders only on Linux")
def test_linux_folders(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert system.data_dir() == tmp_path / "data" / "anyfile"
    assert system.cache_dir() == tmp_path / "cache" / "anyfile"


def test_link_falls_back_to_hard_link_then_copy(tmp_path, monkeypatch):
    src = tmp_path / "original.bin"
    src.write_bytes(b"content")

    def no_symlink(self, target):
        raise OSError("symlinks not allowed")

    monkeypatch.setattr(Path, "symlink_to", no_symlink)
    hard = tmp_path / "hard.bin"
    system.link_or_copy(src, hard)
    assert hard.read_bytes() == b"content" and os.path.samefile(src, hard)

    def no_link(*args):
        raise OSError("hard links not allowed")

    monkeypatch.setattr(os, "link", no_link)
    copy = tmp_path / "copy.bin"
    system.link_or_copy(src, copy)
    assert copy.read_bytes() == b"content" and not os.path.samefile(src, copy)


def test_windows_never_uses_symlinks(windows, tmp_path, monkeypatch):
    src = tmp_path / "original.bin"
    src.write_bytes(b"content")

    def forbidden(self, target):
        raise AssertionError("no symbolic links on Windows")

    monkeypatch.setattr(Path, "symlink_to", forbidden)
    dst = tmp_path / "input.bin"
    system.link_or_copy(src, dst)
    assert dst.read_bytes() == b"content" and not dst.is_symlink()


def test_kill_tree_stops_process_and_children():
    # A process that starts another one: both must stop.
    child = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
    proc = subprocess.Popen([sys.executable, "-c", child], **system.popen_options())
    time.sleep(0.5)
    started = time.monotonic()
    system.kill_tree(proc)
    assert proc.poll() is not None
    assert time.monotonic() - started < 10


def test_is_flatpak(monkeypatch, tmp_path):
    monkeypatch.delenv("FLATPAK_ID", raising=False)
    monkeypatch.setattr(system, "_FLATPAK_INFO", tmp_path / "missing")
    assert not system.is_flatpak()

    monkeypatch.setenv("FLATPAK_ID", "io.github.pietrolama.anyfile")
    assert system.is_flatpak()


def test_dolphin_integration_lifecycle(monkeypatch, tmp_path):
    from anyfile.ui import desktop

    fake_menu = tmp_path / "kio" / "servicemenus" / "anyfile.desktop"
    monkeypatch.setattr(desktop, "dolphin_servicemenu_path", lambda: fake_menu)
    monkeypatch.setattr(desktop, "_refresh_kde_sycoca", lambda: None)
    monkeypatch.delenv("FLATPAK_ID", raising=False)

    assert not desktop.is_dolphin_integrated()

    path = desktop.integrate_dolphin()
    assert path == fake_menu
    assert desktop.is_dolphin_integrated()
    content = path.read_text(encoding="utf-8")
    assert "Type=Service" in content
    assert "Convert with ANYFILE" in content
    assert "--radial %F" in content

    # Test flatpak exec generation
    monkeypatch.setenv("FLATPAK_ID", "io.github.pietrolama.anyfile")
    desktop.integrate_dolphin()
    content_flatpak = path.read_text(encoding="utf-8")
    assert "Exec=flatpak run io.github.pietrolama.anyfile --radial %F" in content_flatpak

    # Test removal
    desktop.remove_dolphin_integration()
    assert not desktop.is_dolphin_integrated()
    assert not fake_menu.exists()


def test_reveal_calls(monkeypatch, tmp_path):
    from anyfile.ui import desktop

    target = tmp_path / "test.png"
    target.touch()

    # 1. On Windows
    commands = []
    monkeypatch.setattr(system, "IS_WINDOWS", True)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: commands.append(cmd))
    desktop.reveal(target)
    assert any("explorer" in cmd[0] for cmd in commands)

    # 2. On Linux fallback to dolphin
    commands.clear()
    monkeypatch.setattr(system, "IS_WINDOWS", False)
    monkeypatch.setattr(desktop, "_reveal_dbus", lambda path: False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/dolphin" if name == "dolphin" else None)
    desktop.reveal(target)
    assert any("dolphin" in cmd[0] for cmd in commands)


def test_install_hint_inside_and_outside_flatpak(monkeypatch):
    monkeypatch.setattr(system, "is_flatpak", lambda: False)
    assert system.install_command(["ffmpeg", "pandoc"]) == "sudo apt install ffmpeg pandoc"
    assert system.install_command([]) == ""
    assert system.install_hint(["pandoc"]) == "sudo apt install pandoc"

    monkeypatch.setattr(system, "is_flatpak", lambda: True)
    assert system.install_command(["pandoc"]) == ""
    assert "Flatpak" in system.install_hint(["pandoc"])
