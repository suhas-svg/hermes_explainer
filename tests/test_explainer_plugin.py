"""Behaviour tests for Explainer Studio.

Narration is injected (a fake voice that writes audio and word timings), so the tests run offline.
Tests that encode real video need ffmpeg and ffprobe on PATH and are skipped without them.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _load_plugin():
    name = "explainer_plugin_under_test"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_DIR / "__init__.py", submodule_search_locations=[str(PLUGIN_DIR)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PLUGIN = _load_plugin()
tools_mod = sys.modules["explainer_plugin_under_test.tools"]
tl = sys.modules["explainer_plugin_under_test.timeline"]
slides = sys.modules["explainer_plugin_under_test.slides"]
speech = sys.modules["explainer_plugin_under_test.speech"]
FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not on PATH")
NO_FFMPEG = {"ffmpeg_path": "no-such-ffmpeg-binary"}


class FakeCtx:
    def __init__(self, config=None):
        self.config = config or {}
        self.tools, self.commands, self.cli, self.skills, self.blueprints = {}, {}, {}, {}, {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, name, toolset, schema, handler, description=""):
        self.tools[name] = (toolset, schema, handler)

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands[name] = handler

    def register_cli_command(self, name, help, setup_fn, handler_fn):
        self.cli[name] = (setup_fn, handler_fn)

    def register_skill(self, name, path):
        self.skills[name] = Path(path)

    def register_automation_blueprint(self, key, **fields):
        self.blueprints[key] = fields


class FakeVoice:
    """Speaks 0.3 s per word: a real tone when ffmpeg exists, word timings like edge-tts (no punctuation)."""

    def __init__(self, *, fail_first=0, always_fail=False):
        self.calls, self.fail_first, self.always_fail = [], fail_first, always_fail

    async def __call__(self, text, voice, rate, out):
        self.calls.append((text, voice, rate))
        if self.always_fail or len(self.calls) <= self.fail_first:
            raise ConnectionError("voice service unavailable")
        words = re.findall(r"[\w'-]+", text)
        seconds = 0.3 * len(words)
        if FFMPEG:
            subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            f"sine=frequency=330:duration={seconds}", "-ar", "24000", "-ac", "1",
                            "-c:a", "libmp3lame", "-b:a", "48k", str(out)], check=True)
        else:
            out.write_bytes(b"\xff\xfb" + b"\x00" * 200)
        return [(w, i * 0.3, i * 0.3 + 0.25) for i, w in enumerate(words)]


FAST = {"gap": 0.0, "backoff": 0.01}


def _tools(tmp_path, voice=None, **config):
    return tools_mod.ExplainerTools(FakeCtx(config), speak=voice or FakeVoice(), data_root=lambda: tmp_path,
                                    pacing=FAST)


def _board(**overrides):
    board = {
        "title": "How Vaccines Work",
        "subtitle": "A short explainer",
        "scenes": [
            {"heading": "Your body keeps a memory",
             "narration": "Your immune system remembers invaders. Vaccines give it a safe preview.",
             "bullets": ["Immune memory", "A safe preview"]},
            {"heading": "Training day",
             "narration": "Antibodies learn the shape, and memory cells keep it for years.",
             "bullets": ["Antibodies learn", "Memory cells remember"], "note": "Source: CDC"},
        ],
    }
    board.update(overrides)
    return board


def _probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


# ---------- storyboard validation ----------

@pytest.mark.parametrize("change, message", [
    ({"title": ""}, "title is required"),
    ({"scenes": []}, "non-empty list"),
    ({"aspect": "4:3"}, "aspect must be one of"),
    ({"theme": "neon"}, "theme must be one of"),
    ({"voice": "Alice"}, "not an Edge neural voice"),
    ({"rate": "fast"}, "rate looks like"),
    ({"scenes": [{"heading": "", "narration": "x"}]}, "Scene 1 needs a heading"),
    ({"scenes": [{"heading": "h", "narration": ""}]}, "Scene 1 needs narration"),
    ({"scenes": [{"heading": "h", "narration": "x", "bullets": ["b"] * 6}]}, "at most 5"),
    ({"scenes": [{"heading": "h", "narration": "x", "bullets": ["b" * 120]}]}, "keep bullets under"),
    ({"scenes": [{"heading": "h", "narration": "x" * 1000}]}, "split it into two scenes"),
])
def test_bad_storyboards_return_fixable_errors_without_speaking(tmp_path, change, message):
    voice = FakeVoice()
    result = json.loads(_tools(tmp_path, voice).render(_board(**change)))
    assert message in result["error"]
    assert result["hint"]
    assert voice.calls == []
    assert not (tmp_path / "videos").exists()


def test_scene_and_character_limits_come_from_config(tmp_path):
    result = json.loads(_tools(tmp_path, max_scenes=1).render(_board()))
    assert "limit is 1" in result["error"]
    result = json.loads(_tools(tmp_path, max_chars=200).render(_board(scenes=[{"heading": "h", "narration": "x" * 300}])))
    assert "limit is 200" in result["error"]


def test_missing_ffmpeg_is_reported_before_any_narration(tmp_path):
    voice = FakeVoice()
    result = json.loads(_tools(tmp_path, voice, **NO_FFMPEG).render(_board()))
    assert "ffmpeg" in result["error"] and "ffmpeg_path" in result["hint"]
    assert voice.calls == []


def test_markdown_is_stripped_from_what_is_spoken_and_shown():
    board = _board(scenes=[{"heading": "## **Bold** idea", "narration": "Read [the paper](https://x.y) *now*."}])
    parsed = sys.modules["explainer_plugin_under_test.storyboard"].parse_storyboard(
        board, default_voice="en-US-AndrewMultilingualNeural", default_theme="midnight",
        themes=set(slides.THEMES), max_scenes=5, max_chars=1000)
    assert parsed.scenes[0].heading == "Bold idea"
    assert parsed.scenes[0].narration == "Read the paper now."


# ---------- timing ----------

def _tokens(text, step=0.3):
    words = re.findall(r"[\w'-]+", text)
    return tl.align(text, [speech.Word(w, i * step, i * step + 0.25) for i, w in enumerate(words)])


def test_captions_keep_the_narrations_punctuation():
    tokens = _tokens("Hello, world. It's 2024!")
    assert [t.text for t in tokens] == ["Hello,", "world.", "It's", "2024!"]


def test_caption_chunks_break_at_sentences_and_never_strand_a_word():
    tokens = _tokens("Your immune system remembers every invader it has beaten. Vaccines use that memory.")
    chunks = tl.chunk(tokens, max_words=8, max_chars=48)
    texts = [" ".join(tokens[i].text for i in c) for c in chunks]
    assert texts[-1] == "Vaccines use that memory."
    assert all(len(c) >= 3 for c in chunks)
    assert sorted(i for c in chunks for i in c) == list(range(len(tokens)))


def test_bullets_appear_when_the_narration_reaches_them_and_in_order():
    tokens = _tokens("First we mix the flour. Then we knead the dough. Finally the oven bakes it.")
    times = tl.bullet_times(["Mix the flour", "Knead dough", "Oven"], tokens, duration=5.0)
    starts = {t.text.strip(".,").lower(): t.start for t in tokens}
    assert times == pytest.approx([starts["flour"], starts["knead"], starts["oven"]])
    unmatched = tl.bullet_times(["Zebra", "Quokka"], tokens, duration=4.0)
    assert unmatched == sorted(unmatched) and unmatched[0] == 0.0


def test_frame_states_cover_the_scene_and_clear_the_last_caption():
    tokens = _tokens("One two three. Four five six.")
    chunks = tl.chunk(tokens)
    duration = tokens[-1].end + 2.0
    segments = tl.states(tokens, chunks, [0.0, 0.9], duration)
    assert sum(seconds for _, seconds in segments) == pytest.approx(duration)
    assert segments[-1][0].chunk is None and segments[-1][0].bullets == 2
    spoken = [state for state, _ in segments if state.chunk is not None]
    assert spoken[0].word == 0 and spoken[-1].chunk == len(chunks) - 1


def test_srt_is_well_formed_and_offset():
    tokens = _tokens("Alpha beta gamma. Delta epsilon zeta.")
    entries = tl.caption_entries(tokens, tl.chunk(tokens), offset=2.0, scene_end=4.0)
    text = tl.srt(entries)
    assert text.startswith("1\n00:00:02,000 --> 00:00:02,900\nAlpha beta gamma.\n")
    assert "2\n00:00:02,900 --> " in text


# ---------- narration ----------

def test_transient_voice_failures_are_retried(tmp_path):
    voice = FakeVoice(fail_first=2)
    out = speech.narrate(["Hello there."], tmp_path, voice="v", speak=voice, concurrency=1, **FAST)
    assert len(voice.calls) == 3 and out[0][1][0].text == "Hello"


def test_requests_are_spaced_so_the_voice_service_does_not_throttle(tmp_path):
    starts = []

    async def timed(text, voice, rate, out):
        starts.append(time.monotonic())
        out.write_bytes(b"x")
        return [("hi", 0.0, 0.2)]

    speech.narrate(["a", "b", "c"], tmp_path, voice="v", speak=timed, concurrency=3, gap=0.25, backoff=0.01)
    starts.sort()
    assert all(b - a >= 0.2 for a, b in zip(starts, starts[1:]))


@needs_ffmpeg
def test_a_scene_that_keeps_failing_aborts_cleanly(tmp_path):
    result = json.loads(_tools(tmp_path, FakeVoice(always_fail=True)).render(_board()))
    assert "Could not narrate scene" in result["error"]
    assert not any((tmp_path / "videos").iterdir())


def test_narration_works_inside_a_running_event_loop(tmp_path):
    async def inside():
        return speech.narrate(["Hi."], tmp_path, voice="v", speak=FakeVoice(), **FAST)

    assert asyncio.run(inside())[0][1][0].text == "Hi"


# ---------- rendering ----------

@needs_ffmpeg
@pytest.mark.parametrize("aspect, size", [("16:9", (1920, 1080)), ("9:16", (1080, 1920))])
def test_render_produces_video_captions_transcript_and_thumbnail(tmp_path, aspect, size):
    result = json.loads(_tools(tmp_path).render(_board(aspect=aspect)))
    assert result["success"], result
    info = _probe(result["video"])
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == size
    assert any(s["codec_type"] == "audio" for s in info["streams"])
    narration = sum(0.3 * len(re.findall(r"[\w'-]+", s["narration"])) for s in _board()["scenes"])
    seconds = float(info["format"]["duration"])
    assert seconds >= narration + 2.2 + 0.6 + 1.0  # title card, scene gap and tail around the speech
    assert [float(s["duration"]) for s in info["streams"]] == pytest.approx([seconds] * 2, abs=0.1)
    srt = Path(result["captions"]).read_text(encoding="utf-8")
    assert srt.startswith("1\n00:00:02,200 --> ")
    assert "Antibodies learn the shape," in srt
    assert "## Training day" in Path(result["transcript"]).read_text(encoding="utf-8")
    assert Path(result["thumbnail"]).stat().st_size > 1000
    assert result["media_tag"] == f"MEDIA:{result['video']}"
    assert [c["title"] for c in result["chapters"]] == ["Your body keeps a memory", "Training day"]
    assert not (Path(result["video"]).parent / "work").exists()


@needs_ffmpeg
def test_a_broken_image_becomes_a_warning_not_a_failure(tmp_path):
    board = _board()
    board["scenes"][0]["image"] = str(tmp_path / "missing.png")
    board["scenes"][1]["image"] = "http://example.com/a.png"
    result = json.loads(_tools(tmp_path).render(board))
    assert result["success"]
    assert len(result["warnings"]) == 2 and "only https" in result["warnings"][1]


def test_slides_render_without_any_system_font(monkeypatch):
    monkeypatch.setattr(slides, "_FONT_CANDIDATES", {"regular": [], "bold": []})
    fonts = slides.Fonts()
    assert "Pillow built-in" in fonts.describe()
    board = sys.modules["explainer_plugin_under_test.storyboard"].Storyboard(
        "A title that is long enough to wrap onto a second line", [], aspect="9:16")
    assert slides.Renderer(board, fonts).title_card(3).size == (1080, 1920)


def test_every_theme_draws_a_scene_with_bullets_and_captions():
    storyboard = sys.modules["explainer_plugin_under_test.storyboard"]
    scene = storyboard.Scene("Heading", "One two three four.", ("Alpha", "Beta"), note="Source: test")
    tokens = _tokens(scene.narration)
    for theme in slides.THEMES:
        renderer = slides.Renderer(storyboard.Storyboard("T", [scene], theme=theme), slides.Fonts())
        bases = renderer.scene_bases(scene, 1, 1)
        assert len(bases) == 3
        frame = renderer.frame(bases, tl.FrameState(2, 0, 1), tokens, tl.chunk(tokens), 0.5)
        assert frame.size == (1920, 1080)


# ---------- library, voices, commands ----------

@needs_ffmpeg
def test_videos_list_and_resend(tmp_path):
    tools = _tools(tmp_path)
    made = json.loads(tools.render(_board()))
    listed = json.loads(tools.list({}))
    assert listed["count"] == 1 and listed["videos"][0]["id"] == made["video_id"]
    again = json.loads(tools.list({"id": made["video_id"]}))
    assert again["media_tag"] == made["media_tag"]
    assert "No video" in json.loads(tools.list({"id": "nope"}))["error"]


def test_voices_filter_and_cache(tmp_path):
    calls = []

    async def fetch():
        calls.append(1)
        return [{"ShortName": "en-US-AvaNeural", "Locale": "en-US", "Gender": "Female", "VoiceTag": {}},
                {"ShortName": "es-ES-AlvaroNeural", "Locale": "es-ES", "Gender": "Male", "VoiceTag": {}}]

    tools = tools_mod.ExplainerTools(FakeCtx(), data_root=lambda: tmp_path, voice_fetch=fetch)
    english = json.loads(tools.voices({"locale": "en"}))
    assert [v["voice"] for v in english["voices"]] == ["en-US-AvaNeural"]
    json.loads(tools.voices({"locale": "es", "gender": "Male"}))
    assert len(calls) == 1


def test_voice_list_failure_is_reported(tmp_path):
    async def fetch():
        raise ConnectionError("offline")

    tools = tools_mod.ExplainerTools(FakeCtx(), data_root=lambda: tmp_path, voice_fetch=fetch)
    result = json.loads(tools.voices({}))
    assert "offline" in result["error"] and result["hint"]


def test_slash_and_cli(tmp_path, capsys):
    tools = _tools(tmp_path)
    assert "No videos yet" in tools.slash("")
    doctor = tools.slash("doctor")
    assert "Pillow:" in doctor and "ffmpeg:" in doctor and "fonts:" in doctor
    assert "Usage: /explainer" in tools.slash("bogus")
    parser = argparse.ArgumentParser()
    tools_mod._setup_cli(parser)
    assert tools.cli(parser.parse_args(["doctor"])) == 0
    assert "edge-tts:" in capsys.readouterr().out
    assert tools.cli(parser.parse_args(["play"])) == 1


# ---------- registration ----------

def test_register_wires_tools_command_cli_skill_and_blueprint():
    ctx = FakeCtx()
    PLUGIN.register(ctx)
    assert set(ctx.tools) == {"explainer_render", "explainer_voices", "explainer_videos"}
    assert all(toolset == "explainer" for toolset, _, _ in ctx.tools.values())
    assert "explainer" in ctx.commands and "explainer" in ctx.cli
    assert ctx.skills["explainer-video"].is_file()
    blueprint = ctx.blueprints["weekly-recap-video"]
    assert blueprint["skills"] == ("explainer:explainer-video",)
    manifest = (PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8")
    for name in ctx.tools:
        assert f"- {name}" in manifest


def test_blueprint_is_accepted_by_hermes_when_available():
    blueprint_plugins = pytest.importorskip("cron.blueprint_plugins")
    catalog = pytest.importorskip("cron.blueprint_catalog")
    ctx = FakeCtx()
    PLUGIN.register(ctx)
    built = blueprint_plugins.build_plugin_blueprint("explainer", "weekly-recap-video",
                                                     **ctx.blueprints["weekly-recap-video"])
    assert built.key == "explainer:weekly-recap-video"
    assert hasattr(catalog, "list_blueprints")
