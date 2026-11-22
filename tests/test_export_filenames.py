import csv
import io
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
@pytest.mark.parametrize("make_zip", [False, True], ids=["folder", "zip-only"])
def test_real_export_keeps_descriptive_names_consistent_in_transcripts_and_zip(tone_audio, tmp_path,
                                                                           make_zip):
    audio = AudioService()
    metadata = audio.probe(tone_audio)
    sentences = [
        Sentence("Café déjà vu résumé, first ending.", 0.1, 1.0),
        Sentence("Café déjà vu résumé, another ending.", 1.2, 2.0),
        Sentence("你好🎤", 2.2, 3.6),
    ]
    result = ExportService().export(metadata, sentences, tmp_path / "export", make_zip=make_zip)
    expected = ["001-cafe-deja-vu-resume.mp3", "002-cafe-deja-vu-resume.mp3", "003.mp3"]
    if make_zip:
        assert result.folder is None and not (tmp_path / "export").exists()
        with zipfile.ZipFile(result.archive) as archive:
            assert archive.testzip() is None
            assert set(archive.namelist()) == set(expected + ["transcript.txt", "transcript.csv"])
            contents = {name: archive.read(name) for name in archive.namelist()}
    else:
        assert result.archive is None
        contents = {path.name: path.read_bytes() for path in result.folder.iterdir()}
    rows = list(csv.DictReader(io.StringIO(contents["transcript.csv"].decode("utf-8"))))
    assert [row["filename"] for row in rows] == expected
    assert [row["sentence"] for row in rows] == [sentence.text for sentence in sentences]
    lines = contents["transcript.txt"].decode("utf-8").splitlines()
    assert [line.split("\t", 1)[0] for line in lines] == expected
    assert {name for name in contents if name.endswith(".mp3")} == set(expected)
    inspection = tmp_path / "inspection"
    inspection.mkdir()
    for name in expected:
        clip = inspection / name
        clip.write_bytes(contents[name])
        assert audio.probe(clip).sample_rate == metadata.sample_rate
