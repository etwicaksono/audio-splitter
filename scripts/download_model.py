import argparse
from pathlib import Path

from faster_whisper.utils import download_model


def main():
    parser = argparse.ArgumentParser(description="Download a local Faster-Whisper model for offline use.")
    parser.add_argument("model", choices=["base", "small", "medium"], default="small", nargs="?")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    directory = args.output or root / "models" / args.model
    download_model(args.model, output_dir=str(directory.resolve()))
    print(f"Model ready: {directory.resolve()}")


if __name__ == "__main__":
    main()
