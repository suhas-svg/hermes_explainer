---
name: explainer-video
description: "Turn a link, PDF, paper, notes or topic into a narrated explainer video (MP4) with Explainer Studio."
version: 1.0.0
author: suhas-svg
license: MIT
metadata:
  hermes:
    tags: [video, explainer, slides, captions, shorts]
---

# Explainer video workflow

Use this skill when the user asks for an explainer, a video summary, "a video
about...", a short/reel/TikTok explaining something, or a narrated walkthrough of
a source.

## 1. Read first, then plan

- Read the real sources before writing: fetch the URL, open the PDF, read the
  notes, search the web. Never storyboard from memory when a source was given.
- Find the one question the video answers, then the 3-6 steps or ideas that answer
  it, with the concrete numbers, names and examples.

## 2. Write the storyboard

- **Length:** about 150 spoken words per minute. 60 seconds is ~150 words over
  3-5 scenes. Default to 60-90 seconds unless asked.
- **Scene 1 is the hook:** the question or the surprising fact. The last scene is
  the takeaway.
- **heading:** a few words, a claim or a step ("Step two: training day"), not a
  topic label.
- **narration:** 1-4 short spoken sentences. Plain text only: no markdown, URLs,
  emoji or stage directions. Write numbers as they are said.
- **bullets:** 0-5 points of 2-6 words each. The narration must say each bullet's
  key word, in order: that is when the bullet appears on screen. Bullets summarise;
  the narration explains.
- **note:** the source for that scene ("Source: Nature, 2024") when facts come from
  one.
- **image:** only an https URL or local path you have actually seen (a figure from
  the paper, a diagram from the page). Never invent image URLs. Local files must
  be in the working directory, the plugin's data folder or a configured
  `image_dirs` folder; download a figure into the working directory first if
  needed. An image that cannot be used is skipped with a warning.
- **aspect:** `9:16` when the user says short, reel, TikTok, vertical or phone;
  otherwise `16:9`. Pick a `theme` that suits the subject (paper for academic,
  ocean or forest for science and nature, sunset for culture, midnight default).

## 3. Render and deliver

1. Call `explainer_render` with `title`, a short `subtitle` and `scenes`.
2. If it returns an error, fix exactly what it names and call it again.
3. Reply with a one-line summary, the duration and chapter list, and the returned
   `media_tag` line exactly, on its own line, so the MP4 is attached. Mention the
   SRT and transcript paths if the user may want to upload or edit them.

## Options

- Other languages: call `explainer_voices` with a locale (`es`, `fr-FR`, `hi-IN`),
  pass that `voice`, and write the storyboard in that language.
- Faster or slower delivery: `rate` such as `+8%` or `-6%`.
- To send an earlier video again: `explainer_videos` with its `id`.
