#!/usr/bin/env python3
"""Generate an MP3 narration of a Hugo blog post via Microsoft Edge TTS.

Usage:
    generate_audio.py <post.md> <output.mp3> [--voice VOICE] [--rate RATE]

Pipeline: markdown → cleaned text → edge-tts (Microsoft Neural voice) → MP3.

Cleaning rules (chosen so a code-heavy blog post is listenable):
- Drop the YAML frontmatter.
- Drop fenced code blocks entirely (replaced with "code block omitted").
- Drop inline code spans, but keep the surrounding sentence.
- Drop tables (replaced with "table omitted").
- Drop image lines and HTML.
- Replace `[link text](url)` with just the link text.
- Convert headers to "Section: ..." so the narrator pauses.
- Drop bare URLs — there's no point reading alphanumeric short codes aloud.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import edge_tts


# ---------- markdown → narration text ----------------------------------------

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
FENCED_CODE_RE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
INDENTED_CODE_RE = re.compile(r"(?:^    .*\n)+", re.MULTILINE)
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
TABLE_RE = re.compile(r"(?:^\|.*\|\s*\n)+", re.MULTILINE)
IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
BARE_URL_RE = re.compile(r"https?://\S+")
# Real HTML tags only — won't eat C++ `<header.h>` or `<int, int>` mid-prose.
HTML_TAG_RE = re.compile(r"</?[a-z][a-z0-9]*(?:\s[^>]*)?>", re.IGNORECASE)
NAMESPACE_NOISE_RE = re.compile(r"\b\w+::")
EMPHASIS_RE = re.compile(r"(\*\*|__|\*|_)(.+?)\1")


def clean_markdown(md: str) -> str:
    body = FRONTMATTER_RE.sub("", md, count=1)

    # Drop code blocks first so their contents aren't processed by other rules.
    body = FENCED_CODE_RE.sub("\n[code block omitted]\n", body)
    body = INDENTED_CODE_RE.sub("\n[code block omitted]\n", body)

    # Tables
    body = TABLE_RE.sub("\n[table omitted]\n", body)

    # Images, then links → keep link text only.
    body = IMAGE_RE.sub("", body)
    body = LINK_RE.sub(r"\1", body)

    # Bare URLs the markdown didn't bracket — drop them entirely.
    body = BARE_URL_RE.sub("", body)

    # HTML
    body = HTML_TAG_RE.sub("", body)

    # `ankerl::nanobench::doNotOptimizeAway` reads as "colon colon" otherwise —
    # collapse repeated namespace prefixes to just the last segment.
    body = NAMESPACE_NOISE_RE.sub("", body)

    # Emphasis: keep the inner text.
    body = EMPHASIS_RE.sub(r"\2", body)

    # Inline code spans: keep the inner identifier so a sentence still parses.
    body = INLINE_CODE_RE.sub(r"\1", body)

    # Headers → "Section: title"
    out_lines: list[str] = []
    for line in body.splitlines():
        h = re.match(r"^(#{1,6})\s+(.*)", line)
        if h:
            out_lines.append(f"Section: {h.group(2).strip()}.")
        else:
            out_lines.append(line)
    body = "\n".join(out_lines)

    # Collapse multiple blank lines.
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


# ---------- edge-tts ---------------------------------------------------------

async def synthesize(text: str, voice: str, rate: str, out_mp3: Path) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out_mp3))


# ---------- main -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="path to a Hugo post .md")
    ap.add_argument("output", type=Path, help="path to write the MP3")
    ap.add_argument(
        "--voice",
        default="en-US-AndrewMultilingualNeural",
        help="edge-tts voice id (try en-US-GuyNeural, en-US-TonyNeural, "
             "en-US-BrianMultilingualNeural, en-GB-RyanNeural)",
    )
    ap.add_argument(
        "--rate",
        default="+0%",
        help="speaking rate offset, e.g. '+10%' or '-5%'",
    )
    ap.add_argument(
        "--text-only",
        action="store_true",
        help="just print the cleaned text, don't synthesize",
    )
    args = ap.parse_args()

    md = args.input.read_text(encoding="utf-8")
    text = clean_markdown(md)

    if args.text_only:
        sys.stdout.write(text)
        return 0

    asyncio.run(synthesize(text, args.voice, args.rate, args.output))
    print(f"wrote {args.output} ({args.output.stat().st_size:,} bytes) "
          f"voice={args.voice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
