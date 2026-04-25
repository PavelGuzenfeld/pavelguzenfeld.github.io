#!/usr/bin/env python3
"""Generate an MP3 narration of a Hugo blog post.

Usage:
    generate_audio.py <post.md> <output.mp3> [--voice MODEL.onnx]

Pipeline: markdown → cleaned text → Piper → WAV → ffmpeg → MP3.

Cleaning rules (chosen so a code-heavy blog post is listenable):
- Drop the YAML frontmatter.
- Drop fenced code blocks entirely (replaced with "code block omitted").
- Drop inline code spans, but keep the surrounding sentence.
- Drop tables (replaced with "table omitted").
- Drop image lines and HTML.
- Replace `[link text](url)` with just the link text.
- Convert headers to "Section: ..." so the narrator pauses.
- Drop URLs to godbolt.org / github.com / etc — there's no point reading
  alphanumeric short codes aloud.

The remaining prose is what gets narrated.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


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


# ---------- piper + ffmpeg ---------------------------------------------------

def synthesize(text: str, voice_path: Path, out_mp3: Path) -> None:
    out_mp3.parent.mkdir(parents=True, exist_ok=True)

    piper = subprocess.Popen(
        ["piper", "--model", str(voice_path), "--output_file", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-loglevel", "error", "-y",
            "-f", "wav", "-i", "pipe:0",
            "-codec:a", "libmp3lame", "-q:a", "4",
            str(out_mp3),
        ],
        stdin=piper.stdout,
    )
    assert piper.stdin is not None
    piper.stdin.write(text.encode("utf-8"))
    piper.stdin.close()
    piper.wait()
    ffmpeg.wait()
    if piper.returncode != 0 or ffmpeg.returncode != 0:
        raise RuntimeError(
            f"piper={piper.returncode} ffmpeg={ffmpeg.returncode}")


# ---------- main -------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path, help="path to a Hugo post .md")
    ap.add_argument("output", type=Path, help="path to write the MP3")
    ap.add_argument(
        "--voice",
        type=Path,
        default=Path("/voices/en_US-amy-medium.onnx"),
        help="Piper voice model (.onnx)",
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

    if not args.voice.exists():
        print(f"voice model not found: {args.voice}", file=sys.stderr)
        return 1

    synthesize(text, args.voice, args.output)
    print(f"wrote {args.output} ({args.output.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
