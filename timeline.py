"""Timing: caption chunks, narration-synced bullet reveals, frame states and SRT, from word timestamps."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from .speech import Word

_SENTENCE_END = (".", "!", "?", ";", ":")
_KEY_RE = re.compile(r"[a-z0-9]+")
_STOP = {"this", "that", "with", "from", "they", "their", "there", "have", "were", "what", "which", "about",
         "into", "than", "then", "them", "these", "those", "your", "will", "would", "could", "should", "also"}


@dataclass(frozen=True)
class Token:
    """One spoken word as displayed: the narration's own spelling and punctuation, with timing."""
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class FrameState:
    bullets: int
    chunk: Optional[int]
    word: Optional[int]  # index into the chunk's tokens that is being spoken


def align(narration: str, words: Sequence[Word]) -> list[Token]:
    """Display tokens in narration spelling ("record," not "record"), timed by the voice's word boundaries."""
    tokens: list[Token] = []
    cursor = 0
    lowered = narration.lower()
    for i, word in enumerate(words):
        at = lowered.find(word.text.lower(), cursor)
        if at < 0:
            tokens.append(Token(word.text, word.start, word.end))
            continue
        nxt = lowered.find(words[i + 1].text.lower(), at + len(word.text)) if i + 1 < len(words) else -1
        stop = nxt if nxt > at else len(narration)
        tokens.append(Token(narration[at:stop].strip() or word.text, word.start, word.end))
        cursor = at + len(word.text)
    return tokens


def chunk(tokens: Sequence[Token], max_words: int = 7, max_chars: int = 42) -> list[list[int]]:
    """Group token indices into caption lines.

    Breaks at sentence ends (and at commas after 4+ words); a clause that is still too long is split into
    the fewest, most even pieces, so no caption ends with a stranded one-word fragment.
    """
    clauses: list[list[int]] = [[]]
    for i, token in enumerate(tokens):
        clauses[-1].append(i)
        if token.text.endswith(_SENTENCE_END) or (token.text.endswith(",") and len(clauses[-1]) >= 4):
            clauses.append([])
    chunks: list[list[int]] = []
    for clause in filter(None, clauses):
        chars = sum(len(tokens[i].text) + 1 for i in clause)
        parts = max(-(-len(clause) // max_words), -(-chars // (max_chars + 1)), 1)
        size = -(-len(clause) // parts)
        chunks += [clause[k:k + size] for k in range(0, len(clause), size)]
    return chunks


def _keys(text: str) -> set[str]:
    return {w[:5] for w in _KEY_RE.findall(text.lower()) if len(w) >= 4 and w not in _STOP}


def bullet_times(bullets: Sequence[str], tokens: Sequence[Token], duration: float) -> list[float]:
    """When each bullet appears: the first time the narration says one of its key words, in order.

    Falls back to even spacing for a bullet the narration never mentions, and never reveals out of order.
    """
    times: list[float] = []
    cursor = 0
    earliest = 0.0
    n = len(bullets)
    for i, bullet in enumerate(bullets):
        keys = _keys(bullet)
        found = None
        for j in range(cursor, len(tokens)):
            if _keys(tokens[j].text) & keys:
                found = j
                break
        if found is not None:
            at = tokens[found].start
            cursor = found + 1
        else:
            at = duration * i / max(n, 1)
        at = max(at, earliest)
        times.append(round(at, 3))
        earliest = at
    return times


def states(tokens: Sequence[Token], chunks: Sequence[Sequence[int]], reveals: Sequence[float], duration: float,
           captions: bool = True, hold: float = 0.5) -> list[tuple[FrameState, float]]:
    """(state, seconds) for one scene, covering exactly [0, duration).

    The last caption stays up for ``hold`` seconds after the final word, then clears for the scene change.
    """
    owner = {i: c for c, members in enumerate(chunks) for i in members}
    events = {0.0, *[t for t in reveals if 0 <= t < duration]}
    clear_at = tokens[-1].end + hold if tokens else duration
    if captions:
        events.update(t.start for t in tokens if 0 <= t.start < duration)
        if clear_at < duration:
            events.add(clear_at)
    times = sorted(events)
    out: list[tuple[FrameState, float]] = []
    for k, t in enumerate(times):
        end = times[k + 1] if k + 1 < len(times) else duration
        if end <= t:
            continue
        shown = sum(1 for r in reveals if r <= t + 1e-6)
        spoken = [i for i, tok in enumerate(tokens) if tok.start <= t + 1e-6]
        if captions and spoken and t < clear_at - 1e-6:
            last = spoken[-1]
            c = owner[last]
            state = FrameState(shown, c, list(chunks[c]).index(last))
        else:
            state = FrameState(shown, None, None)
        if out and out[-1][0] == state:
            out[-1] = (state, out[-1][1] + end - t)
        else:
            out.append((state, end - t))
    return out


def _stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def srt(entries: Sequence[tuple[float, float, str]]) -> str:
    return "\n".join(f"{n}\n{_stamp(a)} --> {_stamp(b)}\n{text}\n" for n, (a, b, text) in enumerate(entries, 1))


def caption_entries(tokens: Sequence[Token], chunks: Sequence[Sequence[int]], offset: float,
                    scene_end: float) -> list[tuple[float, float, str]]:
    entries = []
    for c, members in enumerate(chunks):
        start = tokens[members[0]].start
        end = tokens[chunks[c + 1][0]].start if c + 1 < len(chunks) else min(scene_end, tokens[members[-1]].end + 0.6)
        entries.append((offset + start, offset + max(end, start + 0.3),
                        " ".join(tokens[i].text for i in members)))
    return entries
