from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    probability: float = 1.0


@dataclass
class Sentence:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)
    include: bool = True
    review_reasons: list[str] = field(default_factory=list)
    reviewed: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons) and not self.reviewed

    def validate(self, duration: float) -> None:
        if not all(math.isfinite(v) for v in (self.start, self.end)):
            raise ValueError("Timestamps must be finite numbers.")
        if not 0 <= self.start < self.end <= duration + 0.001:
            raise ValueError("Start must be before end, within the recording.")
        if not self.text.strip():
            raise ValueError("Sentence text cannot be empty.")
        if self.words:
            if self.start > min(word.start for word in self.words) + 0.001:
                raise ValueError("Start would cut the first word. Choose an earlier time.")
            if self.end < max(word.end for word in self.words) - 0.001:
                raise ValueError("End would cut the last word. Choose a later time.")


def join_words(words: list[Word]) -> str:
    # Whisper usually includes leading spaces; also accept plain tokens in tests/projects.
    text = ""
    for word in words:
        token = word.text
        if not text:
            text = token.strip()
        elif token[:1].isspace() or token[:1] in ",.!?;:)]}”’":
            text += token
        else:
            text += " " + token
    return text.strip()


def merge_sentences(first: Sentence, second: Sentence) -> Sentence:
    if first.include != second.include:
        raise ValueError("Both sentences must have the same Include setting before merging.")
    return Sentence(
        f"{first.text.rstrip()} {second.text.lstrip()}",
        min(first.start, second.start), max(first.end, second.end),
        first.words + second.words, first.include,
        list(dict.fromkeys(first.review_reasons + second.review_reasons
                           + ["Manually merged. Preview to confirm one sentence."])),
    )


def split_sentence(sentence: Sentence, after_word: int) -> tuple[Sentence, Sentence]:
    if not 1 <= after_word < len(sentence.words):
        raise ValueError("Select a word boundary inside the sentence.")
    left, right = sentence.words[:after_word], sentence.words[after_word:]
    left_end = max(word.end for word in left)
    if left_end > right[0].start:
        raise ValueError("These word timestamps overlap. Choose a different split point.")
    reason = ["Manually split. Check the text and preview both clips."]
    return (
        Sentence(join_words(left), sentence.start, left_end, left,
                 sentence.include, reason.copy()),
        Sentence(join_words(right), right[0].start, sentence.end, right,
                 sentence.include, reason.copy()),
    )
