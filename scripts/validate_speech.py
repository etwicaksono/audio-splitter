"""Independent known-text Windows TTS fixture, real ASR and actual clip checks."""
import argparse
import csv
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.audio_service import AudioService, clip_ranges
from src.services.export_service import ExportService
from src.services.sentence_detection import detect_sentences
from src.services.transcription_service import TranscriptionService


TEXTS = [
    "Once upon a time, a young boy lived in a quiet village.",
    "Every morning, he carried a red book to school.",
    "Why did the old owl stay awake all night?",
    "The girl shouted, run home before the storm arrives!",
    "At sunset, everyone gathered beside the river.",
]


def normalized(text):
    return re.findall(r"[a-z]+", text.lower())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    # Locally installed Windows speech voice, no external speech service.
    script = """
param([string]$Directory)
$voice = New-Object -ComObject SAPI.SpVoice
$texts = @(
  'Once upon a time, a young boy lived in a quiet village.',
  'Every morning, he carried a red book to school.',
  'Why did the old owl stay awake all night?',
  'The girl shouted, run home before the storm arrives!',
  'At sunset, everyone gathered beside the river.'
)
for ($i = 0; $i -lt $texts.Count; $i++) {
    $stream = New-Object -ComObject SAPI.SpFileStream
    $stream.Open((Join-Path $Directory ("reference-{0}.wav" -f $i)), 3, $false)
    $voice.AudioOutputStream = $stream
    [void]$voice.Speak($texts[$i])
    $stream.Close()
}
"""
    synthesizer = directory / "synthesize.ps1"
    synthesizer.write_text(script, encoding="utf-8")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", str(synthesizer), str(directory)], check=True)
    chunks = []
    reference = []
    position = 0
    rate = None
    for number, text in enumerate(TEXTS):
        with wave.open(str(directory / f"reference-{number}.wav"), "rb") as handle:
            assert handle.getnchannels() == 1 and handle.getsampwidth() == 2
            rate = handle.getframerate()
            data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2")
        silence = np.zeros(rate, dtype="<i2")
        chunks.append(silence)
        position += rate
        active = np.flatnonzero(abs(data.astype(np.int32)) > 90)
        reference.append({
            "text": text, "speech_start": (position + active[0]) / rate,
            "speech_end": (position + active[-1] + 1) / rate,
        })
        chunks.append(data)
        position += len(data)
    chunks.append(np.zeros(rate, dtype="<i2"))
    source = directory / "known-story.wav"
    with wave.open(str(source), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.concatenate(chunks).astype("<i2").tobytes())
    began = time.perf_counter()
    audio = AudioService()
    metadata = audio.probe(source)
    words, _ = TranscriptionService(offline=True).transcribe(source, metadata.duration)
    sentences = detect_sentences(words, metadata.duration)
    assert len(sentences) == len(TEXTS), [s.text for s in sentences]
    silences = audio.silences(metadata)
    audio.refine_boundaries(metadata, sentences, silences)
    ranges = clip_ranges(sentences, metadata.duration, silences=silences)
    for sentence, truth, (start, end) in zip(sentences, reference, ranges):
        assert normalized(sentence.text) == normalized(truth["text"]), (sentence.text, truth)
        assert start <= truth["speech_start"], ("First phoneme truncated", start, truth)
        assert end >= truth["speech_end"], ("Last phoneme truncated", end, truth)
        # Ground-truth fixture supplies the review a human would otherwise perform.
        sentence.reviewed = True
    result = ExportService().export(metadata, sentences, directory / "clips", make_zip=True,
                                    silences=silences)
    with (result.folder / "transcript.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    model_results = []
    for row, truth in zip(rows, reference):
        clip = result.folder / row["filename"]
        clip_metadata = audio.probe(clip)
        clip_words, _ = TranscriptionService(offline=True).transcribe(clip, clip_metadata.duration)
        text = "".join(w.text for w in clip_words)
        model_results.append({"filename": row["filename"], "transcribed": text,
                              "expected": truth["text"],
                              "matches": normalized(text) == normalized(truth["text"])})
    report = {"duration_seconds": metadata.duration, "elapsed_seconds": time.perf_counter() - began,
              "reference": reference, "sentences": [asdict(s) for s in sentences],
              "exported_clip_asr": model_results,
              "all_clips_match": all(r["matches"] for r in model_results)}
    (directory / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    assert report["all_clips_match"], model_results
    print(json.dumps({"known_sentences": len(TEXTS), "all_clips_match": True,
                      "elapsed_seconds": report["elapsed_seconds"]}))


if __name__ == "__main__":
    main()
