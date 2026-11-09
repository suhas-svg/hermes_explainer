"""Video storage: <data dir>/videos/<date>-<slug>/{explainer.mp4, captions.srt, transcript.md, thumbnail.png, video.json}."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .render import Video
from .storyboard import Storyboard


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:48].strip("-") or "explainer"


def new_video_dir(root: Path, title: str) -> Path:
    base = root / "videos" / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}"
    path, n = base, 2
    while path.exists():
        path, n = base.with_name(f"{base.name}-{n}"), n + 1
    path.mkdir(parents=True)
    return path


def clock(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def save(board: Storyboard, video: Video, folder: Path) -> dict[str, Any]:
    (folder / "captions.srt").write_text(video.srt, encoding="utf-8")
    rows = [f"# {board.title}", ""]
    if board.subtitle:
        rows += [board.subtitle, ""]
    for scene in video.scenes:
        rows += [f"## {scene.heading}  [{clock(scene.start)}]", "", scene.narration, ""]
    (folder / "transcript.md").write_text("\n".join(rows), encoding="utf-8")
    meta = {
        "title": board.title,
        "subtitle": board.subtitle,
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "duration": video.duration,
        "duration_text": clock(video.duration),
        "aspect": board.aspect,
        "theme": board.theme,
        "voice": board.voice,
        "chapters": [{"title": s.heading, "start": clock(s.start)} for s in video.scenes],
        "video": str(video.path),
        "captions": str(folder / "captions.srt"),
        "transcript": str(folder / "transcript.md"),
        "thumbnail": str(video.thumbnail),
    }
    (folder / "video.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def list_videos(root: Path, limit: int = 20) -> list[dict[str, Any]]:
    folder = root / "videos"
    if not folder.is_dir():
        return []
    rows = []
    for child in sorted(folder.iterdir(), reverse=True):
        meta_file = child / "video.json"
        if meta_file.is_file() and (child / "explainer.mp4").is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            rows.append({"id": child.name, **{k: meta.get(k) for k in
                         ("title", "created", "duration_text", "aspect", "video", "captions", "transcript",
                          "thumbnail", "chapters")}})
        if len(rows) >= limit:
            break
    return rows
