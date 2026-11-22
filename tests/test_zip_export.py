from pathlib import Path
import zipfile

import pytest

from src.models.sentence import Sentence
from src.services.audio_service import AudioMetadata
from src.services.errors import AppError, Cancelled
from src.services.export_service import ExportService


@pytest.fixture
def export_data():
    class PackagingAudio:
        def cut(self, source, destination, *args):
            destination.write_bytes(b"synthetic clip payload for packaging tests")

    return (ExportService(PackagingAudio()),
            AudioMetadata(Path("unused.wav"), 4, 0, 48000, 1, "pcm_s16le"),
            [Sentence("First sentence.", 0.1, 1), Sentence("Second sentence.", 2.1, 3)])


def test_zip_only_keeps_an_existing_same_named_folder(export_data, tmp_path):
    service, metadata, sentences = export_data
    folder = tmp_path / "export"
    folder.mkdir()
    marker = folder / "user.txt"
    marker.write_bytes(b"keep this folder")
    result = service.export(metadata, sentences, folder, make_zip=True)
    assert result.folder is None and result.archive == tmp_path / "export.zip"
    assert marker.read_bytes() == b"keep this folder"
    assert {path.name for path in folder.iterdir()} == {"user.txt"}
    assert not list(tmp_path.glob(".sentence-export-*"))


@pytest.mark.parametrize("make_zip", [False, True], ids=["folder", "zip-only"])
def test_existing_output_is_never_replaced(export_data, tmp_path, make_zip):
    service, metadata, sentences = export_data
    folder = tmp_path / "export"
    target = tmp_path / "export.zip" if make_zip else folder
    target.write_bytes(b"existing user output")
    with pytest.raises(AppError, match="already exists"):
        service.export(metadata, sentences, folder, make_zip=make_zip)
    assert target.read_bytes() == b"existing user output"


def test_zip_publish_failure_keeps_user_folder_and_removes_temporary_files(export_data, tmp_path,
                                                                         monkeypatch):
    service, metadata, sentences = export_data
    folder = tmp_path / "export"
    folder.mkdir()
    marker = folder / "user.txt"
    marker.write_bytes(b"keep me")
    original = Path.rename

    def fail_publish(path, target):
        if path.name == "archive.zip":
            raise OSError("Injected ZIP publish failure")
        return original(path, target)

    monkeypatch.setattr(Path, "rename", fail_publish)
    with pytest.raises(AppError, match="Cannot write"):
        service.export(metadata, sentences, folder, make_zip=True)
    assert marker.read_bytes() == b"keep me"
    assert not (tmp_path / "export.zip").exists()
    assert not list(tmp_path.glob(".sentence-export-*"))


@pytest.mark.parametrize("make_zip", [False, True], ids=["folder", "zip-only"])
def test_failure_after_publish_removes_only_its_new_output(export_data, tmp_path, make_zip):
    service, metadata, sentences = export_data
    folder = tmp_path / "export"
    archive = tmp_path / "export.zip"
    preserved = folder if make_zip else archive
    preserved.write_bytes(b"user data")

    def fail_completion(value, message):
        if value == 100:
            raise ValueError("Injected completion failure")

    with pytest.raises(ValueError, match="completion failure"):
        service.export(metadata, sentences, folder, make_zip=make_zip, progress=fail_completion)
    assert preserved.read_bytes() == b"user data"
    assert not (archive if make_zip else folder).exists()
    assert not list(tmp_path.glob(".sentence-export-*"))


@pytest.mark.parametrize("when", ["packaging", "verified"])
def test_zip_cancel_never_publishes_folder_or_archive(export_data, tmp_path, monkeypatch, when):
    service, metadata, sentences = export_data
    cancelled = False

    def progress(value, message):
        nonlocal cancelled
        if value == 92 and when == "packaging":
            cancelled = True

    original = zipfile.ZipFile.testzip

    def verify(archive):
        nonlocal cancelled
        result = original(archive)
        if when == "verified":
            cancelled = True
        return result

    monkeypatch.setattr(zipfile.ZipFile, "testzip", verify)
    with pytest.raises(Cancelled):
        service.export(metadata, sentences, tmp_path / "export", make_zip=True,
                       progress=progress, cancel=lambda: cancelled)
    assert not (tmp_path / "export").exists()
    assert not (tmp_path / "export.zip").exists()
    assert not list(tmp_path.glob(".sentence-export-*"))


def test_corrupt_zip_is_not_published(export_data, tmp_path, monkeypatch):
    service, metadata, sentences = export_data
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda archive: "broken.mp3")
    with pytest.raises(AppError, match="ZIP verification failed"):
        service.export(metadata, sentences, tmp_path / "export", make_zip=True)
    assert not (tmp_path / "export").exists()
    assert not (tmp_path / "export.zip").exists()
    assert not list(tmp_path.glob(".sentence-export-*"))


def test_zip_appearing_during_export_is_preserved(export_data, tmp_path):
    service, metadata, sentences = export_data
    archive = tmp_path / "export.zip"

    def create_existing_output(value, message):
        if value == 92:
            archive.write_bytes(b"another user's output")

    with pytest.raises(AppError, match="already exists"):
        service.export(metadata, sentences, tmp_path / "export", make_zip=True,
                       progress=create_existing_output)
    assert archive.read_bytes() == b"another user's output"
    assert not (tmp_path / "export").exists()
    assert not list(tmp_path.glob(".sentence-export-*"))
