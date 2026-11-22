"""Conservative, timestamp-aware English sentence detection.

Pauses propose boundaries, but do not prove them. Uncertain decisions always
carry a review reason and cannot be exported until acknowledged.
"""
import math
import re

from src.models.sentence import Sentence, Word, join_words
from src.services.errors import AppError

TITLES = {"mr", "mrs", "ms", "dr", "prof", "rev", "hon", "sir", "st", "gen", "capt", "lt"}
ABBREVIATIONS = {
    "etc", "vs", "e.g", "i.e", "a.m", "p.m", "u.s", "u.k", "jr", "sr", "inc",
    "ltd", "co", "dept", "approx", "no", "vol", "fig", "mt", "ave", "jan", "feb",
    "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}
STARTERS = {
    "i", "he", "she", "they", "we", "it", "the", "this", "that", "then", "there",
    "however", "suddenly", "meanwhile", "every", "once", "when", "what", "why",
    "how", "where", "who", "do", "did", "is", "are", "can", "will", "you",
}
REPORTING_VERBS = {"said", "asked", "replied", "whispered", "shouted", "answered",
                   "cried", "murmured", "exclaimed", "added", "yelled"}


def _bare(text: str) -> str:
    return text.strip().rstrip("\"'”’)]}")


def _next_text(words: list[Word], index: int) -> str:
    return words[index].text.strip().lstrip("\"'“‘([{") if index < len(words) else ""


def _reporting_clause(words: list[Word], index: int) -> bool:
    tail = [re.sub(r"[^a-z]", "", w.text.lower()) for w in words[index:index + 4]]
    if not tail or words[index].text.lstrip().startswith(('"', "“")):
        return False
    # Do not look past another punctuation boundary, or mistake "Then he said..."
    # for attribution to the preceding quotation.
    if tail[0] in {"then", "however", "suddenly", "meanwhile"}:
        return False
    for offset, token in enumerate(tail[1:], 1):
        if token in REPORTING_VERBS:
            return True
        if _bare(words[index + offset].text).endswith((".", "?", "!")):
            break
    return False


def _terminal(words: list[Word], index: int) -> tuple[bool, str | None]:
    token = _bare(words[index].text)
    if not token.endswith((".", "?", "!")):
        return False, None
    # Quoted speech followed by attribution belongs to the same grammatical sentence.
    closed_quote = words[index].text.strip().endswith(('"', "”", "'", "’"))
    if closed_quote and _reporting_clause(words, index + 1):
        return False, None
    if token.endswith(("?", "!")):
        return True, None
    if token.endswith("...") or token.endswith("…"):
        return False, "Ellipsis is ambiguous."
    stem = token.rstrip(".").lower().lstrip("\"'“‘(")
    next_text = _next_text(words, index + 1)
    if stem in TITLES:
        return False, None
    if re.fullmatch(r"[A-Za-z]", stem):
        return False, None  # J. R. Smith, A. Smith
    if stem in ABBREVIATIONS or re.fullmatch(r"(?:[a-z]\.)+[a-z]", stem):
        if not next_text:
            return True, "Sentence ends with an abbreviation."
        # Time abbreviations and etc. can also occur at the end of a sentence.
        first = next_text.split()[0].rstrip(",.!?").lower()
        if next_text[:1].isupper() and first in STARTERS:
            return True, "Possible sentence-ending abbreviation."
        if next_text[:1].isupper():
            return False, "Abbreviation before a capitalized word. Confirm the sentence boundary."
        return False, None
    return True, None


def detect_sentences(words: list[Word], duration: float,
                     pause_threshold: float = 0.85) -> list[Sentence]:
    if not words:
        raise AppError("No spoken words were found. Try another model or check the recording.")
    previous_start = -1.0
    for word in words:
        if (not all(math.isfinite(v) for v in (word.start, word.end)) or
                not 0 <= word.start <= word.end <= duration + 0.001 or
                word.start < previous_start):
            raise AppError("Word timestamps are invalid. Retry transcription with another model.")
        previous_start = word.start
    result: list[Sentence] = []
    start = 0
    reasons: list[str] = []
    for index, word in enumerate(words):
        terminal, ambiguity = _terminal(words, index)
        if ambiguity:
            reasons.append(ambiguity)
        gap = words[index + 1].start - word.end if index + 1 < len(words) else 0
        if gap < 0:
            reasons.append("Overlapping word timestamps. Inspect the boundary.")
        if word.probability < 0.45:
            reasons.append("Low-confidence transcription. Check spoken text and timing.")
        if word.end == word.start:
            reasons.append("A word has zero-length alignment. Check for missing speech or hallucination.")
        pause_boundary = (not terminal and index + 1 < len(words) and
                          gap >= pause_threshold)
        long_run = index - start + 1 >= 60 and gap >= 0.15
        at_end = index == len(words) - 1
        if terminal or pause_boundary or long_run or at_end:
            if pause_boundary:
                reasons.append("Pause without sentence punctuation. Confirm or merge.")
            if long_run and not terminal:
                reasons.append("Long unpunctuated passage. Confirm or split.")
            if at_end and not terminal:
                reasons.append("Final passage has no clear sentence-ending punctuation.")
            if terminal and index + 1 < len(words) and gap <= 0.04:
                reasons.append("Little or no pause at boundary. Preview for word truncation.")
            chunk = words[start:index + 1]
            chunk_end = max(w.end for w in chunk)
            if chunk_end <= chunk[0].start:
                reasons.append("Passage has no timed speech; combined with a neighbour for review.")
                if not at_end:
                    continue
                if not result:
                    raise AppError("No usable word timing was found. Try another model.")
                previous = result[-1]
                previous.text += " " + join_words(chunk)
                previous.words.extend(chunk)
                previous.end = max(previous.end, chunk_end)
                previous.review_reasons.extend(list(dict.fromkeys(reasons)))
                break
            result.append(Sentence(join_words(chunk), chunk[0].start,
                                   min(duration, chunk_end), chunk,
                                   review_reasons=list(dict.fromkeys(reasons))))
            start = index + 1
            # A pause-driven split makes both sides uncertain.
            reasons = ["Begins after an inferred pause boundary. Confirm or merge."] \
                if pause_boundary or long_run else []
            if terminal and index + 1 < len(words) and gap <= 0.04:
                reasons.append("Begins at a tight or overlapping word boundary. Preview carefully.")
    return result
