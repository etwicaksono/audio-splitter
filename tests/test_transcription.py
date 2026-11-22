from types import SimpleNamespace

import pytest

from src.services.errors import AppError, Cancelled
from src.services.transcription_service import TranscriptionService


def fake_model(monkeypatch, segments):
    import faster_whisper

    class Model:
        options = None
        def __init__(self, name, **kwargs):
            Model.options = kwargs

        def transcribe(self, path, **kwargs):
            assert kwargs["language"] == "en"
            assert kwargs["word_timestamps"] and kwargs["vad_filter"]
            return iter(segments), SimpleNamespace(language="en")

    monkeypatch.setattr(faster_whisper, "WhisperModel", Model)
    return Model


def test_required_configuration_and_progress(monkeypatch, tmp_path):
    model = fake_model(monkeypatch, [
        SimpleNamespace(text="Hello.", end=1.0, words=[
            SimpleNamespace(word=" Hello.", start=0.2, end=1.0, probability=0.9)])])
    progress = []
    words, language = TranscriptionService().transcribe(
        tmp_path / "audio.mp3", 2, lambda value, message: progress.append(value))
    assert words[0].start == 0.2 and language == "en"
    assert model.options["device"] == "cpu"
    assert model.options["compute_type"] == "int8"
    assert model.options["num_workers"] == 1
    assert progress[0] == 0 and progress[-1] == 96


@pytest.mark.parametrize("segments", [
    [], [SimpleNamespace(text="Hello", end=1, words=None)],
    [SimpleNamespace(text="Hello", end=1, words=[
        SimpleNamespace(word="Hello", start=None, end=1, probability=1)])],
])
def test_missing_speech_or_timestamps_fail(monkeypatch, tmp_path, segments):
    fake_model(monkeypatch, segments)
    with pytest.raises(AppError):
        TranscriptionService().transcribe(tmp_path / "test.mp3", 2)


def test_cancellation_before_model_loading(monkeypatch, tmp_path):
    fake_model(monkeypatch, [])
    with pytest.raises(Cancelled):
        TranscriptionService().transcribe(tmp_path / "test.mp3", 2, cancel=lambda: True)


def test_model_load_failure_is_understandable(monkeypatch, tmp_path):
    import faster_whisper
    def broken(*args, **kwargs):
        raise RuntimeError("connection failed")
    monkeypatch.setattr(faster_whisper, "WhisperModel", broken)
    with pytest.raises(AppError, match="connect to the internet"):
        TranscriptionService().transcribe(tmp_path / "test.mp3", 2)


def test_zero_length_alignment_token_does_not_abort_entire_recording(monkeypatch, tmp_path):
    fake_model(monkeypatch, [
        SimpleNamespace(text="The boy.", end=1, words=[
            SimpleNamespace(word=" The", start=0.1, end=0.1, probability=0.8),
            SimpleNamespace(word=" boy.", start=0.1, end=1, probability=0.9)])])
    words, _ = TranscriptionService().transcribe(tmp_path / "test.mp3", 2)
    assert words[0].start == words[0].end == 0.1
    assert len(words) == 2
