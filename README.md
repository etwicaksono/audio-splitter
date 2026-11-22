# AI Audio Sentence Splitter

A Windows 11 desktop application that transcribes English recordings locally,
detects sentences, lets you preview/edit their boundaries, and exports numbered
MP3s, UTF-8 TXT/CSV transcripts, and an optional ZIP.

## Use the Windows application (no Python required)

1. Copy or extract the **entire** `dist/AI Audio Sentence Splitter/` folder.
2. Double-click `AI Audio Sentence Splitter.exe`.
3. Browse for audio, or drag one MP3/WAV/M4A/FLAC/AAC onto the window.
4. Choose a model, normally **small**, then click **Start Processing**.
5. Preview sentences. Double-click text/start/end cells to edit. Times are seconds.
   Use **Merge with next** or **Split at word** to correct segmentation. Uncheck
   **Include** to omit a sentence.
6. Yellow **Needs review** rows cannot be exported while included. Hover their
   status to read the reason, preview and correct them, then check **Reviewed**.
7. Set padding if needed, then **Export MP3** or **Export ZIP**. Choose a parent
   folder and a new folder name. Existing outputs are never overwritten.

Both export buttons produce MP3s plus `transcript.txt` and `transcript.csv`.
ZIP additionally creates a sibling ZIP containing the same files.
`001.mp3` through `999.mp3` use three digits; the next is `1000.mp3`.
CSV timestamps describe the actual padded source interval, not the unpadded words.
Padding defaults to 100 ms before and 150 ms after, capped at neighboring sentence
boundaries, including excluded sentences.

### Select and update several sentences

Use **Ctrl-click** for separate rows or **Shift-click** for a range. The
**Select all rows / Unselect all rows** toggle changes row selection only, not
the Include or Reviewed values. The toolbar shows how many rows are selected.

- **Include selected / Reviewed selected** check or uncheck the selected rows.
- **Include all / Reviewed all** check or uncheck every sentence, including rows
  outside the current selection. Click again to clear every value.
- A dash means the target rows have mixed values. Clicking it checks all target
  rows; the next click unchecks them. A checkbox in the table still changes only
  its own sentence. Selection is retained after edits and checkbox changes.

Mark **Reviewed** only after checking the clips. Bulk review is a manual action;
it does not validate speech or remove the original review reasons. Unchecking it
restores **Needs review** for flagged sentences. Merge/split require exactly one
selected row. Bulk controls are disabled while a background task is running.
On small windows, scroll the main view to reach controls without clipping them.

## Models and offline use

CPU inference and int8 quantization are always used. No GPU is required.
Models: **base** (fastest), **small** (default), **medium** (slower, more RAM).
Only one model is loaded at a time and it is released after transcription.

First use downloads the selected model from Hugging Face. Allow several minutes
and enough free disk space (approximately 150 MB/base, 500 MB/small, 1.6 GB/medium,
plus cache overhead). The cache lives under Windows' local application cache:
`%LOCALAPPDATA%\AudioSplitter\AI Audio Sentence Splitter\Cache`.

After downloading, check **Offline mode**. Cached inference needs no internet.
Alternatively, **Local model folder** accepts a complete Faster-Whisper/CTranslate2
folder with `model.bin`, `config.json`, `tokenizer.json`, and its associated model
files. It does not accept an OpenAI `.pt` checkpoint.

Developers can pre-download:

```powershell
.\.venv\Scripts\python.exe scripts\download_model.py small
```

`models/small/` is automatically used when present in source. Build with
`-BundleModel` below for offline first use in a distributable release.

## Source installation (developers only)

Use 64-bit Python **3.11 or newer** on Windows 11. Python 3.11 is the tested build
version. Install FFmpeg with both `ffmpeg.exe` and `ffprobe.exe` on PATH. The
FFmpeg build must support `libmp3lame`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
```

For runtime dependencies only, install `requirements.txt`. Double-click
`launch.bat` to launch an existing source environment or built release without
opening PowerShell. `storytelling.mp3` is left unchanged.

## Repository commands with Make (Windows)

Use GNU Make 3.81 or newer and Windows PowerShell. Run commands from the repository
root, or use `make -C "D:\Project\audio-splitter" <target>`. Run `make --version`
to check availability. If Make is missing, install a Windows GNU Make distribution
such as GnuWin32 and add its `bin` folder to PATH.

```powershell
make help        # Show available commands; also the default for plain make
make install     # Create/reuse .venv and install development dependencies
make run         # Open the desktop app
make test        # Run pytest
make lint        # Check Python code with Ruff
make check       # Run lint and tests
make doctor      # Check Python, packages, FFmpeg, and FFprobe
make model MODEL=small
make build
make build BUNDLE_MODEL=models/small
make clean
```

`make setup` creates the environment without downloading application dependencies
and ensures pip exists, including for environments created with uv. New
environments require Python 3.11+. The existing project environment is preferred
as a bootstrap when available, then `py -3.11`, then `python`.

Custom paths, including spaces, are supported:

```powershell
make install "PYTHON=C:/Python 3.11/python.exe" "VENV=.venv custom"
make test "VENV=.venv custom"
make build "BUNDLE_MODEL=D:/Models/whisper small"
```

`PYTHON` selects only the bootstrap interpreter for a **new** environment. Tasks
always use the chosen environment's Python; there is no need to activate it.
`make build` calls the existing Windows build script and runs its checks before
packaging. `make model` needs internet unless the selected files are already local.

`make clean` removes only PyInstaller's `build/` and known project cache folders.
It keeps `dist/`, `models/`, `output/`, `.venv`, `.tooling`, and original recordings.
It refuses to delete linked directories or follow junctions. Model downloads,
builds, and cleanup run only when explicitly requested. Commands propagate failures
to Make. Execution-policy bypass is limited to the child PowerShell process.

## Build a Windows executable

Run on 64-bit Windows with the development dependencies installed:

```powershell
.\build_windows.ps1
# Optional: include a downloaded small model for offline first use:
.\build_windows.ps1 -BundleModel .\models\small
```

If your shell blocks local scripts, use a process-scoped execution policy:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_windows.ps1
```

This does not change machine-wide policy. The script runs tests and Ruff first,
then PyInstaller. It bundles Python, Qt multimedia plugins, inference/native
libraries, VAD model data, FFmpeg, and FFprobe. Use `-Python C:\path\python.exe`
to select a different environment. You can set `FFMPEG_PATH` and `FFPROBE_PATH`
to explicit binary paths if they are not on PATH.

Output: `dist/AI Audio Sentence Splitter/AI Audio Sentence Splitter.exe`.
Distribute the **whole folder**, including `_internal/`, licenses, and notices.
This is an onedir executable, not an installer or a standalone single `.exe`.
No Python installation is needed on the recipient's computer. The binary is
unsigned; Windows SmartScreen may warn. Sign releases for public distribution.
Read `THIRD_PARTY_NOTICES.md` before redistributing bundled FFmpeg/Qt.

## Tests and diagnostics

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app.py src tests scripts
```

Tests cover English punctuation, abbreviations, quoted dialogue, missing
punctuation, timestamp safety, split/merge, exclusions, numbering, UTF-8
transcripts, actual FFmpeg cutting, ZIP integrity, failure cleanup, and actual
Qt import/edit/preview controls. Waveform correlation against independently
generated WAV audio checks that MP3 cuts keep the intended samples.

An opt-in developer smoke test uses the real desktop controls/workers:

```powershell
.\.venv\Scripts\python.exe app.py --self-test storytelling.mp3 --report-dir output\smoke
# Once cached:
& ".\dist\AI Audio Sentence Splitter\AI Audio Sentence Splitter.exe" --self-test storytelling.mp3 --report-dir output\exe-smoke --offline
```

Use a **new** report folder each time. This writes a screenshot, detected words/
sentences, timings, clips, transcripts, and ZIP. It intentionally **excludes**
sentences requiring manual review instead of pretending a human reviewed them.

Independent Windows speech and audio-fidelity checks:

```powershell
.\.venv\Scripts\python.exe scripts\validate_speech.py --output output\known-speech-test
.\.venv\Scripts\python.exe scripts\verify_export_audio.py --source output\known-speech-test\known-story.wav --folder output\known-speech-test\clips --known-speech-report output\known-speech-test\validation.json
```

The first check compares speech recognition to known text and may fail on a
recognition mistake even when the exported audio is complete. Its JSON retains
the discrepancy. The second independently checks source-waveform coverage,
decoded sample counts, audio correlation, and ZIP contents.

## Accuracy and limitations

- Whisper text, punctuation, and word timestamps are estimates, not guaranteed
  phonetic alignment. Preview every clip when exact sentence isolation matters.
- Missing punctuation, long pauses, ambiguous abbreviations, low-confidence
  words, zero-length alignment tokens, and tight boundaries are flagged. Pauses
  are evidence, not proof of a sentence end. Dialogue with attribution is kept
  together where recognized.
- Text edits do not re-align speech. Split at a timestamped word boundary, then
  edit the two texts; time edits cannot trim away known words or overlap neighbors.
- Interior MP3 cuts re-encode with libmp3lame at 192 kbps. Stream copy is used
  only for a complete MP3 when safe, because MP3 frame/bit-reservoir boundaries
  can otherwise truncate speech. 32/44.1/48 kHz source rates are preserved;
  lower rates are upsampled to 32 kHz to support 192 kbps MPEG-1 MP3.
- FFmpeg trims decoded source samples before encoding. The application also
  verifies/corrects the new MP3's gapless padding metadata for older FFmpeg muxers.
  This does not alter the compressed audio payload or the original file.
- Configurable padding is limited to 0–2000 ms. It never crosses known neighboring
  words. Silence refinement expands estimated word boundaries to nearby quiet
  edges before adding padding. It also corrects initial alignment that includes
  a long confirmed silence, and marks this correction for review.
- Noise or background music may prevent reliable silence detection. The default
  conservative mode can flag many sentences rather than claim their timing is
  exact. Disabling silence refinement uses word timestamps and padding alone;
  careful manual preview remains necessary.
- Model loading/download and one inference step cannot cancel immediately.
  Closing while busy requests cancellation and waits, rather than killing a thread.
- Waveform decoding streams through bounded buffers. Faster-Whisper itself
  decodes a recording to a 16 kHz mono array, so very long recordings use more RAM.
- Language is explicitly **English**, not automatic language detection.
- Edits remain in memory until export and are replaced if you transcribe again.
- Errors leave the original untouched. Failed/cancelled exports remove their
  staging directory, not pre-existing user output. A sudden OS/process crash can
  leave a hidden `.sentence-export-*` staging folder; inspect before removing it.

See `TEST_RESULTS.md` for observed validation, rather than assumed capabilities.

## Structure

`app.py` is the desktop entry point. `src/ui/` contains Qt controls,
`src/workers/` background operations, `src/services/` transcription/detection/
audio/export, and `src/models/` timestamped words and editable sentences.
`scripts/` contains model download and packaging utilities. `output/` is available
for exports, but users may choose any writable folder.
