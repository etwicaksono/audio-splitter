"""Correct older FFmpeg MP3 muxers' incomplete gapless padding metadata.

Newer upstream mp3enc.c accumulates padding spread across multiple packets.
For our freshly encoded files the sample count is already known, so restore
the equivalent total padding and tag CRC without changing compressed audio.
"""
from pathlib import Path

from src.services.errors import AppError


def crc16(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def repair_gapless_padding(path: Path, samples: int) -> None:
    # Only invoked on our new MPEG-1/libmp3lame outputs, never user originals.
    with path.open("r+b") as handle:
        header = bytearray(handle.read(4096))
        frame = 0
        if header[:3] == b"ID3":
            if len(header) < 10 or any(v & 0x80 for v in header[6:10]):
                raise AppError("Encoded MP3 has invalid metadata.")
            size = 0
            for value in header[6:10]:
                size = (size << 7) | value
            frame = 10 + size
        bits = int.from_bytes(header[frame:frame + 4], "big")
        if bits >> 21 != 0x7FF or (bits >> 19) & 3 != 3:
            raise AppError("Encoded MP3 has no valid MPEG-1 header.")
        side_info = 17 if (bits >> 6) & 3 == 3 else 32
        tag = frame + 4 + side_info + (0 if bits & (1 << 16) else 2)
        if header[tag:tag + 4] not in (b"Info", b"Xing") or len(header) < tag + 156:
            raise AppError("Encoded MP3 has no gapless header.")
        flags = int.from_bytes(header[tag + 4:tag + 8], "big")
        if flags != 15:
            raise AppError("Encoded MP3 has an unexpected gapless header.")
        frames = int.from_bytes(header[tag + 8:tag + 12], "big")
        packed = int.from_bytes(header[tag + 141:tag + 144], "big")
        delay, old_padding = packed >> 12, packed & 4095
        padding = frames * 1152 - delay - samples
        if not 0 <= padding < 4096:
            raise AppError("Encoded MP3 sample count cannot be verified.")
        if padding == old_padding:
            return
        header[tag + 141:tag + 144] = ((delay << 12) | padding).to_bytes(3, "big")
        header[tag + 154:tag + 156] = b"\0\0"
        # Match upstream's AV_CRC_16_ANSI_LE update over the first 190 frame bytes.
        checksum = crc16(header[frame:frame + 190])
        header[tag + 154:tag + 156] = checksum.to_bytes(2, "big")
        handle.seek(frame)
        handle.write(header[frame:tag + 156])
