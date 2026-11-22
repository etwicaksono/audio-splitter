import pytest

from src.services.audio_service import AudioService, run_audio, tool_path
from src.services.mp3_metadata import crc16


def test_tag_crc_matches_upstream_polynomial():
    assert crc16(b"123456789") == 0xBB3D


@pytest.mark.integration
@pytest.mark.parametrize("samples", [1153, 6913, 48001, 96001])
def test_gapless_metadata_keeps_partial_frame_sample_count(tone_audio, tmp_path, samples):
    audio = AudioService()
    metadata = audio.probe(tone_audio)
    destination = tmp_path / f"{samples}.mp3"
    audio.cut(metadata, destination, 0, samples / metadata.sample_rate)
    data = run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(destination),
                      "-f", "f32le", "-ac", "1", "pipe:1"])
    assert len(data) // 4 == samples


@pytest.mark.integration
def test_stereo_gapless_metadata(tone_audio, tmp_path):
    audio = AudioService()
    source = tmp_path / "stereo.wav"
    run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(tone_audio), "-ac", "2", str(source)])
    destination = tmp_path / "stereo.mp3"
    audio.cut(audio.probe(source), destination, 0, 1153 / 48000)
    data = run_audio([tool_path("ffmpeg"), "-v", "error", "-i", str(destination),
                      "-f", "f32le", "-ac", "2", "pipe:1"])
    assert len(data) // 8 == 1153
