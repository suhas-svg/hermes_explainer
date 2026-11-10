"""Draw slides with Pillow: themed background, heading, bullets, image, karaoke captions, progress bar."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .storyboard import Scene, Storyboard
from .timeline import FrameState, Token

class SlideError(RuntimeError):
    pass


@dataclass(frozen=True)
class Theme:
    top: str
    bottom: str
    text: str
    muted: str
    accent: str
    panel: tuple[int, int, int, int]


THEMES = {
    "midnight": Theme("#0f1420", "#1c2645", "#f5f7fb", "#9aa6b8", "#ffbf00", (8, 10, 18, 200)),
    "paper": Theme("#faf6ee", "#ece3d1", "#1d1d1f", "#5d5a54", "#c8462a", (255, 255, 255, 225)),
    "ocean": Theme("#05253a", "#0b5270", "#eaf6ff", "#9cc3d5", "#47d7ac", (2, 20, 32, 200)),
    "sunset": Theme("#2a1230", "#6a2340", "#fff4ec", "#e3b9b0", "#ff9f43", (24, 8, 22, 200)),
    "forest": Theme("#0e2318", "#1f402d", "#eef7ef", "#a9c4ae", "#9be15d", (6, 18, 11, 200)),
}

_FONT_CANDIDATES = {
    "regular": [
        "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "bold": [
        "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
}


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps  # noqa: PLC0415 - optional until first use
    except ImportError as exc:
        raise SlideError("Pillow is not installed; run `hermes plugins install explainer --install-deps`.") from exc
    return Image, ImageDraw, ImageFont, ImageOps


class Fonts:
    """Resolves system fonts once, with a configurable override and Pillow's built-in scalable fallback."""

    def __init__(self, regular: str = "", bold: str = "") -> None:
        self.paths = {"regular": self._find("regular", regular), "bold": self._find("bold", bold)}
        self._cache: dict[tuple[str, int], object] = {}

    @staticmethod
    def _find(kind: str, override: str) -> Optional[str]:
        for path in ([override] if override else []) + _FONT_CANDIDATES[kind]:
            if path and Path(path).is_file():
                return path
        return None

    def get(self, kind: str, size: int):
        key = (kind, size)
        if key not in self._cache:
            _, _, ImageFont, _ = _pil()
            path = self.paths[kind] or self.paths["regular"]
            self._cache[key] = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        return self._cache[key]

    def describe(self) -> str:
        return ", ".join(f"{k}: {v or 'Pillow built-in'}" for k, v in self.paths.items())


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def wrap(text: str, font, width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and font.getlength(trial) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


class Renderer:
    def __init__(self, board: Storyboard, fonts: Fonts) -> None:
        self.board = board
        self.theme = THEMES[board.theme]
        self.fonts = fonts
        self.w, self.h = board.size
        self.portrait = self.h > self.w
        self.s = self.w / 1920 if not self.portrait else self.w / 1080  # layout scale
        self._background = None

    # ---------- shared pieces ----------

    def background(self):
        if self._background is None:
            Image, _, _, _ = _pil()
            top, bottom = _rgb(self.theme.top), _rgb(self.theme.bottom)
            column = Image.new("RGB", (1, self.h))
            for y in range(self.h):
                t = y / max(self.h - 1, 1)
                column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
            self._background = column.resize((self.w, self.h))
        return self._background.copy()

    def _fit(self, text: str, kind: str, sizes: Sequence[int], width: int, max_lines: int):
        """Fewest lines first (shrinking a little before wrapping), so a heading never strands one word."""
        for allowed in range(1, max_lines + 1):
            for size in sizes if allowed == max_lines else sizes[:3]:
                font = self.fonts.get(kind, size)
                lines = wrap(text, font, width)
                if len(lines) <= allowed:
                    return font, lines
        font = self.fonts.get(kind, sizes[-1])
        return font, wrap(text, font, width)[:max_lines]

    def _paste_image(self, canvas, image, box: tuple[int, int, int, int]) -> None:
        Image, ImageDraw, _, _ = _pil()
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        scale = min(bw / image.width, bh / image.height)
        fitted = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)
        mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, *fitted.size), radius=int(24 * self.s), fill=255)
        canvas.paste(fitted, (x0 + (bw - fitted.width) // 2, y0 + (bh - fitted.height) // 2), mask)

    # ---------- title card ----------

    def title_card(self, total_scenes: int):
        _, ImageDraw, _, _ = _pil()
        canvas = self.background()
        draw = ImageDraw.Draw(canvas)
        width = int(self.w * (0.84 if self.portrait else 0.78))
        sizes = [int(v * self.s) for v in (120, 104, 92, 80, 68)]
        font, lines = self._fit(self.board.title, "bold", sizes, width, 4)
        line_h = int(font.size * 1.18)
        sub_font = self.fonts.get("regular", int(46 * self.s))
        sub_lines = wrap(self.board.subtitle, sub_font, width) if self.board.subtitle else []
        block = len(lines) * line_h + (int(40 * self.s) + len(sub_lines) * int(sub_font.size * 1.3) if sub_lines else 0)
        y = (self.h - block) // 2
        bar_w = int(140 * self.s)
        draw.rounded_rectangle(((self.w - bar_w) // 2, y - int(56 * self.s), (self.w + bar_w) // 2,
                                y - int(44 * self.s)), radius=6, fill=self.theme.accent)
        for line in lines:
            draw.text(((self.w - font.getlength(line)) / 2, y), line, font=font, fill=self.theme.text)
            y += line_h
        if sub_lines:
            y += int(40 * self.s)
            for line in sub_lines:
                draw.text(((self.w - sub_font.getlength(line)) / 2, y), line, font=sub_font, fill=self.theme.muted)
                y += int(sub_font.size * 1.3)
        foot = self.fonts.get("regular", int(30 * self.s))
        label = f"{total_scenes} parts"
        draw.text(((self.w - foot.getlength(label)) / 2, self.h - int(110 * self.s)), label, font=foot,
                  fill=self.theme.muted)
        return canvas

    # ---------- scene slides ----------

    def scene_bases(self, scene: Scene, number: int, total: int, image=None) -> list:
        """One base slide per number of revealed bullets (0..n); captions are drawn on top per frame."""
        _, ImageDraw, _, _ = _pil()
        base = self.background()
        s, m = self.s, int(120 * self.s)
        if image is None and not self.portrait:
            self._watermark(base, f"{number:02d}")
        draw = ImageDraw.Draw(base)
        counter = self.fonts.get("bold", int(30 * s))
        draw.text((m, int(70 * s)), f"{number:02d} / {total:02d}", font=counter, fill=self.theme.accent)
        top = int(150 * s)
        bottom = self.h - int((660 if self.portrait else 300) * s) if self.board.captions else self.h - int(130 * s)
        text_w = self.w - 2 * m if self.portrait else int(self.w * (0.46 if image is not None else 0.72))
        head_font, head_lines = self._fit(scene.heading, "bold", [int(v * s) for v in (88, 78, 68, 60, 52)], text_w, 3)
        head_h = len(head_lines) * int(head_font.size * 1.15) + int(70 * s)
        img_h = int(600 * s) if self.portrait and image is not None else 0
        extra = img_h + int(50 * s) if img_h else 0
        layout = self._bullet_layout(scene.bullets, text_w, bottom - top - head_h - extra)
        block = head_h + extra + self._bullets_height(layout)
        y = top + max(0, int((bottom - top - block) * 0.42))  # optically centred, a little high
        for line in head_lines:
            draw.text((m, y), line, font=head_font, fill=self.theme.text)
            y += int(head_font.size * 1.15)
        draw.rounded_rectangle((m, y + int(22 * s), m + int(96 * s), y + int(30 * s)), radius=4, fill=self.theme.accent)
        y += int(70 * s)
        if image is not None:
            if self.portrait:
                self._paste_image(base, image, (m, y, self.w - m, y + img_h))
                y += extra
            else:
                self._paste_image(base, image, (m + text_w + int(70 * s), top, self.w - m, bottom))
        if scene.note:
            note_font = self.fonts.get("regular", int(28 * s))
            note_y = self.h - int((330 if self.portrait else 70) * s)
            draw.text((m, note_y), scene.note, font=note_font, fill=self.theme.muted)
        bases = [base.copy()]
        for k in range(1, len(scene.bullets) + 1):
            frame = bases[-1].copy()
            self._draw_bullet(ImageDraw.Draw(frame), layout, k - 1, m, y)
            bases.append(frame)
        return bases

    def _watermark(self, canvas, text: str) -> None:
        """A large, faint scene number on the right of text-only slides."""
        Image, ImageDraw, _, _ = _pil()
        font = self.fonts.get("bold", int(520 * self.s))
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        r, g, b = _rgb(self.theme.accent)
        x = self.w - int(90 * self.s) - font.getlength(text)
        ImageDraw.Draw(layer).text((x, int(150 * self.s)), text, font=font, fill=(r, g, b, 13))
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB"))

    def _bullets_height(self, layout) -> int:
        font, gap, blocks = layout
        return sum(len(lines) * int(font.size * 1.28) + gap for lines in blocks)

    def _bullet_layout(self, bullets: Sequence[str], width: int, height: int):
        for size in [int(v * self.s) for v in (58, 52, 46, 42, 38, 34, 30)]:
            font = self.fonts.get("regular", size)
            gap = int(size * 0.7)
            blocks = [wrap(b, font, width - int(60 * self.s)) for b in bullets]
            if self._bullets_height((font, gap, blocks)) <= height or size <= int(30 * self.s):
                return font, gap, blocks
        raise AssertionError("unreachable")

    def _draw_bullet(self, draw, layout, index: int, x: int, y0: int) -> None:
        font, gap, blocks = layout
        line_h = int(font.size * 1.28)
        y = y0 + sum(len(lines) * line_h + gap for lines in blocks[:index])
        r = int(9 * self.s)
        cy = y + line_h // 2
        draw.ellipse((x + 4, cy - r, x + 4 + 2 * r, cy + r), fill=self.theme.accent)
        for line in blocks[index]:
            draw.text((x + int(60 * self.s), y), line, font=font, fill=self.theme.text)
            y += line_h

    # ---------- per-frame overlay ----------

    def frame(self, bases: list, state: FrameState, tokens: Sequence[Token], chunks: Sequence[Sequence[int]],
              progress: float):
        Image, ImageDraw, _, _ = _pil()
        canvas = bases[min(state.bullets, len(bases) - 1)].copy()
        if state.chunk is not None:
            overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            self._caption(ImageDraw.Draw(overlay), [tokens[i].text for i in chunks[state.chunk]], state.word)
            canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(canvas)
        bar = max(4, int(8 * self.s))
        draw.rectangle((0, self.h - bar, int(self.w * max(0.0, min(1.0, progress))), self.h), fill=self.theme.accent)
        return canvas

    def _caption(self, draw, words: Sequence[str], active: Optional[int]) -> None:
        s = self.s
        font = self.fonts.get("bold", int((58 if self.portrait else 50) * s))
        width = int(self.w * (0.86 if self.portrait else 0.74))
        space = font.getlength(" ")
        lines = _break(words, font, width)
        if len(lines) > 1:  # rebalance so the last line is not a stranded word
            total = sum(font.getlength(w) for w in words) + space * (len(words) - 1)
            target = total / len(lines)
            for trial in range(int(target), width + 1, max(1, int(8 * s))):
                balanced = _break(words, font, trial)
                if len(balanced) == len(lines):
                    lines = balanced
                    break
        line_h = int(font.size * 1.3)
        pad_x, pad_y = int(36 * s), int(22 * s)
        widths = [sum(font.getlength(words[i]) for i in ln) + space * (len(ln) - 1) for ln in lines]
        box_w = max(widths) + 2 * pad_x
        box_h = len(lines) * line_h + 2 * pad_y
        center_y = self.h - int((520 if self.portrait else 175) * s)
        x0, y0 = (self.w - box_w) / 2, center_y - box_h / 2
        draw.rounded_rectangle((x0, y0, x0 + box_w, y0 + box_h), radius=int(20 * s), fill=self.theme.panel)
        text, accent = self.theme.text, self.theme.accent
        for n, ln in enumerate(lines):
            x = (self.w - widths[n]) / 2
            y = y0 + pad_y + n * line_h
            for i in ln:
                draw.text((x, y), words[i], font=font, fill=accent if i == active else text)
                x += font.getlength(words[i]) + space


def _break(words: Sequence[str], font, width: float) -> list[list[int]]:
    """Greedy line breaks of word indices within ``width`` pixels."""
    space = font.getlength(" ")
    lines: list[list[int]] = [[]]
    used = 0.0
    for i, word in enumerate(words):
        wl = font.getlength(word)
        if lines[-1] and used + space + wl > width:
            lines.append([])
            used = 0.0
        used += (space if lines[-1] else 0) + wl
        lines[-1].append(i)
    return lines
