"""JSON Schemas for the Explainer Studio tools."""

from __future__ import annotations

from typing import Any

from .slides import THEMES

RENDER_SCHEMA: dict[str, Any] = {
    "description": (
        "Render a narrated explainer video (MP4) from a storyboard you write: one slide per scene with a "
        "heading, bullets that appear as the narrator reaches them, word-by-word highlighted captions, an "
        "optional image, a title card and a progress bar, voiced by a natural neural voice. Also writes SRT "
        "captions, a transcript and a thumbnail. Put the returned media_tag line in your reply to attach the "
        "video. Load the explainer:explainer-video skill first for how to write a good storyboard."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Video title, shown on the title card."},
            "subtitle": {"type": "string", "description": "One line under the title (e.g. the source)."},
            "aspect": {"type": "string", "enum": ["16:9", "9:16"],
                       "description": "16:9 for YouTube/slides (default), 9:16 for Shorts, Reels, TikTok."},
            "theme": {"type": "string", "enum": sorted(THEMES), "description": "Colour theme."},
            "voice": {"type": "string",
                      "description": "Edge neural voice, e.g. en-US-AndrewMultilingualNeural (see explainer_voices)."},
            "rate": {"type": "string", "description": "Speaking rate, e.g. +5% or -10%."},
            "captions": {"type": "boolean", "description": "Burn in highlighted captions (default true)."},
            "scenes": {
                "type": "array",
                "description": "Scenes in order, 3-8 is typical. Plain spoken text only in narration.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string", "description": "Slide heading, a few words."},
                        "narration": {"type": "string",
                                      "description": "What the voice says on this slide, 1-4 sentences. Mention each "
                                                     "bullet's key word so it appears in sync."},
                        "bullets": {"type": "array", "items": {"type": "string"},
                                    "description": "0-5 short points (under 90 characters each)."},
                        "image": {"type": "string",
                                  "description": "Optional https image URL or local file path shown beside the text."},
                        "note": {"type": "string", "description": "Optional small footer, e.g. a source."},
                    },
                    "required": ["heading", "narration"],
                },
            },
        },
        "required": ["title", "scenes"],
        "additionalProperties": False,
    },
}

VOICES_SCHEMA: dict[str, Any] = {
    "description": "List the narrator voices available for explainer videos, filtered by language/locale and gender.",
    "parameters": {
        "type": "object",
        "properties": {
            "locale": {"type": "string", "description": "Language or locale prefix, e.g. en, en-GB, es, hi-IN. Default en."},
            "gender": {"type": "string", "enum": ["Male", "Female"]},
        },
        "additionalProperties": False,
    },
}

VIDEOS_SCHEMA: dict[str, Any] = {
    "description": "List explainer videos made so far, newest first, with video, caption and transcript paths. "
                   "Pass `id` to re-send one video.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Video id from a previous listing, to attach it again."},
            "limit": {"type": "integer", "description": "How many to list (1-50, default 10)."},
        },
        "additionalProperties": False,
    },
}
