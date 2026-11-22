"""Build a Windows onedir release with FFmpeg and native inference libraries."""
import argparse
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-model", type=Path,
                        help="Complete small CTranslate2 model folder to bundle for offline first use")
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on 64-bit Windows.")
    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--onedir",
        "--name", "AI Audio Sentence Splitter", "--contents-directory", "_internal",
        "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
        "--specpath", str(root / "build"),
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "matplotlib", "--exclude-module", "torch",
        "--exclude-module", "tensorflow", "--exclude-module", "transformers",
        "--exclude-module", "pytest",
    ]
    for package in ("faster_whisper", "ctranslate2", "av", "onnxruntime",
                    "tokenizers", "huggingface_hub"):
        command.extend(["--collect-all", package])
    ffmpeg_paths = {}
    for name in ("ffmpeg", "ffprobe"):
        path = os.environ.get(f"{name.upper()}_PATH") or shutil.which(name)
        if not path or not Path(path).is_file():
            raise SystemExit(f"{name} not found. Install FFmpeg or set {name.upper()}_PATH.")
        ffmpeg_paths[name] = path
        command.extend(["--add-binary", f"{path}{os.pathsep}assets/ffmpeg"])
    if args.bundle_model:
        if not all((args.bundle_model / name).is_file() for name in
                   ("model.bin", "config.json", "tokenizer.json")):
            raise SystemExit("Model folder is incomplete.")
        command.extend(["--add-data", f"{args.bundle_model.resolve()}{os.pathsep}models/small"])
    command.append(str(root / "app.py"))
    subprocess.run(command, cwd=root, check=True)
    release = root / "dist" / "AI Audio Sentence Splitter"
    shutil.copy2(root / "README.md", release / "README.md")
    shutil.copy2(root / "THIRD_PARTY_NOTICES.md", release / "THIRD_PARTY_NOTICES.md")
    licenses = release / "licenses"
    licenses.mkdir(exist_ok=True)
    versions = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        versions[name] = dist.version
        for file in dist.files or []:
            if any("license" in part.lower() or "copying" in part.lower() for part in file.parts):
                source = Path(dist.locate_file(file))
                if source.is_file():
                    target = licenses / name / Path(*file.parts[-2:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    for name, binary in ffmpeg_paths.items():
        license_file = Path(binary).parent.parent / "LICENSE"
        if license_file.is_file():
            shutil.copy2(license_file, licenses / f"{name}-LICENSE.txt")
    (release / "dependency-versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    (release / "ffmpeg-build-info.txt").write_bytes(
        subprocess.check_output([ffmpeg_paths["ffmpeg"], "-version"]))
    print(f"Built {release}")


if __name__ == "__main__":
    main()
