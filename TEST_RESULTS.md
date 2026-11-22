# Test results

Validated on this Windows 11 x64 machine on 2026-11-22.

## Environment

- Python 3.11.18, PySide6 6.12.0.
- Faster-Whisper 1.2.1, CTranslate2 4.9.0.
- Default small model, CPU, int8, English, word timestamps, VAD.
- 12 logical CPUs, 16 GB RAM. Inference uses at most 8 threads.
- Exact build dependencies are recorded in the release's `dependency-versions.json`.

## Automated suite

Final Windows build ran `python -m pytest -q`:

**79 passed, 1 warning in 31.05 seconds.**

Ruff: **All checks passed.**

Coverage includes punctuation, English abbreviations, quoted dialogue and
attribution, unpunctuated passages, zero-duration alignment tokens, timestamp
validation, tight/overlapping boundaries, split/merge, UTF-8 TXT/CSV, three-digit
numbering and expansion beyond 999, exclusions, real FFmpeg metadata/waveforms/
cuts, bitrate/sample-rate handling, full MP3 stream copy, gapless metadata/CRC,
partial MP3 frames in mono/stereo, ZIP integrity, cancellation, disk-space errors,
failure cleanup, and actual Qt import/drag/drop/edit/split/merge/preview/export
controls.

The warning is a deprecated Qt drag-event constructor used in a test. The build
also warns about missing `onnx` for ONNX Runtime's unused quantization tools.
Runtime ONNX inference/VAD, CTranslate2 int8 transcription, and exports succeeded.

## Final executable, real recording

Release:
`dist/AI Audio Sentence Splitter/AI Audio Sentence Splitter.exe`

The **packaged executable**, not source Python, ran with PATH restricted to
Windows system directories and without PYTHONPATH/PYTHONHOME. It used bundled
FFmpeg/FFprobe and the previously downloaded model with Offline mode enabled.
No system Python or FFmpeg command was available to the application.

Observed real desktop workflow:

- Imported `storytelling.mp3`, 242.773333 seconds, 48 kHz mono.
- Transcribed the entire recording: **77 sentence candidates**.
- **64 candidates required review** under default conservative silence refinement.
- Played and automatically stopped an individual sentence preview.
- The diagnostic deliberately excluded those 64 candidates, rather than falsely
  checking Reviewed. It exported **13 unflagged MP3s**, TXT, CSV, and ZIP.
- GUI controls remained responsive; its independent 100 ms timer fired 1476 times.
- No errors were reported.

Measured from a fresh process:

| Measurement | Observed |
| --- | ---: |
| Import | 1.42 s |
| Transcription, segmentation, refinement | 147.10 s |
| Export 13 clips, transcripts, ZIP | 13.02 s |
| In-app workflow including preview | 163.50 s |
| Whole process wall time, including startup | 191.89 s |
| Peak process-tree resident memory | 756.45 MB |

These numbers include first model loading in that process, but not the earlier
model download. They are observations on this machine, not performance guarantees.

Every final exported clip was decoded and compared to the corresponding original
source interval. The **unchanged strict checks passed for all 13 clips**:

- Decoded sample counts within two samples of the CSV interval's sample grid.
- Worst source/output waveform correlation: **0.9999771114** (required >0.995).
- Largest alignment offset: **one sample** at 48 kHz.
- ZIP CRC validation and byte-for-byte agreement with all exported files passed.

Evidence:
`output/release-verified/report.json`, `measurements.json`,
`pcm-verification.json`, `desktop.png`, `clips/`, and `clips.zip`.
Build log: `output/release-build.log`.

This verifies cutting fidelity and timing against the original signal. It does
**not** constitute a human listening review of every sentence in the recording.
Review the 64 flagged candidates before exporting the complete story.

## Independent known-speech validation

Five fixed English sentences were synthesized locally with Windows SAPI and
concatenated with known silence intervals. Reference speech starts/ends came from
the independently generated waveform, not from Whisper or sentence detection.

Final audio checks: **5/5 passed**.

- All intended first and last phonemes lie inside the exported intervals.
- No neighboring sentence is included.
- Worst waveform correlation: **0.9999992418**.
- Largest sample alignment offset: **zero samples**.
- Strict decoded sample counts and ZIP/file-content checks passed.

Evidence: `output/final-known/pcm-verification.json` and `clips/`.
Reference fixture and text: `output/known-speech-final/`.

**Known recognition failure:** re-transcribing the five individual clips with the
small model matched **4/5** known texts. It heard “old owl” as “old arrow” in the
third complete clip. The strict text check exited with failure and its discrepancy
is preserved in `output/known-speech-final/validation.json`. The independently
verified audio still contains the complete original sentence.

Earlier development checks also found and fixed zero-duration alignment aborts,
about 32 ms of final-phoneme truncation despite fixed padding, older FFmpeg muxer
gapless-padding metadata errors, and resampler phase changes. The final release
passes the original audio gates without loosening them.

## Packaging and limitations

- PyInstaller successfully built the onedir Windows executable with its runtime
  dependencies and audio tools. Distribute the **whole folder**, not only the EXE.
- The small model's download and cached offline loading were exercised.
- Base/medium selections and common code paths are implemented, but their actual
  weights were not downloaded or benchmarked during this session.
- Optional embedded-model packaging is provided, but this release uses cache/
  local-folder models rather than including model weights.
- Validation used this Windows machine, not a separate clean Windows VM.
- The executable is unsigned. Public distribution also requires compliance with
  bundled Qt/FFmpeg and other dependency licenses.
- Whisper is not guaranteed transcription or phonetic alignment. Noisy audio,
  ambiguous punctuation, and uncertain quiet edges can require substantial manual
  review. This application intentionally blocks included unreviewed candidates.
- Earlier `output/` folders are development evidence, not final validated exports.
  Use `release-verified/` for the final recording smoke test.
