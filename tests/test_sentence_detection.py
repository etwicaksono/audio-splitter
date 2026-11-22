import pytest

from src.models.sentence import Sentence, Word, merge_sentences, split_sentence
from src.services.errors import AppError
from src.services.sentence_detection import detect_sentences


def words_for(text, gap=0.08):
    tokens = text.split()
    return [Word(token, i * (0.2 + gap), i * (0.2 + gap) + 0.2) for i, token in enumerate(tokens)]


@pytest.mark.parametrize("text,expected", [
    ("Once upon a time, a boy lived. He went to school.", 2),
    ("Are you ready? Yes! Let's go.", 3),
    ('He said, "Go now!" Then he left.', 2),
    ('"Where are you?" she asked. "Here!" he replied.', 2),
    ('"Where are you?" Tom asked. Mary left.', 2),
    ('"Come here!" the young boy shouted. They ran.', 2),
    ('"Hello." "Goodbye."', 2),
    ("Dr. Smith met Mrs. Jones. They talked.", 2),
    ("J. R. Smith lives here. He is happy.", 2),
    ("The U.S. Army arrived. They stayed.", 2),
    ("Meet at 3 p.m. outside the school. Bring a coat.", 2),
    ("It cost 3.14 dollars. That was cheap.", 2),
    ("Bring fruit, e.g. apples and pears. We will eat.", 2),
    ("He visited St. Louis. It was sunny.", 2),
    ("She bought books etc. They were useful.", 2),
    ("One sentence without punctuation", 1),
    ("He paused... and continued. Then stopped.", 2),
])
def test_boundaries(text, expected):
    words = words_for(text)
    result = detect_sentences(words, words[-1].end)
    assert len(result) == expected
    assert [word for sentence in result for word in sentence.words] == words
    assert all(s.start == s.words[0].start and s.end == s.words[-1].end for s in result)


def test_missing_punctuation_marks_both_sides():
    words = [Word("Hello", 0.2, 0.5), Word("there", 0.6, 1.0),
             Word("She", 2.1, 2.4), Word("left", 2.5, 2.8)]
    result = detect_sentences(words, 3)
    assert len(result) == 2
    assert all(s.needs_review for s in result)


def test_abbreviation_at_sentence_end_requires_review():
    words = words_for("She moved to the U.S. He followed.")
    result = detect_sentences(words, words[-1].end)
    assert len(result) == 2
    assert result[0].needs_review


def test_no_pause_boundary_is_flagged():
    words = [Word("Hello.", 0, 0.5), Word("Goodbye.", 0.5, 1)]
    assert detect_sentences(words, 1)[0].needs_review


@pytest.mark.parametrize("words", [
    [], [Word("Hello.", 1, 0)], [Word("Hello.", float("nan"), 1)],
    [Word("Hello.", 0, 0)], [Word("Hello.", 0, 8)],
    [Word("One", 2, 3), Word("two.", 1, 2)],
])
def test_invalid_timestamps_are_not_guessed(words):
    with pytest.raises(AppError):
        detect_sentences(words, 4)


def test_long_unpunctuated_run():
    words = words_for(" ".join(["word"] * 130), gap=0.2)
    result = detect_sentences(words, words[-1].end)
    assert len(result) == 3
    assert all(s.needs_review for s in result)


def test_low_confidence_is_flagged():
    assert detect_sentences([Word("Hello.", 0, 1, 0.2)], 1)[0].needs_review


def test_split_and_merge_preserve_words_and_bounds():
    words = words_for("Hello there. Goodbye now.")
    sentence = Sentence("Hello there. Goodbye now.", words[0].start, words[-1].end, words)
    left, right = split_sentence(sentence, 2)
    assert left.text == "Hello there."
    assert right.text == "Goodbye now."
    merged = merge_sentences(left, right)
    assert merged.words == words
    assert merged.start == sentence.start and merged.end == sentence.end
    assert merged.needs_review


@pytest.mark.parametrize("index", [0, 4, -1, 10])
def test_invalid_split(index):
    words = words_for("Hello there. Goodbye now.")
    with pytest.raises(ValueError):
        split_sentence(Sentence("test", 0, 2, words), index)


def test_cannot_trim_words_or_merge_inconsistent_inclusion():
    sentence = Sentence("Hello.", 0.3, 1, [Word("Hello.", 0.2, 1)])
    with pytest.raises(ValueError):
        sentence.validate(2)
    with pytest.raises(ValueError):
        merge_sentences(Sentence("One.", 0, 1), Sentence("Two.", 1, 2, include=False))


def test_nested_word_timestamps_cannot_trim_earlier_word():
    words = [Word("Long", 0, 1.5), Word("word.", 0.5, 1.0)]
    sentence = detect_sentences(words, 2)[0]
    assert sentence.end == 1.5
    sentence.end = 1.1
    with pytest.raises(ValueError):
        sentence.validate(2)


def test_zero_duration_word_is_preserved_and_reviewable():
    words = [Word("The", 0.1, 0.1), Word("boy", 0.1, 0.5), Word("left.", 0.6, 0.9),
             Word("He", 1.3, 1.5), Word("ran.", 1.6, 2.0)]
    result = detect_sentences(words, 2)
    assert len(result) == 2
    assert result[0].needs_review and not result[1].needs_review
    assert result[0].words == words[:3]
    result[0].validate(2)


def test_zero_duration_only_sentence_does_not_get_guessed_boundaries():
    words = [Word("Yes.", 0.1, 0.1), Word("He", 0.5, 0.7), Word("left.", 0.8, 1)]
    result = detect_sentences(words, 1)
    assert len(result) == 1 and result[0].needs_review
    assert result[0].words == words
