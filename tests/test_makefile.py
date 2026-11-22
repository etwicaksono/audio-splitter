import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or MAKE is None or shutil.which("powershell.exe") is None,
    reason="Windows GNU Make and PowerShell are required",
)


@pytest.fixture
def make_repo(tmp_path):
    repo = tmp_path / "repository with spaces"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "Makefile", repo / "Makefile")
    shutil.copy2(ROOT / "scripts" / "repo.ps1", repo / "scripts" / "repo.ps1")
    return repo


def run_make(repo, *arguments, timeout=45):
    environment = os.environ.copy()
    # Isolated install tests use an empty requirements file, with no network.
    environment["PIP_NO_INDEX"] = "1"
    environment["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    result = subprocess.run(
        [MAKE, "-C", str(repo), *arguments], capture_output=True, text=True,
        timeout=timeout, env=environment,
    )
    return result.returncode, result.stdout + result.stderr


def test_default_help_does_not_create_environment(make_repo):
    code, output = run_make(make_repo)
    assert code == 0, output
    assert "make build" in output and "make clean" in output
    assert not (make_repo / ".venv").exists()


def test_install_and_idempotent_setup_with_spaces(make_repo):
    (make_repo / "requirements-dev.txt").write_text("", encoding="utf-8")
    environment = make_repo / "environment with spaces"
    options = [f"VENV={environment}", f"PYTHON={sys.executable}"]
    code, output = run_make(make_repo, "install", *options, timeout=90)
    assert code == 0, output
    python = environment / "Scripts" / "python.exe"
    pip = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
    assert pip.returncode == 0
    stamp = (environment / "pyvenv.cfg").stat().st_mtime_ns
    code, output = run_make(make_repo, "setup", *options)
    assert code == 0, output
    assert (environment / "pyvenv.cfg").stat().st_mtime_ns == stamp
    # Reproduce an existing uv-style environment with no pip installed.
    removed = subprocess.run(
        [str(python), "-m", "pip", "uninstall", "-y", "pip"], capture_output=True)
    assert removed.returncode == 0
    code, output = run_make(make_repo, "setup", *options)
    assert code == 0, output
    restored = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
    assert restored.returncode == 0
    assert (environment / "pyvenv.cfg").stat().st_mtime_ns == stamp


def test_run_model_and_build_dispatch_with_quoted_paths(make_repo):
    (make_repo / "app.py").write_text(
        "from pathlib import Path\nPath('run.txt').write_text('launched')\n", encoding="utf-8")
    (make_repo / "scripts" / "download_model.py").write_text(
        "from pathlib import Path\nimport sys\nPath('model.txt').write_text(sys.argv[1])\n",
        encoding="utf-8",
    )
    (make_repo / "build_windows.ps1").write_text(
        "param([string]$Python, [string]$BundleModel)\n"
        "@{ Python=$Python; BundleModel=$BundleModel } | ConvertTo-Json | "
        "Set-Content -LiteralPath 'build-call.json' -Encoding UTF8\nexit 0\n", encoding="utf-8")
    option = f"VENV={Path(sys.executable).parents[1]}"
    for target in ("run", "model"):
        code, output = run_make(make_repo, target, option, "MODEL=base")
        assert code == 0, output
    assert (make_repo / "run.txt").read_text() == "launched"
    assert (make_repo / "model.txt").read_text() == "base"
    code, output = run_make(make_repo, "build", option, "BUNDLE_MODEL=models/model with spaces")
    assert code == 0, output
    data = json.loads((make_repo / "build-call.json").read_text(encoding="utf-8-sig"))
    assert Path(data["Python"]) == Path(sys.executable)
    assert data["BundleModel"] == "models/model with spaces"
    code, _ = run_make(make_repo, "model", option, "MODEL=tiny")
    assert code != 0
    assert (make_repo / "model.txt").read_text() == "base"


def test_missing_environment_is_understandable(make_repo):
    code, output = run_make(make_repo, "test")
    assert code != 0
    assert "Run make install first" in output


def test_process_failure_propagates_to_make(make_repo):
    (make_repo / "app.py").write_text("raise SystemExit(7)\n", encoding="utf-8")
    code, output = run_make(make_repo, "run", f"VENV={Path(sys.executable).parents[1]}")
    assert code != 0
    assert "exit code 7" in output


def test_clean_keeps_releases_models_audio_and_environment(make_repo):
    for name in ("dist", "models", "output", ".venv", ".tooling", "build",
                 ".pytest_cache", ".ruff_cache", "src/services/__pycache__"):
        directory = make_repo / name
        directory.mkdir(parents=True)
        (directory / "sentinel.txt").write_text("keep or clean", encoding="utf-8")
    recording = make_repo / "storytelling.mp3"
    recording.write_bytes(b"original recording")
    code, output = run_make(make_repo, "clean")
    assert code == 0, output
    for name in ("dist", "models", "output", ".venv", ".tooling"):
        assert (make_repo / name / "sentinel.txt").is_file()
    for name in ("build", ".pytest_cache", ".ruff_cache", "src/services/__pycache__"):
        assert not (make_repo / name).exists()
    assert recording.read_bytes() == b"original recording"
    assert (make_repo / "scripts" / "repo.ps1").is_file()


@pytest.mark.parametrize("relative", ["src", "build/nested link"])
def test_clean_rejects_junction_before_removing_anything(make_repo, tmp_path, relative):
    external = tmp_path / "external directory"
    external.mkdir()
    sentinel = external / "sentinel.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    (make_repo / "build").mkdir()
    junction = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(make_repo / relative), str(external)],
        capture_output=True, text=True,
    )
    if junction.returncode != 0:
        pytest.skip("This filesystem cannot create test junctions.")
    try:
        code, output = run_make(make_repo, "clean")
        assert code != 0
        assert "linked directory" in output
        assert (make_repo / "build").is_dir()
        assert sentinel.read_text(encoding="utf-8") == "untouched"
    finally:
        # Remove only the junction, never recurse into its target.
        os.rmdir(make_repo / relative)


def test_setup_does_not_overwrite_user_folder(make_repo):
    environment = make_repo / "user folder"
    environment.mkdir()
    sentinel = environment / "document.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    code, output = run_make(make_repo, "setup", f"VENV={environment}", f"PYTHON={sys.executable}")
    assert code != 0
    assert "non-empty folder" in output
    assert sentinel.read_text(encoding="utf-8") == "keep me"
    assert not (environment / "pyvenv.cfg").exists()
