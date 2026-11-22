import csv
import shutil
import zipfile

import numpy as np
import pytest

from src.models.sentence import Sentence, Word
from src.services.audio_service import AudioService, clip_ranges, run_audio, tool_path
from src.services.errors import AppError, Cancelled
from src.services.export_service import ExportService, filename_for, write_transcripts


def test_default_padding_and_neighbor_limits():
    sentences = [
        Sentence("One.", 0.2, 1.0, [Word("One.", 0.2, 1.0)]),
        Sentence("Two.", 1.1, 2.0, [Word("Two.", 1.1, 2.0)], include=False),
        Sentence("Three.", 2.5, 2.9, [Word("Three.", 2.5, 2.9)]),
    ]
    ranges = clip_ranges(sentences, 3)
    assert ranges[0] == pytest.approx((0.1, 1.05))
    assert ranges[1] == pytest.approx((1.05, 2.15))
    assert ranges[2] == pytest.approx((2.4, 3))
    for sentence, (start, end) in zip(sentences, ranges):
        assert start <= sentence.words[0].start
        assert end >= sentence.words[-1].end


def test_silence_refinement_uses_silent_neighbor_point():
    sentences = [Sentence("One.", 0.1, 1), Sentence("Two.", 1.2, 2)]
    ranges = clip_ranges(sentences, 2, 0.2, 0.2, [(1.02, 1.08)])
    assert ranges[0][1] == pytest.approx(1.05)
    assert ranges[1][0] == pytest.approx(1.05)


@pytest.mark.parametrize("padding", [-1, 3, float("nan"), float("inf")])
def test_invalid_padding(padding):
    with pytest.raises(AppError):
        clip_ranges([Sentence("One.", 0, 1)], 1, padding)


def test_overlaps_cannot_export():
    with pytest.raises(AppError):
        clip_ranges([Sentence("One.", 0, 1), Sentence("Two.", 0.8, 2)], 2)


@pytest.mark.parametrize("number,name", [
    (1, "001.mp3"), (9, "009.mp3"), (99, "099.mp3"), (999, "999.mp3"),
    (1000, "1000.mp3"), (10001, "10001.mp3"),
])
def test_numbering(number, name):
    assert filename_for(number) == name


def test_utf8_transcript_and_csv_quotes(tmp_path):
    rows = [{"filename": "001.mp3", "sentence": 'She said, “Hello, friend!”',
             "start_time": "0.100000", "end_time": "1.200000", "duration": "1.100000"}]
    write_transcripts(tmp_path, rows)
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == \
        "001.mp3\tShe said, “Hello, friend!”\n"
    with (tmp_path / "transcript.csv").open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == rows


@pytest.mark.integration
def test_real_mp3_cut_accuracy(tone_audio, tmp_path):
    audio = AudioService()
    source = audio.probe(tone_audio)
    destination = tmp_path / "cut.mp3"
    audio.cut(source, destination, 2.2, 3.2)
    actual = audio.probe(destination)
    assert actual.sample_rate == source.sample_rate == 48000
    assert actual.duration == pytest.approx(1, abs=0.06)
    samples = np.frombuffer(run_audio([
        tool_path("ffmpeg"), "-v", "error", "-i", str(destination), "-f", "f32le",
        "-ac", "1", "-ar", "48000", "pipe:1",
    ]), dtype="<f4")
    assert len(samples) == pytest.approx(48000, abs=48)
    # Decoder removes MP3 encoder delay; compare directly to the independent WAV.
    import wave
    with wave.open(str(tone_audio), "rb") as handle:
        handle.setpos(int(2.2 * 48000))
        reference = np.frombuffer(handle.readframes(len(samples)), dtype="<i2") / 32767
    correlation = np.corrcoef(reference[1000:-1000], samples[1000:-1000])[0, 1]
    assert correlation > 0.995
    frequency = np.fft.rfftfreq(len(samples), 1 / 48000)[np.argmax(abs(np.fft.rfft(samples)))]
    assert frequency == pytest.approx(880, abs=2)


@pytest.mark.integration
def test_actual_sequential_export_zip_and_exclusion(tone_audio, tmp_path):
    metadata = AudioService().probe(tone_audio)
    sentences = [Sentence("First sentence.", 0.1, 1.2),
                 Sentence("Excluded.", 1.4, 1.7, include=False),
                 Sentence('Second, “sentence!”', 2.2, 3.7)]
    result = ExportService().export(metadata, sentences, tmp_path / "export", make_zip=True)
    assert result.count == 2
    assert {f.name for f in result.folder.iterdir()} == {
        "001.mp3", "002.mp3", "transcript.txt", "transcript.csv"}
    with zipfile.ZipFile(result.archive) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {f.name for f in result.folder.iterdir()}
    with (result.folder / "transcript.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[1]["sentence"] == sentences[2].text
    assert float(rows[0]["start_time"]) == pytest.approx(0)
    assert float(rows[1]["duration"]) == pytest.approx(1.75)


@pytest.mark.integration
def test_actual_import_waveform(tone_audio):
    audio = AudioService()
    metadata = audio.probe(tone_audio)
    peaks = audio.waveform(metadata)
    assert metadata.duration == 4
    assert 850 <= len(peaks) <= 900
    assert max(peaks) == pytest.approx(0.35, abs=0.01)


@pytest.mark.integration
def test_review_gate_missing_space_cancel_and_existing_folder(tone_audio, tmp_path, monkeypatch):
    metadata = AudioService().probe(tone_audio)
    sentence = Sentence("One.", 0, 1, review_reasons=["Uncertain."])
    target = tmp_path / "export"
    with pytest.raises(AppError, match="review"):
        ExportService().export(metadata, [sentence], target)
    sentence.reviewed = True
    with pytest.raises(Cancelled):
        ExportService().export(metadata, [sentence], target, cancel=lambda: True)
    assert not target.exists()
    original = shutil.disk_usage
    monkeypatch.setattr(shutil, "disk_usage", lambda path: type(original(path))(100, 100, 0))
    with pytest.raises(AppError, match="disk space"):
        ExportService().export(metadata, [sentence], target)
    monkeypatch.setattr(shutil, "disk_usage", original)
    target.mkdir()
    marker = target / "user.txt"
    marker.write_text("keep me", encoding="utf-8")
    with pytest.raises(AppError, match="already exists"):
        ExportService().export(metadata, [sentence], target)
    assert marker.read_text(encoding="utf-8") == "keep me"


@pytest.mark.integration
def test_failed_second_clip_never_silently_skips(tone_audio, tmp_path):
    class FailingAudio(AudioService):
        def cut(self, source, destination, start, end, prefer_copy=False, cancel=None):
            if destination.name == "002.mp3":
                raise AppError("Injected failure")
            return super().cut(source, destination, start, end, prefer_copy, cancel)
    target = tmp_path / "failed"
    with pytest.raises(AppError, match="Injected"):
        ExportService(FailingAudio()).export(
            AudioService().probe(tone_audio),
            [Sentence("One.", 0, 1), Sentence("Two.", 2, 3)], target, make_zip=True)
    assert not target.exists()
    assert not target.with_suffix(".zip").exists()
    assert not list(tmp_path.glob(".sentence-export-*"))


def test_invalid_file_and_missing_ffmpeg(tmp_path, monkeypatch):
    with pytest.raises(AppError):
        AudioService().probe(tmp_path / "none.mp3")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(AppError, match="missing"):
        tool_path("nonexistent-ffmpeg-tool")


@pytest.mark.integration
def test_low_sample_rate_export_keeps_requested_bitrate(tone_audio, tmp_path):
    low = tmp_path / "low.wav"
    run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(tone_audio),
               "-ar", "16000", str(low)])
    source = AudioService().probe(low)
    clip = tmp_path / "low.mp3"
    AudioService().cut(source, clip, 0.5, 1.5)
    assert AudioService().probe(clip).sample_rate == 32000
    import json
    info = json.loads(run_audio([tool_path("ffprobe"), "-v", "error",
                                "-show_entries", "stream=bit_rate", "-of", "json", str(clip)]))
    assert int(info["streams"][0]["bit_rate"]) == 192000


@pytest.mark.integration
def test_full_mp3_copy_and_dotted_zip_name(tone_audio, tmp_path):
    audio = AudioService()
    mp3 = tmp_path / "source.mp3"
    audio.cut(audio.probe(tone_audio), mp3, 0, 4)
    metadata = audio.probe(mp3)
    copied = tmp_path / "copied.mp3"
    assert audio.cut(metadata, copied, 0, metadata.duration, prefer_copy=True) == "stream copy"
    # Full copy keeps the compressed payload, not a second generation encode.
    payloads = [run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(path),
                          "-map", "0:a:0", "-c:a", "copy", "-f", "data", "pipe:1"])
                for path in (mp3, copied)]
    assert payloads[0] == payloads[1]
    result = ExportService().export(metadata, [Sentence("One.", 0, 1)],
                                    tmp_path / "story.version1", make_zip=True)
    assert result.archive.name == "story.version1.zip"


def test_refinement_covers_word_tails_without_crossing_neighbors():
    from src.services.audio_service import AudioMetadata
    from pathlib import Path
    source = AudioMetadata(Path("unused.wav"), 5, 0, 48000, 1, "pcm_s16le")
    sentences = [Sentence("One.", 0.3, 1.0), Sentence("Two.", 2.2, 3.1)]
    AudioService().refine_boundaries(source, sentences, [(0, 0.2), (1.21, 2.1), (3.25, 5)])
    assert sentences[0].start == pytest.approx(0.2)
    assert sentences[0].end == pytest.approx(1.21)
    assert sentences[1].start == pytest.approx(2.1)
    assert sentences[1].end == pytest.approx(3.25)
    assert not any(s.needs_review for s in sentences)
    ranges = clip_ranges(sentences, 5)
    assert ranges[0][1] > 1.21 and ranges[1][0] < 2.1


def test_missing_silence_edges_are_flagged_not_guessed():
    from src.services.audio_service import AudioMetadata
    from pathlib import Path
    source = AudioMetadata(Path("unused.wav"), 10, 0, 48000, 1, "pcm_s16le")
    sentences = [Sentence("One.", 1.5, 2), Sentence("Two.", 2.1, 3)]
    AudioService().refine_boundaries(source, sentences, [])
    assert all(s.needs_review for s in sentences)
    assert sentences[0].start == 1.5 and sentences[0].end == 2


def test_alignment_inside_long_silence_does_not_export_excess_silence():
    from src.services.audio_service import AudioMetadata
    from pathlib import Path
    source = AudioMetadata(Path("unused.wav"), 4, 0, 48000, 1, "pcm_s16le")
    words = [Word("Hello", 0.72, 1.3), Word("there.", 1.4, 2.0)]
    sentence = Sentence("Hello there.", 0.72, 2, words)
    AudioService().refine_boundaries(source, [sentence], [(0, 1.11), (2.1, 4)])
    assert sentence.start == sentence.words[0].start == 1.11
    sentence.validate(4)
    assert clip_ranges([sentence], 4)[0][0] == pytest.approx(1.01)
    assert sentence.needs_review


@pytest.mark.integration
def test_mp3_input_cut_is_sample_exact_at_fractional_timestamps(tone_audio, tmp_path):
    audio = AudioService()
    source = tmp_path / "source.mp3"
    audio.cut(audio.probe(tone_audio), source, 0, 4)
    metadata = audio.probe(source)
    clip = tmp_path / "fractional.mp3"
    start, end = 1.15814, 3.578662
    audio.cut(metadata, clip, start, end)
    decoded = run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(clip),
                         "-f", "f32le", "-ac", "1", "pipe:1"])
    assert len(decoded) // 4 == round(end * 48000) - round(start * 48000)
