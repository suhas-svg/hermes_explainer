"""Validate and normalise the storyboard the model hands to explainer_render."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
_VOICE_RE = re.compile(r"^[a-z]{2,3}-[A-Za-z]{2,4}(?:-[A-Za-z]+)?-[A-Za-z0-9]+Neural$")
_RATE_RE = re.compile(r"^[+-]\d{1,2}%$")
MAX_BULLETS = 5
MAX_BULLET_CHARS = 90
MAX_HEADING_CHARS = 80
MAX_NARRATION_CHARS = 900


class StoryboardError(ValueError):
    """The storyboard cannot be rendered as given; the message says how to fix it."""


@dataclass(frozen=True)
class Scene:
    heading: str
    narration: str
    bullets: tuple[str, ...] = ()
    image: str = ""
    note: str = ""


@dataclass
class Storyboard:
    title: str
    scenes: list[Scene]
    subtitle: str = ""
    aspect: str = "16:9"
    theme: str = "midnight"
    voice: str = DEFAULT_VOICE
    rate: str = "+0%"
    captions: bool = True
    tags: list[str] = field(default_factory=list)

    @property
    def size(self) -> tuple[int, int]:
        return ASPECTS[self.aspect]

    @property
    def narration_chars(self) -> int:
        return sum(len(s.narration) for s in self.scenes)


def _clean(text: Any) -> str:
    text = str(text or "")
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)  # markdown links read as their label
    text = re.sub(r"[*_`#>]+", "", text)
    return " ".join(text.split())


def _scene(index: int, raw: Any) -> Scene:
    where = f"Scene {index}"
    if not isinstance(raw, dict):
        raise StoryboardError(f"{where} must be an object with heading and narration.")
    heading = _clean(raw.get("heading"))
    narration = _clean(raw.get("narration"))
    if not heading:
        raise StoryboardError(f"{where} needs a heading.")
    if len(heading) > MAX_HEADING_CHARS:
        raise StoryboardError(f"{where} heading is {len(heading)} characters; keep it under {MAX_HEADING_CHARS}.")
    if not narration:
        raise StoryboardError(f"{where} needs narration (what the voice says while it is on screen).")
    if len(narration) > MAX_NARRATION_CHARS:
        raise StoryboardError(f"{where} narration is {len(narration)} characters; split it into two scenes "
                              f"(limit {MAX_NARRATION_CHARS}).")
    bullets = raw.get("bullets") or []
    if not isinstance(bullets, list):
        raise StoryboardError(f"{where} bullets must be a list of short strings.")
    bullets = [_clean(b) for b in bullets if _clean(b)]
    if len(bullets) > MAX_BULLETS:
        raise StoryboardError(f"{where} has {len(bullets)} bullets; use at most {MAX_BULLETS}.")
    for b in bullets:
        if len(b) > MAX_BULLET_CHARS:
            raise StoryboardError(f"{where} bullet {b[:30]!r}... is {len(b)} characters; keep bullets under "
                                  f"{MAX_BULLET_CHARS} (the narration carries the detail).")
    return Scene(heading, narration, tuple(bullets), str(raw.get("image") or "").strip(), _clean(raw.get("note")))


def parse_storyboard(args: dict[str, Any], *, default_voice: str, default_theme: str, themes: set[str],
                     max_scenes: int, max_chars: int) -> Storyboard:
    title = _clean(args.get("title"))
    if not title:
        raise StoryboardError("title is required.")
    aspect = str(args.get("aspect") or "16:9").strip()
    if aspect not in ASPECTS:
        raise StoryboardError(f"aspect must be one of {', '.join(ASPECTS)} (9:16 for Shorts/Reels/TikTok).")
    theme = str(args.get("theme") or default_theme).strip().lower()
    if theme not in themes:
        raise StoryboardError(f"theme must be one of {', '.join(sorted(themes))}.")
    voice = str(args.get("voice") or default_voice).strip()
    if not _VOICE_RE.match(voice):
        raise StoryboardError(f"{voice!r} is not an Edge neural voice name (e.g. en-US-AvaMultilingualNeural).")
    rate = str(args.get("rate") or "+0%").strip()
    if not _RATE_RE.match(rate):
        raise StoryboardError("rate looks like '+10%' or '-5%'.")
    raw_scenes = args.get("scenes")
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise StoryboardError("scenes must be a non-empty list of {heading, narration, bullets}.")
    if len(raw_scenes) > max_scenes:
        raise StoryboardError(f"{len(raw_scenes)} scenes is too many; the limit is {max_scenes}. Merge some.")
    scenes = [_scene(i, raw) for i, raw in enumerate(raw_scenes, start=1)]
    board = Storyboard(title, scenes, _clean(args.get("subtitle")), aspect, theme, voice, rate,
                       args.get("captions") is not False)
    if board.narration_chars > max_chars:
        raise StoryboardError(f"The narration is {board.narration_chars} characters; the limit is {max_chars}. "
                              "Tighten it.")
    return board
