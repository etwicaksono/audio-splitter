from array import array
from dataclasses import dataclass, replace
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys

from src.models.sentence import Sentence
from src.services.errors import AppError, Cancelled
from src.services.mp3_metadata import repair_gapless_padding

SUPPORTED = {".mp3", ".wav", ".m4a", ".flac", ".aac"}
CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def tool_path(name: str) -> str:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    suffix = ".exe" if sys.platform == "win32" else ""
    for directory in (root / "assets" / "ffmpeg", Path(sys.executable).parent / "ffmpeg"):
        candidate = directory / (name + suffix)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if not found:
        raise AppError(f"{name} is missing. Install FFmpeg or use the bundled Windows release.")
    return found


def run_audio(args: list[str], timeout: float = 120, cancel=None) -> bytes:
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          creationflags=CREATE_NO_WINDOW) as process:
        elapsed = 0.0
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                elapsed += 0.2
                if (cancel and cancel()) or elapsed >= timeout:
                    process.kill()
                    process.communicate()
                    if cancel and cancel():
                        raise Cancelled("Operation cancelled. No partial export was kept.")
                    raise AppError("Audio processing took too long. Check the file and retry.")
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace").strip()[-1200:]
            raise AppError("FFmpeg could not process this audio. " + detail)
        return stdout


@dataclass(frozen=True)
class AudioMetadata:
    path: Path
    duration: float
    size: int
    sample_rate: int
    channels: int
    codec: str


class AudioService:
    def probe(self, path: Path) -> AudioMetadata:
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            raise AppError("Choose an existing MP3, WAV, M4A, FLAC, or AAC audio file.")
        try:
            data = json.loads(run_audio([
                tool_path("ffprobe"), "-v", "error", "-select_streams", "a:0",
                "-show_entries", "format=duration:stream=codec_name,sample_rate,channels,duration",
                "-of", "json", str(path),
            ]))
            stream = data["streams"][0]
            duration = float(data.get("format", {}).get("duration")
                             or stream.get("duration") or 0)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("No valid duration")
            return AudioMetadata(path, duration, path.stat().st_size,
                                 int(stream["sample_rate"]), int(stream["channels"]),
                                 stream["codec_name"])
        except (KeyError, ValueError, IndexError, OSError) as exc:
            raise AppError("This file has no readable audio track or duration.") from exc

    def waveform(self, metadata: AudioMetadata, bins: int = 900, cancel=None) -> list[float]:
        # Streaming decoder: memory remains bounded even for long recordings.
        rate = 8000
        samples_per_bin = max(1, math.ceil(metadata.duration * rate / bins))
        peaks: list[float] = []
        count = 0
        peak = 0.0
        args = [tool_path("ffmpeg"), "-v", "error", "-i", str(metadata.path),
                "-map", "0:a:0", "-ac", "1", "-ar", str(rate), "-f", "s16le", "pipe:1"]
        # stderr goes to a temporary file to avoid pipe deadlocks on corrupt inputs.
        import tempfile
        with tempfile.TemporaryFile() as errors:
            with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors,
                                  creationflags=CREATE_NO_WINDOW) as process:
                try:
                    while block := process.stdout.read(16384):
                        if cancel and cancel():
                            raise Cancelled("Import cancelled.")
                        samples = array("h")
                        samples.frombytes(block)
                        if sys.byteorder != "little":
                            samples.byteswap()
                        for sample in samples:
                            peak = max(peak, abs(sample) / 32768)
                            count += 1
                            if count == samples_per_bin:
                                peaks.append(peak)
                                count, peak = 0, 0.0
                    if count:
                        peaks.append(peak)
                    if process.wait(timeout=30):
                        raise AppError("Cannot decode the audio waveform. The file may be damaged.")
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
        return peaks[:bins]

    def silences(self, metadata: AudioMetadata, cancel=None) -> list[tuple[float, float]]:
        # FFmpeg writes this analysis to stderr.
        args = [tool_path("ffmpeg"), "-hide_banner", "-nostats", "-i", str(metadata.path),
                "-map", "0:a:0", "-af", "silencedetect=noise=-55dB:d=0.12",
                "-f", "null", "-"]
        # Reuse cancellable process runner with stderr redirected to stdout.
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              creationflags=CREATE_NO_WINDOW) as process:
            while True:
                try:
                    output, _ = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel and cancel():
                        process.kill()
                        process.communicate()
                        raise Cancelled("Processing cancelled.")
        if process.returncode:
            raise AppError("Silence analysis failed. Check the recording for damaged audio.")
        pairs = []
        start = None
        for kind, value in re.findall(r"silence_(start|end):\s*([\d.]+)",
                                      output.decode(errors="replace")):
            if kind == "start":
                start = float(value)
            elif start is not None:
                pairs.append((start, float(value)))
                start = None
        if start is not None:
            pairs.append((start, metadata.duration))
        return pairs

    def refine_boundaries(self, metadata: AudioMetadata, sentences: list[Sentence],
                          silences: list[tuple[float, float]]) -> None:
        """Refine approximate word timing using conservative quiet edges.

        A recognizer's final word can end before its last phoneme. Find the next
        silence onset, rather than assuming fixed padding alone repairs alignment.
        Neighbouring words bound the search so it cannot import another sentence.
        """
        # Alignment sometimes puts the start of the first word inside a long silence.
        # Trim only that confirmed silent part, never the audible part of the word.
        for sentence in sentences:
            if sentence.words:
                first = sentence.words[0]
                next_start = sentence.words[1].start if len(sentence.words) > 1 else first.end
                containing = [b for a, b in silences
                              if a <= first.start < b < min(first.end, next_start)
                              and b - a >= 0.3 and b - first.start <= 1.0]
                if containing:
                    onset = max(containing)
                    sentence.words[0] = replace(first, start=onset)
                    sentence.start = onset
                    sentence.review_reasons.append("Initial word alignment included silence. Timing refined; preview.")
        bounds = [(s.start, s.end) for s in sentences]
        for index, sentence in enumerate(sentences):
            start, end = bounds[index]
            left = bounds[index - 1][1] if index else 0.0
            right = bounds[index + 1][0] if index + 1 < len(bounds) else metadata.duration
            preceding = [b for a, b in silences if left <= b <= start]
            following = [a for a, b in silences if end <= a <= right]
            if preceding and start - max(preceding) <= 1.0:
                sentence.start = max(preceding)
            elif not index and start <= 1.0:
                # Speech may already be in progress at file start.
                sentence.start = 0.0
                if start > 0.15:
                    sentence.review_reasons.append("Recording starts before aligned words. Check leading speech.")
            else:
                sentence.review_reasons.append("No reliable quiet edge before the first word. Check timing.")
            if following and min(following) - end <= 1.0:
                sentence.end = min(following)
            elif index == len(bounds) - 1 and metadata.duration - end <= 1.0:
                sentence.end = metadata.duration
            else:
                sentence.review_reasons.append("No reliable quiet edge after the last word. Check timing.")
            if sentence.end - end > 0.4 or start - sentence.start > 0.4:
                sentence.review_reasons.append("Large alignment correction. Check for neighbouring or missed speech.")
            sentence.review_reasons = list(dict.fromkeys(sentence.review_reasons))

    def cut(self, source: AudioMetadata, destination: Path, start: float, end: float,
            prefer_copy: bool = False, cancel=None) -> str:
        if not 0 <= start < end <= source.duration + 0.001:
            raise AppError("Invalid clip timestamps. Fix the sentence before exporting.")
        # Full-file MP3 copy is lossless and exact. Interior MP3 frames have bit-reservoir
        # dependencies and encoder delay; re-encode rather than silently lose phonemes.
        copy = prefer_copy and source.codec == "mp3" and start == 0 and \
            abs(end - source.duration) <= 0.001
        if copy:
            args = [tool_path("ffmpeg"), "-v", "error", "-n", "-i", str(source.path),
                    "-map", "0:a:0", "-c:a", "copy", str(destination)]
        else:
            # 192 kbps requires MPEG-1 Layer III. Lower sample rates use MPEG-2/2.5,
            # which cannot represent the requested bitrate.
            sample_rate = source.sample_rate if source.sample_rate in {
                32000, 44100, 48000
            } else (32000 if source.sample_rate < 32000 else 48000)
            first_sample = round(start * sample_rate)
            last_sample = round(end * sample_rate)
            # Resample before trimming, preserving the source resampler's phase.
            filters = f"aresample={sample_rate}," if sample_rate != source.sample_rate else ""
            filters += f"atrim=start_sample={first_sample}:end_sample={last_sample},asetpts=PTS-STARTPTS"
            args = [tool_path("ffmpeg"), "-v", "error", "-n", "-i", str(source.path),
                    "-af", filters,
                    "-map", "0:a:0", "-map_metadata", "-1", "-c:a", "libmp3lame",
                    "-b:a", "192k", "-ar", str(sample_rate), "-write_xing", "1",
                    str(destination)]
        run_audio(args, timeout=max(120, (end - start) * 3), cancel=cancel)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise AppError("FFmpeg did not create an audio clip.")
        if not copy:
            repair_gapless_padding(destination, last_sample - first_sample)
        actual = self.probe(destination)
        # MP3 duration includes complete frames; tolerate at most three frames.
        tolerance = max(0.09, 3 * 1152 / actual.sample_rate)
        if abs(actual.duration - (end - start)) > tolerance:
            raise AppError("Exported clip duration is incorrect. No partial export will be kept.")
        return "stream copy" if copy else "192 kbps"


def clip_ranges(sentences: list[Sentence], duration: float, before: float = 0.1,
                after: float = 0.15, silences: list[tuple[float, float]] | None = None
                ) -> list[tuple[float, float]]:
    if not all(math.isfinite(v) and 0 <= v <= 2 for v in (before, after)):
        raise AppError("Padding must be between 0 and 2000 milliseconds.")
    ranges = []
    # Neighbours include excluded sentences: padding must never import their speech.
    for index, sentence in enumerate(sentences):
        sentence.validate(duration)
        start, end = max(0, sentence.start - before), min(duration, sentence.end + after)
        if index:
            previous = sentences[index - 1]
            if previous.end > sentence.start + 0.001:
                raise AppError("Sentence timestamps overlap. Correct or merge them before export.")
            boundary = (previous.end + sentence.start) / 2
            # Choose an actual silent point when available, without crossing known words.
            for a, b in silences or []:
                lo, hi = max(a, previous.end), min(b, sentence.start)
                if lo < hi:
                    boundary = (lo + hi) / 2
                    break
            start = max(start, boundary)
        if index + 1 < len(sentences):
            next_sentence = sentences[index + 1]
            if sentence.end > next_sentence.start + 0.001:
                raise AppError("Sentence timestamps overlap. Correct or merge them before export.")
            boundary = (sentence.end + next_sentence.start) / 2
            for a, b in silences or []:
                lo, hi = max(a, sentence.end), min(b, next_sentence.start)
                if lo < hi:
                    boundary = (lo + hi) / 2
                    break
            end = min(end, boundary)
        ranges.append((start, end))
    return ranges
