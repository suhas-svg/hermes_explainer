"""Tool, slash-command and CLI handlers for Explainer Studio."""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import sys
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from . import library
from .render import RenderError, find_ffmpeg, render
from .slides import THEMES, Fonts, SlideError
from .speech import Speak, SpeechError, list_voices, narrate
from .storyboard import DEFAULT_VOICE, StoryboardError, parse_storyboard

logger = logging.getLogger(__name__)
PLUGIN = "explainer"
_DELIVER = "Include the media_tag line exactly, on its own line, in your reply so the video is attached."


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"success": True, **payload}, ensure_ascii=False)


def _error(message: str, hint: str = "") -> str:
    return json.dumps({"error": message, **({"hint": hint} if hint else {})}, ensure_ascii=False)


def _guard(fn: Callable[..., str]) -> Callable[..., str]:
    @wraps(fn)
    def wrapper(self: "ExplainerTools", args: dict[str, Any], **_kwargs: Any) -> str:
        try:
            return fn(self, args or {})
        except StoryboardError as exc:
            return _error(str(exc), "Fix the storyboard and call the tool again.")
        except SpeechError as exc:
            return _error(str(exc), exc.hint)
        except (RenderError, SlideError) as exc:
            return _error(str(exc), "Run /explainer doctor to check ffmpeg, Pillow and fonts.")
        except Exception as exc:  # tool handlers must never raise
            logger.exception("explainer tool %s failed", fn.__name__)
            return _error(f"Unexpected Explainer Studio error: {exc}")

    return wrapper


def _data_root() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir  # noqa: PLC0415 - Hermes runtime only
    except ImportError:
        return Path.home() / ".hermes" / "plugin-data" / PLUGIN
    return Path(plugin_data_dir(PLUGIN))


def _media_tag(path: str) -> str:
    return f"MEDIA:{path}"


class ExplainerTools:
    def __init__(self, ctx: Any, *, speak: Optional[Speak] = None, data_root: Optional[Callable[[], Path]] = None,
                 voice_fetch: Any = None, pacing: Optional[dict[str, float]] = None) -> None:
        self.ctx = ctx
        self._speak = speak
        self._pacing = pacing or {}
        self._root = data_root or _data_root
        self._voice_fetch = voice_fetch

    def _get(self, key: str, default: Any) -> Any:
        try:
            value = self.ctx.get_config(key, default)
        except Exception:
            return default
        return default if value in (None, "") else value

    def _int(self, key: str, default: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(self._get(key, default))))
        except (TypeError, ValueError):
            return default

    def _ffmpeg(self) -> Optional[str]:
        return find_ffmpeg(str(self._get("ffmpeg_path", "")))

    def _fonts(self) -> Fonts:
        return Fonts(str(self._get("font_path", "")), str(self._get("font_bold_path", "")))

    def _image_roots(self) -> list[Path]:
        """Folders local scene images may come from: the working directory, the plugin's data folder, image_dirs."""
        extra = self._get("image_dirs", [])
        extra = [extra] if isinstance(extra, str) else list(extra or [])
        return [Path.cwd(), self._root(), *(Path(str(d)) for d in extra if str(d).strip())]

    # ---------- tools ----------

    @_guard
    def render(self, args: dict[str, Any]) -> str:
        args = dict(args)
        args.setdefault("aspect", str(self._get("aspect", "16:9")))
        board = parse_storyboard(args, default_voice=str(self._get("voice", DEFAULT_VOICE)),
                                 default_theme=str(self._get("theme", "midnight")), themes=set(THEMES),
                                 max_scenes=self._int("max_scenes", 12, 1, 40),
                                 max_chars=self._int("max_chars", 6000, 200, 40000))
        ffmpeg = self._ffmpeg()
        if not ffmpeg:
            return _error("ffmpeg was not found, and it is needed to encode the video.",
                          "Install ffmpeg (winget install ffmpeg / brew install ffmpeg / apt install ffmpeg) "
                          "or set plugins.entries.explainer.settings.ffmpeg_path.")
        started = time.monotonic()
        folder = library.new_video_dir(self._root(), board.title)
        try:
            voiced = narrate([s.narration for s in board.scenes], folder / "work" / "voice", voice=board.voice,
                             rate=board.rate, speak=self._speak, concurrency=self._int("concurrency", 3, 1, 8),
                             **self._pacing)
            video = render(board, voiced, folder, ffmpeg=ffmpeg, fonts=self._fonts(), image_roots=self._image_roots())
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        meta = library.save(board, video, folder)
        payload = {
            "video_id": folder.name,
            "title": board.title,
            "duration": meta["duration_text"],
            "aspect": board.aspect,
            "scenes": len(board.scenes),
            "chapters": meta["chapters"],
            "video": meta["video"],
            "captions": meta["captions"],
            "transcript": meta["transcript"],
            "thumbnail": meta["thumbnail"],
            "render_seconds": round(time.monotonic() - started, 1),
            "media_tag": _media_tag(meta["video"]),
            "deliver": _DELIVER,
        }
        if video.warnings:
            payload["warnings"] = video.warnings
        return _ok(payload)

    @_guard
    def voices(self, args: dict[str, Any]) -> str:
        locale = str(args.get("locale") or "en").strip().lower()
        gender = str(args.get("gender") or "").strip().lower()
        rows = []
        for v in list_voices(self._root() / "voices.json", fetch=self._voice_fetch):
            if not str(v.get("Locale", "")).lower().startswith(locale):
                continue
            if gender and str(v.get("Gender", "")).lower() != gender:
                continue
            tags = v.get("VoiceTag") or {}
            rows.append({"voice": v.get("ShortName"), "locale": v.get("Locale"), "gender": v.get("Gender"),
                         "personality": ", ".join(tags.get("VoicePersonalities") or [])})
        return _ok({"locale": locale, "count": len(rows), "voices": rows[:60],
                    "default": self._get("voice", DEFAULT_VOICE)})

    @_guard
    def list(self, args: dict[str, Any]) -> str:
        wanted = str(args.get("id") or "").strip()
        try:
            limit = max(1, min(50, int(args.get("limit", 10))))
        except (TypeError, ValueError):
            limit = 10
        rows = library.list_videos(self._root(), limit=500 if wanted else limit)
        if wanted:
            match = next((r for r in rows if r["id"] == wanted), None)
            if not match:
                return _error(f"No video with id {wanted!r}.", "Call explainer_videos without id to list them.")
            return _ok({"video": match, "media_tag": _media_tag(match["video"]), "deliver": _DELIVER})
        return _ok({"count": len(rows), "videos": rows, "folder": str(self._root() / "videos")})

    # ---------- /explainer ----------

    def slash(self, raw_args: str, **_kwargs: Any) -> str:
        try:
            parts = shlex.split(raw_args or "")
        except ValueError as exc:
            return f"Could not parse /explainer arguments: {exc}"
        command = parts[0].lower() if parts else "list"
        try:
            if command == "list":
                return self._text_list()
            if command == "voices":
                return self._text_voices(parts[1] if len(parts) > 1 else "en")
            if command == "doctor":
                return self._text_doctor()
        except (SpeechError, RenderError, SlideError) as exc:
            return f"Explainer Studio error: {exc}"
        return ("Usage: /explainer [list|voices [locale]|doctor]\n"
                "Ask Hermes to turn a link, PDF, notes or a topic into a narrated explainer video.")

    def _text_list(self) -> str:
        rows = library.list_videos(self._root(), limit=10)
        if not rows:
            return "No videos yet. Try: \"Make a 60-second explainer video about <a link or topic>.\""
        lines = ["Recent explainer videos:"]
        lines += [f"  {r['created']}  {r['duration_text']}  {r['aspect']}  {r['title']}\n    {r['video']}" for r in rows]
        return "\n".join(lines)

    def _text_voices(self, locale: str) -> str:
        data = json.loads(self.voices({"locale": locale}))
        if data.get("error"):
            return f"Explainer Studio error: {data['error']}"
        return "\n".join([f"{data['count']} voices for {locale}:"] +
                         [f"  {v['voice']}  ({v['gender']}{', ' + v['personality'] if v['personality'] else ''})"
                          for v in data["voices"][:25]])

    def _text_doctor(self) -> str:
        checks = []
        for module, label in (("edge_tts", "edge-tts"), ("PIL", "Pillow")):
            try:
                __import__(module)
                checks.append(f"{label + ':':10}installed")
            except ImportError:
                checks.append(f"{label + ':':10}MISSING (run `hermes plugins install explainer --install-deps`)")
        ffmpeg = self._ffmpeg()
        checks.append(f"{'ffmpeg:':10}{ffmpeg or 'NOT FOUND (needed to encode video)'}")
        checks.append(f"{'fonts:':10}{self._fonts().describe()}")
        checks.append(f"{'videos:':10}{self._root() / 'videos'}")
        return "\n".join(checks)

    # ---------- hermes explainer ----------

    def cli(self, args: Any) -> int:
        command = getattr(args, "explainer_command", None) or "list"
        if command == "play":
            rows = library.list_videos(self._root(), limit=50)
            ref = getattr(args, "video", None)
            match = rows[0] if rows and not ref else next((r for r in rows if ref and ref in r["id"]), None)
            if not match:
                print("No matching video. Run `hermes explainer list`.")
                return 1
            print(f"Playing {match['title']} ({match['duration_text']})")
            _open(match["video"])
            return 0
        if command == "voices":
            print(self._text_voices(getattr(args, "locale", "en") or "en"))
            return 0
        text = {"list": self._text_list, "doctor": self._text_doctor}.get(command)
        if text is None:
            print("Usage: hermes explainer <list|play [ID]|voices [LOCALE]|doctor>")
            return 2
        print(text())
        return 0


def _open(path: str) -> None:
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 - opens the user's own video in their default player
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def _setup_cli(subparser: Any) -> None:
    subs = subparser.add_subparsers(dest="explainer_command")
    subs.add_parser("list", help="List recent explainer videos")
    play = subs.add_parser("play", help="Open a video in your default player")
    play.add_argument("video", nargs="?", help="Video id (or part of it); newest if omitted")
    voices = subs.add_parser("voices", help="List narrator voices for a locale")
    voices.add_argument("locale", nargs="?", default="en")
    subs.add_parser("doctor", help="Check edge-tts, Pillow, ffmpeg and fonts")
