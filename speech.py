"""Narration with Microsoft Edge's online voices (edge-tts), with per-word timestamps."""

from __future__ import annotations

import asyncio
import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

# (text, voice, rate, out_mp3) -> [(word, start_seconds, end_seconds)]; injectable for tests.
Speak = Callable[[str, str, str, Path], Awaitable[list[tuple[str, float, float]]]]
_TICKS = 10_000_000  # edge-tts offsets are in 100 ns units
_VOICE_CACHE_SECONDS = 7 * 24 * 3600


class SpeechError(RuntimeError):
    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


def _edge():
    try:
        import edge_tts  # noqa: PLC0415 - optional until first use
    except ImportError as exc:
        raise SpeechError("The edge-tts package is not installed.",
                          hint="Run `hermes plugins install explainer --install-deps` or `hermes pm install`.") from exc
    return edge_tts


async def edge_speak(text: str, voice: str, rate: str, out: Path) -> list[tuple[str, float, float]]:
    communicate = _edge().Communicate(text, voice, rate=rate, boundary="WordBoundary", receive_timeout=60)
    words: list[tuple[str, float, float]] = []
    with out.open("wb") as audio:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / _TICKS
                words.append((chunk["text"], start, start + chunk["duration"] / _TICKS))
    return words


def run_async(coro: Awaitable[Any]) -> Any:
    """Run a coroutine from sync code, even when the caller's thread already runs a loop."""
    result: dict[str, Any] = {}

    def target() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised in the caller's thread
            result["error"] = exc

    worker = threading.Thread(target=target, name="explainer-speech", daemon=True)
    worker.start()
    worker.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


class _Pacer:
    """Spaces request starts: the Edge service answers rapid back-to-back requests with no audio."""

    def __init__(self, gap: float) -> None:
        self.gap, self.next_start, self.lock = gap, 0.0, asyncio.Lock()

    async def wait(self) -> None:
        async with self.lock:
            now = time.monotonic()
            if self.next_start > now:
                await asyncio.sleep(self.next_start - now)
            self.next_start = max(now, self.next_start) + self.gap


async def _one(speak: Speak, index: int, text: str, voice: str, rate: str, out: Path, sem: asyncio.Semaphore,
               pacer: _Pacer, attempts: int, backoff: float) -> list[Word]:
    async with sem:
        for attempt in range(1, attempts + 1):
            await pacer.wait()
            try:
                raw = await speak(text, voice, rate, out)
                if out.is_file() and out.stat().st_size > 0 and raw:
                    return [Word(w, s, e) for w, s, e in raw]
                raise SpeechError("the voice service returned no audio")
            except Exception as exc:
                if attempt == attempts:
                    raise SpeechError(f"Could not narrate scene {index + 1} with {voice}: {exc}",
                                      hint="Check the internet connection and that the voice exists.") from exc
                await asyncio.sleep(min(8.0, backoff * 2 ** (attempt - 1)) * random.uniform(0.75, 1.25))
    raise AssertionError("unreachable")


async def _all(speak: Speak, texts: list[str], voice: str, rate: str, workdir: Path, concurrency: int,
               attempts: int, gap: float, backoff: float) -> list[tuple[Path, list[Word]]]:
    sem, pacer = asyncio.Semaphore(concurrency), _Pacer(gap)
    paths = [workdir / f"scene_{i:02d}.mp3" for i in range(len(texts))]
    words = await asyncio.gather(*(_one(speak, i, t, voice, rate, p, sem, pacer, attempts, backoff)
                                   for i, (t, p) in enumerate(zip(texts, paths))))
    return list(zip(paths, words))


def narrate(texts: list[str], workdir: Path, *, voice: str, rate: str = "+0%", speak: Optional[Speak] = None,
            concurrency: int = 3, attempts: int = 6, gap: float = 0.6, backoff: float = 1.5) -> list[tuple[Path, list[Word]]]:
    workdir.mkdir(parents=True, exist_ok=True)
    return run_async(_all(speak or edge_speak, texts, voice, rate, workdir, concurrency, attempts, gap, backoff))


async def _list_voices() -> list[dict[str, Any]]:
    return await _edge().list_voices()


def list_voices(cache: Path, *, fetch: Optional[Callable[[], Awaitable[list[dict[str, Any]]]]] = None) -> list[dict[str, Any]]:
    if cache.is_file() and time.time() - cache.stat().st_mtime < _VOICE_CACHE_SECONDS:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            pass
    try:
        voices = run_async((fetch or _list_voices)())
    except SpeechError:
        raise
    except Exception as exc:
        raise SpeechError(f"Could not fetch the Edge voice list: {exc}", hint="Check the internet connection.") from exc
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(voices), encoding="utf-8")
    return voices
