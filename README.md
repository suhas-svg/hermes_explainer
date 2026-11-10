# Explainer Studio for Hermes

Turn anything Hermes can read (a link, a PDF, a paper, your notes, or just a
topic) into a narrated explainer video. You get designed slides, a natural
neural voice, bullets that appear as the narrator reaches them, and captions
that highlight each word as it is spoken. Videos come out as 16:9 for YouTube
or 9:16 for Shorts, Reels and TikTok, with SRT captions, a transcript and a
thumbnail alongside. Everything is rendered on your machine, free.

```
You: Read https://en.wikipedia.org/wiki/Rayleigh_scattering and make me a
     45-second vertical (9:16) explainer video about why the sky is blue.
Hermes: 43-second vertical explainer on Rayleigh scattering: blue light
        scatters about ten times more than red off nitrogen and oxygen.
        Duration: 00:43, 9:16, 4 chapters: Why Is the Sky Blue (00:02),
        Sunlight Is All Colors (00:11), Tiny Air Scatters Blue (00:20),
        Blue Sky Red Sunset (00:31).
        MEDIA:.../videos/20261109-175118-why-is-the-sky-blue/explainer.mp4
```

On Telegram, Discord and other messaging platforms the video arrives as a file
you can play right in the chat.

## What it adds

| Surface | What you get |
| --- | --- |
| Tools | `explainer_render`, `explainer_voices`, `explainer_videos` |
| Skill | `explainer:explainer-video`: how to read sources and write a storyboard that explains well on screen |
| Automation blueprint | `explainer:weekly-recap-video`: a weekly news recap video on topics you choose, delivered to your chat |
| Slash command | `/explainer list`, `/explainer voices LOCALE`, `/explainer doctor` |
| CLI | `hermes explainer list`, `hermes explainer play [ID]`, `hermes explainer voices [LOCALE]`, `hermes explainer doctor` |

| Tool | Does |
| --- | --- |
| `explainer_render` | Takes a storyboard (title, scenes with heading, narration, bullets, an optional image and source note). It voices every scene, using word-level timestamps to reveal each bullet when the narrator says it and to highlight each caption word as it is spoken. It draws the slides in one of five themes, adds a title card and a progress bar, normalises loudness to -16 LUFS and encodes an H.264/AAC MP4. Writes `explainer.mp4`, `captions.srt`, `transcript.md`, `thumbnail.png` and `video.json`. |
| `explainer_voices` | Lists the 300+ narrator voices by locale and gender, so videos can be in Spanish, Hindi, Japanese and more. |
| `explainer_videos` | Lists past videos, or re-sends one by id. |

A prompt alone can't do this. The model writes the storyboard, and the plugin
turns it into a finished video:

- word-timed narration with throttle-aware pacing and retries;
- bullet reveals synced to the moment each one is spoken;
- karaoke captions plus a matching SRT;
- layout that fits text and images at either aspect ratio;
- picture and sound kept exactly in step;
- a library of videos you can replay or resend.

## Requirements

- Hermes Agent 0.22.5 or newer.
- An internet connection (voices are synthesized online, see Privacy).
- **ffmpeg** to encode the video. Hermes ships one; otherwise any ffmpeg on
  `PATH` works, or set `ffmpeg_path`.
- Python dependencies: [`edge-tts`](https://github.com/rany2/edge-tts) and
  [Pillow](https://python-pillow.org/), installed by Hermes with the plugin.
- Fonts: picks Segoe UI, Arial, Helvetica, DejaVu or Liberation Sans if present,
  and falls back to Pillow's built-in font. Set `font_path` and `font_bold_path`
  to use your own.

## Install

```bash
hermes plugins install suhas-svg/hermes_explainer --enable
```

Once the plugin is in the curated catalog:

```bash
hermes plugins install explainer --enable
```

Then check the setup:

```bash
hermes explainer doctor
```

## Try it

- "Make a 60-second explainer video about this article: <link>"
- "Turn this PDF into a 9:16 short explaining the main result."
- "Explain how HTTPS works as a 90-second video, paper theme."
- "Haz un video explicativo de un minuto en español sobre <tema>."
- With the Zotero Research plugin: "Make an explainer video about the key idea
  of the newest paper in my Zotero library."
- Schedule `explainer:weekly-recap-video` with `/blueprint` for a recap every
  Friday.

## Settings

Set under `plugins.entries.explainer.settings` in `config.yaml`, for example
`hermes config set plugins.entries.explainer.settings.theme ocean`.

| Key | Default | Meaning |
| --- | --- | --- |
| `voice` | `en-US-AndrewMultilingualNeural` | Default narrator voice |
| `theme` | `midnight` | `midnight`, `paper`, `ocean`, `sunset` or `forest` |
| `aspect` | `16:9` | Default shape: `16:9` or `9:16` |
| `max_scenes` | `12` | Most scenes one video may have |
| `max_chars` | `6000` | Most narration characters (about 6 minutes) |
| `concurrency` | `3` | Scenes narrated in parallel |
| `ffmpeg_path` | empty | ffmpeg to use; empty means find it on `PATH` |
| `font_path` | empty | Body font (.ttf/.otf); empty picks a system font |
| `font_bold_path` | empty | Heading and caption font |
| `image_dirs` | empty | Extra folders local scene images may come from |

Videos are stored in the plugin's data folder
(`<HERMES_HOME>/plugin-data/explainer/videos/`), one folder per video.

## Privacy

- **Network:** the narration text of each scene is sent to Microsoft's online
  neural text-to-speech service (the one behind Microsoft Edge's Read Aloud)
  through the open-source `edge-tts` library. No account or API key is used.
  Don't make videos from text you are not willing to send to Microsoft. The
  voice list is fetched from the same service and cached for a week. When a
  scene's `image` is an `https://` URL, the plugin downloads it (capped at 8 MB,
  20-second timeout, no proxy). It refuses hosts that resolve to loopback,
  private (RFC 1918 / ULA), link-local (including 169.254.169.254) or other
  non-public addresses, checks the address it actually connects to, and checks
  every redirect hop the same way; `http://` and other schemes are refused.
- **Local files:** a scene's `image` given as a local path is read only from the
  working directory, the plugin's data folder or the folders in `image_dirs`.
  The plugin also reads system or configured font files, and writes only inside
  its own data folder.
- **Subprocesses:** ffmpeg runs locally to decode the narration and encode the
  video. `hermes explainer play` opens a video in your default player.

Nothing else leaves your machine. Videos, captions, transcripts and the cached
voice list stay local.

## Development

```bash
python -m pip install pytest edge-tts Pillow
python -m pytest -q
```

Tests inject a fake voice, so they run offline. The rendering tests need ffmpeg
and ffprobe on `PATH` and are skipped without them.

## License

MIT
