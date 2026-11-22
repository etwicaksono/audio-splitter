# Third-party distribution notes

This application uses PySide6/Qt (LGPLv3 or commercial licensing), Faster-Whisper
(MIT), CTranslate2 (MIT), PyAV (BSD), ONNX Runtime (MIT), NumPy (BSD), and other
dependencies. The build script copies installed package license files into
`licenses/` and records the exact package versions.

FFmpeg's license depends on the binary you bundle. The development machine's
Gyan full build may be GPL-enabled. `ffmpeg-build-info.txt` records its build flags.
See https://ffmpeg.org/legal.html and https://www.gyan.dev/ffmpeg/builds/.
Distributors must comply with the bundled build's license, including providing
corresponding source and notices where required. This project does not claim that
copying a binary and its license alone satisfies all redistribution obligations.

Qt libraries remain external DLLs in the onedir release; do not restrict the
recipient's ability to replace LGPL libraries. Review all applicable licenses
before commercial distribution. PyInstaller's exception permits bundling the
application without imposing its GPL license on the application itself.

Whisper model weights have their own model-card terms. Do not remove applicable
model notices when bundling models.
