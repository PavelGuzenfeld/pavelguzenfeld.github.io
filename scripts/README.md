# Audio narration scripts

`generate_audio.py` reads a Hugo post `.md`, strips structural markdown
(frontmatter, code blocks, tables, images, raw URLs, HTML), applies
pronunciation rules, and emits an MP3 via Microsoft Edge TTS. The CI workflow
at `.github/workflows/audio.yaml` runs this on every changed post.

## Pronunciation control — three layers

The cleaner applies three layers of pronunciation rules in order. Each layer
is invisible to readers of the rendered HTML.

### 1. Built-in global rules

Defined in `PRONUNCIATION_RULES` at the top of `generate_audio.py`. These
cover the common stuff that appears across every post:

| Source | Narrated as |
|---|---|
| `-O2 -std=c++23` | "O2 optimization on C plus plus 23 standard" |
| `-O3`, `-Os`, `-Ofast` | "O3 optimization", "O size optimization", … |
| `-march=x86-64-v3` | "march x86-64 version 3" |
| `-ffast-math`, `-flto`, `-fno-rtti` | "fast math", "link time optimization", … |
| `c++23`, `C++` | "C plus plus 23", "C plus plus" |
| `__builtin_popcountll` | "the popcountll built-in" |
| `ns/op`, `ns/iter` | "nanoseconds per operation" |
| `4.6 GHz`, `48 KiB`, `2 MiB` | "4.6 gigahertz", "48 kilobytes", "2 megabytes" |
| `7×`, `1.6x` | "7 times", "1.6 times" |
| `CRTP`, `SIMD`, `HFT`, `GCC`, `LLVM` | letter-spelled |
| `IEEE` | "I triple E" |

Edit the list when a new term shows up across many posts.

### 2. Per-post overrides via frontmatter

For terms specific to one post, add an `audio.pronunciation` block to that
post's frontmatter. Keys are matched as plain text (escaped); values replace
them.

```yaml
---
title: "..."
audio:
  pronunciation:
    "Müller": "Mueller"          # avoid the German-language switch
    "ns/op":  "nanoseconds per operation"
    "L1d":    "L one D cache"
---
```

Frontmatter rules run *before* the built-ins, so a per-post entry wins on
overlap.

### 3. Inline overrides via the `pron` shortcode

Use the Hugo shortcode for one-off substitutions in the prose:

```markdown
The benchmark reports {{< pron "ns/op" "nanoseconds per operation" >}}.
```

- HTML readers see only the first argument.
- The audio script sees the shortcode in the source markdown and substitutes
  the second argument before TTS.

There's also a markdown-flavoured fallback: `[[shown|narrated]]`.
Use this when you don't want the Hugo shortcode delimiters in your source —
the bracket form survives copy-paste between editors.

## Voice selection

Default: `en-US-AndrewNeural` (English-only, male). Override with `--voice`.
**Avoid `*-MultilingualNeural` voices** for English-only posts — they
auto-detect non-English words (e.g. "Müller", "naïve") and switch language
mid-sentence.

Other tested male voices:

| Voice id | Notes |
|---|---|
| `en-US-AndrewNeural` | warm, conversational — current default |
| `en-US-GuyNeural` | classic, professional |
| `en-US-ChristopherNeural` | lower register |
| `en-US-EricNeural` | crisp |
| `en-US-BrianNeural` | newscaster |
| `en-GB-RyanNeural` | British |

## Local development

```bash
docker build -t blog-tts -f scripts/Dockerfile scripts/

# Preview the cleaned narration text (no TTS call)
docker run --rm -v $(pwd):/work blog-tts \
  python3 /scripts/generate_audio.py \
    /work/content/posts/foo.md /tmp/x.mp3 --text-only

# Generate the MP3 (needs network for the Edge TTS endpoint)
docker run --rm --network host -v $(pwd):/work blog-tts \
  python3 /scripts/generate_audio.py \
    /work/content/posts/foo.md /work/static/audio/foo.mp3
```
