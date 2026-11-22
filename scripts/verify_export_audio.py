"""Verify exported PCM against source samples and independent speech envelopes."""
import argparse
import csv
import json
from pathlib import Path
import sys
import zipfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.audio_service import AudioService, run_audio, tool_path


def decode(path, rate):
    return np.frombuffer(run_audio([
        tool_path("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:a:0",
        "-ac", "1", "-ar", str(rate), "-f", "f32le", "pipe:1",
    ]), dtype="<f4")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--known-speech-report", type=Path)
    args = parser.parse_args()
    with (args.folder / "transcript.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    truth = json.loads(args.known_speech_report.read_text(encoding="utf-8"))["reference"] \
        if args.known_speech_report else None
    audio = AudioService()
    source_samples = {}
    results = []
    for index, row in enumerate(rows):
        clip = args.folder / row["filename"]
        metadata = audio.probe(clip)
        rate = metadata.sample_rate
        if rate not in source_samples:
            source_samples[rate] = decode(args.source, rate)
        samples = decode(clip, rate)
        start, end = float(row["start_time"]), float(row["end_time"])
        expected_length = round((end - start) * rate)
        assert abs(len(samples) - expected_length) <= 2, (clip, len(samples), expected_length)
        offset = round(start * rate)
        # Source seek uses timestamps with sample-grid rounding; at most two samples.
        comparisons = []
        for shift in range(-2, 3):
            begin = offset + shift
            if begin < 0:
                continue
            reference = source_samples[rate][begin:begin + len(samples)]
            if len(reference) == len(samples):
                correlation = float(np.corrcoef(reference, samples)[0, 1])
                comparisons.append((correlation, shift))
        correlation, shift = max(comparisons)
        assert correlation > 0.995, (row["filename"], correlation)
        if truth:
            # These bounds come from the independently synthesized source waveform,
            # not Whisper or our segmentation code.
            assert start <= truth[index]["speech_start"], row
            assert end >= truth[index]["speech_end"], row
        results.append({"filename": row["filename"], "correlation": correlation,
                        "sample_offset": shift, "decoded_samples": len(samples)})
    archive = args.folder.parent / (args.folder.name + ".zip")
    if archive.is_file():
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None
            assert set(bundle.namelist()) == {p.name for p in args.folder.iterdir()}
            for name in bundle.namelist():
                assert bundle.read(name) == (args.folder / name).read_bytes()
    report = {"verified_clips": len(results),
              "worst_correlation": min(r["correlation"] for r in results),
              "largest_sample_offset": max(abs(r["sample_offset"]) for r in results),
              "known_phonemes_covered": bool(truth), "clips": results}
    (args.folder.parent / "pcm-verification.json").write_text(json.dumps(report, indent=2),
                                                            encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "clips"}))


if __name__ == "__main__":
    main()
