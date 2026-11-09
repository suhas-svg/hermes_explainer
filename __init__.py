"""Explainer Studio: turn any link, PDF, notes or topic into a narrated explainer video."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .schemas import RENDER_SCHEMA, VIDEOS_SCHEMA, VOICES_SCHEMA
from .tools import ExplainerTools, _setup_cli

logger = logging.getLogger(__name__)

_TOOLS = (
    ("explainer_render", RENDER_SCHEMA, "render", "Render a storyboard to a narrated explainer MP4."),
    ("explainer_voices", VOICES_SCHEMA, "voices", "List narrator voices for explainer videos."),
    ("explainer_videos", VIDEOS_SCHEMA, "list", "List or re-send explainer videos."),
)

_DELIVER = {
    "name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
    "options": ("origin", "local", "telegram", "discord", "email"), "strict": False,
    "help": "origin = the chat you set this up from; local = save only",
}


def register(ctx: Any) -> None:
    """Register the tools, /explainer, `hermes explainer`, the skill and the weekly-recap blueprint."""
    tools = ExplainerTools(ctx)
    for name, schema, method, description in _TOOLS:
        ctx.register_tool(name=name, toolset="explainer", schema=schema,
                          handler=getattr(tools, method), description=description)

    ctx.register_command("explainer", handler=tools.slash, description="Explainer Studio videos and voices",
                         args_hint="[list|voices LOCALE|doctor]")
    ctx.register_cli_command(name="explainer", help="Explainer Studio videos, playback and voices",
                             setup_fn=_setup_cli, handler_fn=tools.cli)

    skills_dir = Path(__file__).parent / "skills"
    for child in sorted(skills_dir.iterdir()) if skills_dir.is_dir() else ():
        if (child / "SKILL.md").is_file():
            ctx.register_skill(child.name, child / "SKILL.md")

    ctx.register_automation_blueprint(
        "weekly-recap-video",
        title="Weekly recap video",
        description="Every week, a short narrated video recapping the news on topics you choose.",
        category="weekly",
        schedule_template="{minute} {hour} * * {dow}",
        prompt_template=(
            "Load the explainer:explainer-video skill. Search the web for the most important developments "
            "of the past 7 days about: {topics}. Read at least three sources. Write a storyboard of 4-6 scenes "
            "(about {seconds} seconds of narration) that explains what happened and why it matters, with the "
            "source in each scene's note. Render it with explainer_render (aspect {aspect}) and reply with a "
            "3-bullet summary plus the media_tag line."
        ),
        slots=[
            {"name": "day", "type": "enum", "label": "Which day?", "default": "friday",
             "options": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")},
            {"name": "time", "type": "time", "label": "What time?", "default": "17:00",
             "help": "24h local time, e.g. 17:00"},
            {"name": "topics", "type": "text", "label": "Which topics?",
             "default": "AI research, open-source software"},
            {"name": "seconds", "type": "enum", "label": "How long?", "default": "90",
             "options": ("45", "90", "150")},
            {"name": "aspect", "type": "enum", "label": "Shape?", "default": "16:9",
             "options": ("16:9", "9:16")},
            _DELIVER,
        ],
        skills=("explainer:explainer-video",),
        tags=("weekly", "recap", "video", "explainer"),
    )
    logger.debug("explainer: registered %d tools, /explainer, hermes explainer, skill and blueprint", len(_TOOLS))
