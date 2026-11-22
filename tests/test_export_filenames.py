import csv
import re
import zipfile

import pytest

from src.models.sentence import Sentence
from src.services.audio_service import AudioService
from src.services.export_service import ExportService, FILENAME_SLUG_LIMIT, filename_for


@pytest.mark.parametrize("text,expected", [
    ("Once upon a time, a young boy lived here.", "001-once-upon-a-time.mp3"),
    ('She said, “Hello, friend!”', "001-she-said-hello-friend.mp3"),
    ("Café déjà vu résumé.", "001-cafe-deja-vu-resume.mp3"),
    ("Don't stop believing in tomorrow.", "001-dont-stop-believing-in.mp3"),
    ("I’m ready—let’s go!", "001-im-ready-lets-go.mp3"),
    ("Hello/world: sample? 42* yes", "001-hello-world-sample-42.mp3"),
    ("..\\..\\CON<PRN>|AUX? NUL*", "001-con-prn-aux-nul.mp3"),
    ("\x00\tHello\nworld\x7f", "001-hello-world.mp3"),
    ("\u202eHello\u200bworld", "001-hello-world.mp3"),
    ("Ｆｕｌｌｗｉｄｔｈ １２３ café!", "001-fullwidth-123-cafe.mp3"),
    ("你好🎤", "001.mp3"),
    ("...!!!", "001.mp3"),
    ("", "001.mp3"),
])
def test_short_filename_is_safe_and_uses_first_words(text, expected, tmp_path):
    name = filename_for(1, text)
    assert name == expected
    assert re.fullmatch(r"[0-9]{3,}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?\.mp3", name)
    assert name.isascii() and len(name) <= 48
    path = tmp_path / name
    path.write_bytes(b"test filename")
    assert path.read_bytes() == b"test filename"


@pytest.mark.parametrize("text", ["a" * 200, "a" * 39 + " b c d",
                                  "a" * 38 + " b c d"])
def test_long_filename_suffix_is_bounded_without_trailing_separator(text):
    name = filename_for(999, text)
    slug = name[4:-4]
    assert len(slug) <= FILENAME_SLUG_LIMIT == 40
    assert slug and not slug.endswith("-")
    assert len(name) <= 48


@pytest.mark.parametrize("number", [0, -1])
def test_invalid_number_cannot_generate_filename(number):
    with pytest.raises(ValueError, match="start at one"):
        filename_for(number, "Example sentence.")


def test_repeated_prefixes_and_large_numbers_remain_unique():
    names = [filename_for(number, "Same first four words and more.")
             for number in range(1, 1002)]
    assert len({name.casefold() for name in names}) == 1001
    assert names[0] == "001-same-first-four-words.mp3"
    assert names[999] == "1000-same-first-four-words.mp3"


@pytest.mark.integration
def test_real_export_keeps_descriptive_names_consistent_in_transcripts_and_zip(tone_audio, tmp_path):
    audio = AudioService()
    metadata = audio.probe(tone_audio)
    sentences = [
        Sentence("Café déjà vu résumé, first ending.", 0.1, 1.0),
        Sentence("Café déjà vu résumé, another ending.", 1.2, 2.0),
        Sentence("你好🎤", 2.2, 3.6),
    ]
    result = ExportService().export(metadata, sentences, tmp_path / "export", make_zip=True)
    expected = ["001-cafe-deja-vu-resume.mp3", "002-cafe-deja-vu-resume.mp3", "003.mp3"]
    with (result.folder / "transcript.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["filename"] for row in rows] == expected
    assert [row["sentence"] for row in rows] == [sentence.text for sentence in sentences]
    lines = (result.folder / "transcript.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split("\t", 1)[0] for line in lines] == expected
    assert {path.name for path in result.folder.glob("*.mp3")} == set(expected)
    for name in expected:
        assert audio.probe(result.folder / name).sample_rate == metadata.sample_rate
    with zipfile.ZipFile(result.archive) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == set(expected + ["transcript.txt", "transcript.csv"])
        for name in archive.namelist():
            assert archive.read(name) == (result.folder / name).read_bytes()
