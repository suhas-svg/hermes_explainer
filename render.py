"""Assemble narrated scenes into an MP4: frames from slides.py, timing from timeline.py, ffmpeg for the rest."""

from __future__ import annotations

import shutil
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from . import timeline as tl
from .slides import Fonts, Renderer, SlideError, load_image
from .speech import Word
from .storyboard import Storyboard

RATE = 24000
FPS = 30
TITLE_SECONDS = 2.2
GAP_SECONDS = 0.6
TAIL_SECONDS = 1.0
MAX_SEGMENT = 0.5  # split long still segments so the progress bar keeps moving


class RenderError(RuntimeError):
    pass


@dataclass
class SceneTiming:
    heading: str
    start: float
    end: float
    narration: str


@dataclass
class Video:
    path: Path
    duration: float
    scenes: list[SceneTiming]
    srt: str
    thumbnail: Path
    warnings: list[str] = field(default_factory=list)


def find_ffmpeg(configured: str = "") -> Optional[str]:
    if configured:
        return configured if Path(configured).is_file() else shutil.which(configured)
    return shutil.which("ffmpeg")


def _run(argv: list[str], timeout: int = 1800) -> None:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RenderError(f"ffmpeg failed: {proc.stderr.strip()[-500:]}")


def _to_wav(ffmpeg: str, src: Path, dst: Path) -> float:
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-ac", "1", "-ar", str(RATE), "-sample_fmt", "s16", str(dst)])
    with wave.open(str(dst), "rb") as w:
        return w.getnframes() / RATE


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(round(RATE * seconds))


def _join_audio(wavs: Sequence[Path], gaps: Sequence[float], lead: float, out: Path) -> None:
    with wave.open(str(out), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(RATE)
        dst.writeframes(_silence(lead))
        for wav, gap in zip(wavs, gaps):
            with wave.open(str(wav), "rb") as src:
                dst.writeframes(src.readframes(src.getnframes()))
            dst.writeframes(_silence(gap))


def _split(segments: list[tuple[tl.FrameState, float]]) -> list[tuple[tl.FrameState, float]]:
    out = []
    for state, seconds in segments:
        while seconds > MAX_SEGMENT * 1.5:
            out.append((state, MAX_SEGMENT))
            seconds -= MAX_SEGMENT
        out.append((state, seconds))
    return out


def _ffconcat(frames: Sequence[tuple[Path, float]], path: Path) -> None:
    rows = ["ffconcat version 1.0"]
    for frame, seconds in frames:
        rows += [f"file '{frame.name}'", f"duration {seconds:.4f}"]
    rows.append(f"file '{frames[-1][0].name}'")  # the concat demuxer ignores the last entry's duration
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def render(board: Storyboard, narration: Sequence[tuple[Path, list[Word]]], out_dir: Path, *, ffmpeg: str,
           fonts: Fonts, base_dir: Optional[Path] = None, workers: int = 4) -> Video:
    work = out_dir / "work"
    frames_dir = work / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    renderer = Renderer(board, fonts)
    warnings: list[str] = []

    wavs = [work / f"scene_{i:02d}.wav" for i in range(len(narration))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        lengths = list(pool.map(lambda p: _to_wav(ffmpeg, *p), [(mp3, wav) for (mp3, _), wav in zip(narration, wavs)]))
    gaps = [GAP_SECONDS] * (len(wavs) - 1) + [TAIL_SECONDS]
    total = TITLE_SECONDS + sum(lengths) + sum(gaps)

    jobs: list[tuple[Path, float, object]] = []  # (frame file, seconds, draw thunk)
    title = renderer.title_card(len(board.scenes))
    thumb = out_dir / "thumbnail.png"
    title.save(thumb)
    title_png = frames_dir / "f00000.png"
    jobs.append((title_png, TITLE_SECONDS, lambda: title))

    timings: list[SceneTiming] = []
    captions: list[tuple[float, float, str]] = []
    cursor = TITLE_SECONDS
    for n, (scene, (_mp3, words), length, gap) in enumerate(zip(board.scenes, narration, lengths, gaps), start=1):
        image = None
        if scene.image:
            try:
                image = load_image(scene.image, base_dir)
            except Exception as exc:  # a broken image must not sink the video
                warnings.append(f"Scene {n}: image skipped ({exc}).")
        bases = renderer.scene_bases(scene, n, len(board.scenes), image)
        tokens = tl.align(scene.narration, words)
        chunks = tl.chunk(tokens, max_words=6 if board.aspect == "9:16" else 8,
                          max_chars=30 if board.aspect == "9:16" else 48)
        span = length + gap
        reveals = tl.bullet_times(scene.bullets, tokens, length)
        local = 0.0
        for state, seconds in _split(tl.states(tokens, chunks, reveals, span, captions=board.captions)):
            progress = (cursor + local) / total
            path = frames_dir / f"f{len(jobs):05d}.png"
            jobs.append((path, seconds, lambda b=bases, s=state, p=progress, t=tokens, c=chunks:
                         renderer.frame(b, s, t, c, p)))
            local += seconds
        if tokens:
            captions += tl.caption_entries(tokens, chunks, cursor, span)
        timings.append(SceneTiming(scene.heading, round(cursor, 2), round(cursor + span, 2), scene.narration))
        cursor += span

    def draw(job: tuple[Path, float, object]) -> None:
        path, _seconds, thunk = job
        thunk().save(path, compress_level=1)  # type: ignore[operator]

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(draw, jobs))
    except SlideError:
        raise
    except Exception as exc:
        raise RenderError(f"Could not draw the slides: {exc}") from exc

    concat = frames_dir / "frames.ffconcat"
    _ffconcat([(p, s) for p, s, _ in jobs], concat)
    audio = work / "narration.wav"
    _join_audio(wavs, gaps, TITLE_SECONDS, audio)
    out = out_dir / "explainer.mp4"
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-f", "concat", "-safe", "0", "-i", str(concat), "-i", str(audio),
          "-map", "0:v", "-map", "1:a",
          "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-tune", "stillimage",
          "-af", "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000", "-c:a", "aac", "-b:a", "160k",
          "-metadata", f"title={board.title}", "-metadata", "comment=Made with Hermes Explainer Studio",
          "-t", f"{total:.3f}",  # the fps filter pads past the last still at EOF; keep picture and sound equal
          "-movflags", "+faststart", str(out)])
    shutil.rmtree(work, ignore_errors=True)
    return Video(out, round(total, 2), timings, tl.srt(captions), thumb, warnings)
